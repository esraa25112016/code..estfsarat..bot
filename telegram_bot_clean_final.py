import datetime
import gspread
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from oauth2client.service_account import ServiceAccountCredentials
from telegram.helpers import escape_markdown

# إعداداتك هنا
BOT_TOKEN = "8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY"
ADMINS = [1969054373]
GROUP_CHAT_ID = -1002606054225

GOOGLE_SHEET_ID = "1yWJDu9I_T30wddt2lkgEO_m6sr1_SDx-WiDUkoZ9UTI"
SHEET_NAME = "Students Data"
SUBSCRIBERS_SHEET_NAME = "المشتركين"
QUESTIONS_SHEET_NAME = "استفسارات الطلاب"

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME)
subscribers_sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SUBSCRIBERS_SHEET_NAME)
questions_sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(QUESTIONS_SHEET_NAME)

ASK_NAME, ASK_PHONE, UPDATE_NAME, UPDATE_PHONE, ASK_QUESTION, BROADCAST, PREVIEW_CONFIRM, ASK_ANOTHER = range(8)
admin_round_robin = 0
pending_questions = {}
handled_questions = set()

# --- دوال البث الجماعي (Broadcast) ---
async def ask_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("📝 اكتب نص الرسالة الجماعية (يمكنك كتابة (اسم الطالب) ليتم استبدالها باسم الطالب).")
    return BROADCAST

async def preview_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["broadcast_template"] = update.message.text
    records = sheet.get_all_records()
    sample_name = records[0].get("الاسم", "الطالب") if records else "الطالب"
    preview_message = context.user_data["broadcast_template"].replace("(اسم الطالب)", sample_name)
    keyboard = [
        [InlineKeyboardButton("✅ نعم، أرسل", callback_data="confirm_broadcast")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_broadcast")]
    ]
    await update.message.reply_text(f"📤 *معاينة الرسالة:*\n\n{preview_message}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return PREVIEW_CONFIRM

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    template = context.user_data.get("broadcast_template", "")
    records = sheet.get_all_records()
    count = 0
    for row in records:
        student_id = row.get("Telegram ID")
        student_name = row.get("الاسم", "الطالب")
        if student_id:
            try:
                message = template.replace("(اسم الطالب)", student_name)
                await context.bot.send_message(chat_id=int(student_id), text=message)
                count += 1
            except Exception as e:
                print(f"❌ Failed for {student_name}: {e}")
    await query.edit_message_text(f"✅ تم إرسال الرسالة إلى {count} طالب.")
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ تم الإلغاء.")
    return ConversationHandler.END

# --- الدوال الأساسية ---

def is_user_registered(user_id):
    for row in sheet.get_all_records():
        if str(row.get("Telegram ID", "")).strip() == str(user_id):
            return row
    return None

def is_subscribed(user_id):
    for row in subscribers_sheet.get_all_records():
        if str(row.get("Telegram ID", "")).strip() == str(user_id):
            return True
    return False

def main_keyboard(user_id):
    # بناء الكيبورد بحسب حالة الطالب أو الادمن
    keyboard = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث البيانات", callback_data="update")]
    ]
    if is_subscribed(user_id):
        keyboard.append([InlineKeyboardButton("✍️ استفسار دراسي", callback_data="study_question")])
    if user_id in ADMINS:
        keyboard.append([InlineKeyboardButton("👨‍💻 لوحة تحكم الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["ابدأ ✅"]]
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    await update.message.reply_text("اضغط على 'ابدأ ✅' للمتابعة", reply_markup=markup)

async def handle_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = is_user_registered(user_id)
    if user_data:
        await update.message.reply_text("أنت مسجل بالفعل، اختر من القائمة:", reply_markup=main_keyboard(user_id))
        return ConversationHandler.END
    else:
        await update.message.reply_text("أهلاً بيك! اكتب اسمك بالكامل:")
        return ASK_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("تمام ✅، دلوقتي ابعت رقم تليفونك:")
    return ASK_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("name")
    phone = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username or "بدون يوزر"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([name, phone, str(user_id), username, timestamp])
    await update.message.reply_text("✅ تم تسجيلك بنجاح!")
    await update.message.reply_text("اختر من القائمة:", reply_markup=main_keyboard(user_id))
    return ConversationHandler.END

async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✏️ اكتب اسمك الجديد:")
    return UPDATE_NAME

async def update_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_name"] = update.message.text.strip()
    await update.message.reply_text("📞 اكتب رقمك الجديد:")
    return UPDATE_PHONE

async def update_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = context.user_data.get("new_name")
    new_phone = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username or "بدون يوزر"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cell = sheet.find(str(user_id))
    if cell:
        sheet.update(range_name=f"A{cell.row}:E{cell.row}", values=[[new_name, new_phone, str(user_id), username, timestamp]])
        await update.message.reply_text("✅ تم تحديث بياناتك بنجاح!", reply_markup=main_keyboard(user_id))
    else:
        await update.message.reply_text("❌ لم يتم العثور على بياناتك.")
    return ConversationHandler.END

async def handle_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = is_user_registered(user_id)
    if data:
        text = (
            f"👤 *اسمك:* {escape_markdown(str(data.get('الاسم', 'غير متوفر')), version=2)}\n"
            f"📱 *رقمك:* {escape_markdown(str(data.get('رقم التليفون', 'غير متوفر')), version=2)}\n"
            f"🔗 *Username:* {escape_markdown('@' + data['Username'], version=2) if data.get('Username') else 'غير متوفر'}"
        )
        await query.edit_message_text(text=text, parse_mode="MarkdownV2", reply_markup=main_keyboard(user_id))
    else:
        await query.edit_message_text("❌ لم يتم العثور على بياناتك.")

def generate_ref():
    now = datetime.datetime.now().strftime("%Y%m%d")
    suffix = "".join(str(i) for i in [datetime.datetime.now().second, datetime.datetime.now().microsecond][::-1])[-3:]
    return f"Q{now}_{suffix}"

def extract_ref_from_message(message_text):
    match = re.search(r'Q\d{8}_\d{3,}', message_text or "")
    if match:
        return match.group(0).strip()
    for line in (message_text or "").splitlines():
        if "الرقم المرجعي" in line:
            return line.split(":")[-1].strip()
    return None

async def handle_study_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("✍️ اكتب سؤالك نصيًا أو ابعت صورة وسيصل للإدمن.")
    return ASK_QUESTION

async def receive_study_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_subscribed(user.id):
        await update.message.reply_text("❌ الخدمة متاحة فقط للمشتركين.")
        return ConversationHandler.END
    data = is_user_registered(user.id)
    question = update.message.text or '📷 صورة مرفقة'
    photo = update.message.photo[-1].file_id if update.message.photo else None
    global admin_round_robin
    if not ADMINS:
        await update.message.reply_text("❌ لا يوجد إدمن متاح حالياً.")
        return ConversationHandler.END
    admin_id = ADMINS[admin_round_robin % len(ADMINS)]
    admin_round_robin += 1

    ref = generate_ref()
    pending_questions[ref] = {
        "student_id": user.id,
        "student_name": data.get("الاسم", user.full_name),
        "student_username": user.username,
        "question": question,
        "photo": photo,
        "assigned_admin": admin_id,
        "ref": ref,
        "asked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "answer": "",
        "answered_at": "",
        "admin_name": "",
        "admin_id": "",
    }

    msg = (
        f"سؤال جديد:\n"
        f"👤 <b>اسم الطالب:</b> {data.get('الاسم', user.full_name)}\n"
        f"🆔 <b>ID:</b> {user.id}\n"
        f"📄 <b>السؤال:</b> {question}\n"
        f"🔢 <b>الرقم المرجعي:</b> {ref}\n"
    )
    if photo:
        await context.bot.send_photo(admin_id, photo, caption=msg, parse_mode="HTML")
    else:
        await context.bot.send_message(admin_id, msg, parse_mode="HTML")
    keyboard = [
        [InlineKeyboardButton("نعم، أريد", callback_data="ask_another_yes")],
        [InlineKeyboardButton("لا، شكرًا", callback_data="ask_another_no")]
    ]
    await update.message.reply_text(
        "✅ تم استلام سؤالك. سيتم الرد عليك قريبًا.\n\nهل تريد إرسال استفسار آخر؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_ANOTHER

async def handle_ask_another(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "ask_another_yes":
        await query.edit_message_text("اكتب سؤالك الجديد 👇")
        return ASK_QUESTION
    else:
        await query.edit_message_text("شكرًا لك! إذا احتجت أي شيء يمكنك العودة في أي وقت.")
        return ConversationHandler.END

async def admin_reply_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        return
    if not update.message.reply_to_message:
        return
    ref = None
    if update.message.reply_to_message.text:
        ref = extract_ref_from_message(update.message.reply_to_message.text)
    if not ref and getattr(update.message.reply_to_message, 'caption', None):
        ref = extract_ref_from_message(update.message.reply_to_message.caption)
    if not ref:
        await update.message.reply_text("تعذر معرفة الرقم المرجعي لهذا السؤال.")
        return
    answer = update.message.text
    q = pending_questions.get(ref)
    if not q:
        await update.message.reply_text("❌ الرقم المرجعي غير صحيح أو تم الرد بالفعل.")
        return
    if q["assigned_admin"] != user_id:
        await update.message.reply_text("❌ لا يمكنك الرد على سؤال غير مخصص لك.")
        return
    if ref in handled_questions:
        await update.message.reply_text("تم الرد على هذا السؤال بالفعل.")
        return
    q["admin_name"] = update.effective_user.full_name
    q["admin_id"] = user_id
    q["answer"] = answer
    q["answered_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(q["student_id"], f"رد الإدمن على سؤالك ({ref}):\n{answer}")
    group_msg = (
        f"❓ <b>سؤال جديد</b>\n"
        f"👤 <b>الطالب:</b> {q['student_name']} (@{q['student_username']})\n"
        f"📝 <b>السؤال:</b> {q['question']}\n"
        f"🔢 <b>الرقم المرجعي:</b> {ref}\n\n"
        f"✅ <b>رد الإدمن:</b> {answer}\n"
        f"👤 <b>اسم الأدمن:</b> {q['admin_name']} | <b>ID:</b> {q['admin_id']}\n"
        f"⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    if q["photo"]:
        await context.bot.send_photo(GROUP_CHAT_ID, q["photo"], caption=group_msg, parse_mode="HTML")
    else:
        await context.bot.send_message(GROUP_CHAT_ID, group_msg, parse_mode="HTML")
    questions_sheet.append_row([
        q["ref"], q["student_name"], q["student_id"], q["student_username"],
        q["question"], q["photo"], answer, q["admin_name"], q["admin_id"], q["asked_at"], q["answered_at"]
    ])
    handled_questions.add(ref)
    del pending_questions[ref]
    await update.message.reply_text("✅ تم إرسال الرد وحفظه.")

# لوحة تحكم الأدمن (زر جماعي)
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        if update.message:
            await update.message.reply_text("❌ ليس لديك صلاحية الوصول لهذه القائمة.")
        elif update.callback_query:
            await update.callback_query.answer("❌ ليس لديك صلاحية.", show_alert=True)
        return
    keyboard = [[InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="broadcast")]]
    if update.message:
        await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

# ConversationHandler للرسائل الجماعية
broadcast_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(ask_broadcast_message, pattern="^broadcast$")],
    states={
        BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, preview_broadcast)],
        PREVIEW_CONFIRM: [
            CallbackQueryHandler(execute_broadcast, pattern="^confirm_broadcast$"),
            CallbackQueryHandler(cancel_broadcast, pattern="^cancel_broadcast$")
        ]
    },
    fallbacks=[]
)

# ConversationHandler الرئيسي
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^ابدأ ✅$"), handle_start_button),
            CallbackQueryHandler(handle_update, pattern="^update$"),
            CallbackQueryHandler(handle_study_question, pattern="^study_question$"),
            CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            UPDATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_name)],
            UPDATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_phone)],
            ASK_QUESTION: [MessageHandler(filters.TEXT | filters.PHOTO, receive_study_question)],
            ASK_ANOTHER: [CallbackQueryHandler(handle_ask_another, pattern="^ask_another_(yes|no)$")],
        },
        fallbacks=[]
    )
    app.add_handler(conv_handler)
    app.add_handler(broadcast_conv)
    app.add_handler(CallbackQueryHandler(handle_view, pattern="^view$"))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, admin_reply_direct))
    print("✅ Bot is running...")
    app.run_polling()
