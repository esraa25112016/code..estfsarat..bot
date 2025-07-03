import datetime
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# ====== الإعدادات ======
BOT_TOKEN = "8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY"
ADMINS = [1969054373, 411966667]
GROUP_CHAT_ID = -1002606054225

GOOGLE_SHEET_ID = "1yWJDu9I_T30wddt2lkgEO_m6sr1_SDx-WiDUkoZ9UTI"
SHEET_NAME = "Students Data"
SUBSCRIBERS_SHEET_NAME = "المشتركين"

# ====== ربط جوجل شيت ======
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME)
subscribers_sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SUBSCRIBERS_SHEET_NAME)

# ====== حالات المحادثة ======
ASK_NAME, ASK_PHONE, ASK_QUESTION, UPDATE_NAME, UPDATE_PHONE = range(5)

# ====== الكاش والبيانات ======
USERS_CACHE = {}
SUBSCRIBERS_CACHE = set()
admin_round_robin = 0
student_questions = {}  # uid -> list of (type, content, timestamp)

def refresh_cache():
    global USERS_CACHE, SUBSCRIBERS_CACHE
    USERS_CACHE.clear()
    for row in sheet.get_all_records():
        uid = str(row.get("Telegram ID", "")).strip()
        if uid:
            USERS_CACHE[uid] = row
    SUBSCRIBERS_CACHE = {
        str(r.get("Telegram ID", "")).strip()
        for r in subscribers_sheet.get_all_records()
    }

refresh_cache()

def is_registered(uid):
    return str(uid) in USERS_CACHE

def is_sub(uid):
    return str(uid) in SUBSCRIBERS_CACHE

def generate_ref():
    now = datetime.datetime.now()
    return f"Q{now.strftime('%Y%m%d')}_{now.strftime('%S%f')[:4]}"

def main_keyboard(uid):
    kb = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث بياناتك", callback_data="update")],
    ]
    if is_sub(uid):
        kb.append([InlineKeyboardButton("✍️ استفسار دراسي", callback_data="study_question")])
    if uid in ADMINS:
        kb.append([InlineKeyboardButton("👨‍💻 لوحة تحكم الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

# ====== دوال التسجيل ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = ReplyKeyboardMarkup([["ابدأ ✅"]], resize_keyboard=True)
    await update.message.reply_text("اضغط على 'ابدأ ✅' للمتابعة.", reply_markup=kb)
    return ConversationHandler.END

async def on_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_registered(uid):
        await update.message.reply_text("أنت مسجل بالفعل.", reply_markup=main_keyboard(uid))
        return ConversationHandler.END
    await update.message.reply_text("اكتب اسمك الكامل:", reply_markup=ReplyKeyboardRemove())
    return ASK_NAME

async def on_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text.strip()
    await update.message.reply_text("اكتب رقم هاتفك:")
    return ASK_PHONE

async def on_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data['name']
    phone = update.message.text.strip()
    uid = update.effective_user.id
    username = update.effective_user.username or ''
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sheet.append_row([name, phone, str(uid), username, ts])
    refresh_cache()
    await update.message.reply_text("✅ تم التسجيل.", reply_markup=main_keyboard(uid))
    return ConversationHandler.END

# ====== دوال عرض وتحديث البيانات ======

async def handle_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    await cq.answer()
    uid = cq.from_user.id
    row = USERS_CACHE.get(str(uid))
    if not row:
        await cq.message.reply_text("❌ لم أجد بياناتك.")
        return
    msg = (
        f"📋 بياناتك:\n"
        f"الاسم: {row.get('Name','غير متوفر')}\n"
        f"الهاتف: {row.get('Phone','غير متوفر')}\n"
        f"معرف تيليجرام: {row.get('Telegram ID','')}\n"
        f"اسم المستخدم: @{row.get('Username','')}\n"
        f"تاريخ التسجيل: {row.get('Timestamp','')}"
    )
    await cq.message.reply_text(msg)

async def handle_update_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    await cq.answer()
    await cq.message.reply_text("✏️ اكتب اسمك الجديد:", reply_markup=ReplyKeyboardRemove())
    return UPDATE_NAME

async def on_update_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_name'] = update.message.text.strip()
    await update.message.reply_text("✏️ اكتب رقم الهاتف الجديد:")
    return UPDATE_PHONE

async def on_update_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = context.user_data.get('new_name')
    new_phone = update.message.text.strip()
    uid = update.effective_user.id

    # إيجاد صف الطالب
    try:
        cell = sheet.find(str(uid))
    except Exception as e:
        print("Error finding user row:", e)
        await update.message.reply_text("❌ لم أجد صفّك في الشيت.")
        return ConversationHandler.END

    row_idx = cell.row
    # أعمدة ثابتة: 1=Name, 2=Phone
    name_col = 1
    phone_col = 2

    try:
        sheet.update_cell(row_idx, name_col, new_name)
        sheet.update_cell(row_idx, phone_col, new_phone)
        refresh_cache()
    except Exception as e:
        print("Error updating cells:", e)
        await update.message.reply_text("❌ خطأ عند التحديث، راجعي الطرفي لرؤية التفاصيل.")
        return ConversationHandler.END

    await update.message.reply_text("✅ تم تحديث بياناتك.", reply_markup=main_keyboard(uid))
    return ConversationHandler.END

# ====== دوال جمع الأسئلة ======

async def handle_study_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        cq = update.callback_query
        await cq.answer()
        chat = cq.message
    else:
        chat = update.message

    uid = update.effective_user.id
    student_questions[uid] = []
    prompt = (
        "✍️ أرسل أسئلتك نصًا أو صورًا.\n"
        "عند الانتهاء، أكتب /send_questions أو اضغط الزر."
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("إرسال جميع الأسئلة", callback_data="send_questions")
    ]])
    await chat.reply_text(prompt, reply_markup=kb)
    return ASK_QUESTION

async def collect_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in student_questions:
        return ASK_QUESTION
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if update.message.text:
        student_questions[uid].append(("text", update.message.text.strip(), ts))
    elif update.message.photo:
        student_questions[uid].append(("photo", update.message.photo[-1].file_id, ts))
    await update.message.reply_text("👌 تم حفظ السؤال.")
    return ASK_QUESTION

async def send_questions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        cq = update.callback_query
        await cq.answer()
        send_target = cq.message
        uid = cq.from_user.id
    else:
        send_target = update.message
        uid = update.effective_user.id

    if not is_sub(uid):
        await send_target.reply_text("❌ هذه الخدمة للمشتركين فقط.")
        return ASK_QUESTION

    buf = student_questions.get(uid, [])
    if not buf:
        await send_target.reply_text("❌ لم ترسل أي سؤال.")
        return ASK_QUESTION

    global admin_round_robin
    aid = ADMINS[admin_round_robin % len(ADMINS)]
    admin_round_robin += 1

    for qtype, content, _ in buf:
        ref = generate_ref()
        # إرسال للأدمن
        if qtype == "text":
            await context.bot.send_message(aid, f"❓ سؤال الطالب:\n{content}\n🔢 {ref}")
        else:
            await context.bot.send_photo(aid, content, caption=f"❓ صورة سؤال الطالب\n🔢 {ref}")
        # إرسال للجروب
        if qtype == "text":
            await context.bot.send_message(GROUP_CHAT_ID, f"❓ سؤال الطالب:\n{content}\n🔢 {ref}")
        else:
            await context.bot.send_photo(GROUP_CHAT_ID, content, caption=f"❓ صورة سؤال الطالب\n🔢 {ref}")

    context.user_data['last_student'] = uid
    student_questions[uid] = []
    await send_target.reply_text("✅ أُرسلت أسئلتك إلى الأدمن وللمجروب.")
    return ConversationHandler.END

# ====== دالة رد الأدمن ======

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aid = update.effective_user.id
    reply_to = update.message.reply_to_message
    if aid not in ADMINS or not reply_to:
        return

    original = reply_to.text or reply_to.caption or ""
    m = re.search(r'🔢\s*(Q\d{8}_\d{4})', original)
    if not m:
        await update.message.reply_text("❌ الرقم المرجعي غير موجود.")
        return
    ref = m.group(1)
    question_text = original.split("🔢")[0].strip()
    admin_name = update.effective_user.full_name

    sid = context.user_data.get('last_student')
    if not sid:
        await update.message.reply_text("❌ لا يمكن إيجاد مستلم الرد.")
        return

    caption = f"سؤال الطالب: {question_text}\nرد من الأدمن: {admin_name}\n🔢 {ref}"

    if update.message.text:
        resp = update.message.text.strip()
        await context.bot.send_message(sid, f"{caption}\n\n{resp}")
        await context.bot.send_message(GROUP_CHAT_ID, f"{caption}\n\n{resp}")
    elif update.message.photo:
        fid = update.message.photo[-1].file_id
        await context.bot.send_photo(sid, fid, caption=caption)
        await context.bot.send_photo(GROUP_CHAT_ID, fid, caption=caption)
    elif update.message.voice:
        fid = update.message.voice.file_id
        await context.bot.send_voice(sid, fid, caption=caption)
        await context.bot.send_voice(GROUP_CHAT_ID, fid, caption=caption)

    await update.message.reply_text("✅ تم إرسال الرد.")

# ====== تشغيل البوت ======

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^ابدأ ✅$"), on_start_button),
            CallbackQueryHandler(handle_view, pattern="^view$"),
            CallbackQueryHandler(handle_update_request, pattern="^update$"),
            CallbackQueryHandler(handle_study_question, pattern="^study_question$"),
            CommandHandler("ask", handle_study_question),
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_phone)],
            ASK_QUESTION: [
                MessageHandler(filters.TEXT | filters.PHOTO, collect_question),
                CallbackQueryHandler(send_questions_command, pattern="^send_questions$"),
                CommandHandler("send_questions", send_questions_command),
            ],
            UPDATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_update_name)],
            UPDATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_update_phone)],
        },
        fallbacks=[]
    )

    app.add_handler(conv)
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VOICE) & filters.REPLY,
        handle_admin_reply
    ))

    print("✅ Bot is running")
    app.run_polling()
