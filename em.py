import datetime
import gspread
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from oauth2client.service_account import ServiceAccountCredentials

BOT_TOKEN = "8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY"
ADMINS = [1969054373, 411966667]
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

ASK_NAME, ASK_PHONE, ASK_QUESTION = range(3)
admin_round_robin = 0

USERS_CACHE = {}
SUBSCRIBERS_CACHE = set()

def refresh_cache():
    global USERS_CACHE, SUBSCRIBERS_CACHE
    USERS_CACHE.clear()
    for row in sheet.get_all_records():
        uid = str(row.get("Telegram ID", "")).strip()
        if uid:
            USERS_CACHE[uid] = row
    SUBSCRIBERS_CACHE = set(
        str(r.get("Telegram ID", "")).strip()
        for r in subscribers_sheet.get_all_records()
    )
refresh_cache()

def is_registered(uid): return USERS_CACHE.get(str(uid))
def is_sub(uid): return str(uid) in SUBSCRIBERS_CACHE

def main_keyboard(uid):
    kb = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث بياناتك", callback_data="update")]
    ]
    if is_sub(uid):
        kb.append([InlineKeyboardButton("✍️ استفسار دراسي", callback_data="study_question")])
    if uid in ADMINS:
        kb.append([InlineKeyboardButton("👨‍💻 لوحة تحكم الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

student_questions = {}  # uid -> list of (type, content, time)
admin_replies = {}      # aid -> list of (ref, ans_type, ans_content, admin_name, question_text)

def generate_ref():
    now = datetime.datetime.now().strftime("%Y%m%d")
    suf = f"{datetime.datetime.now().second:02d}{datetime.datetime.now().microsecond%100:02d}"
    return f"Q{now}_{suf}"

# --- تسجيل مستخدم جديد ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = ReplyKeyboardMarkup([["ابدأ ✅"]], resize_keyboard=True)
    await update.message.reply_text("اضغط على 'ابدأ ✅' للمتابعة.", reply_markup=kb)

async def on_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_registered(uid):
        await update.message.reply_text("أنت مسجل بالفعل.", reply_markup=main_keyboard(uid))
        return ConversationHandler.END
    await update.message.reply_text("اكتب اسمك الكامل:")
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
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sheet.append_row([name, phone, str(uid), username, timestamp])
    refresh_cache()
    await update.message.reply_text("✅ تم التسجيل.", reply_markup=main_keyboard(uid))
    return ConversationHandler.END

# --- عرض بيانات المستخدم ---
from telegram.helpers import escape_markdown

async def handle_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = is_registered(uid)
    if not data:
        await query.edit_message_text("❌ لم يتم العثور على بياناتك.")
        return
    text = (
        f"👤 اسمك: {escape_markdown(data.get('الاسم', 'غير متوفر'), version=2)}\n"
        f"📱 رقمك: {escape_markdown(data.get('رقم التليفون', 'غير متوفر'), version=2)}\n"
        f"🔗 يوزرنيم: @{escape_markdown(data.get('Username', 'غير متوفر'), version=2)}"
    )
    await query.edit_message_text(text=text, parse_mode="MarkdownV2", reply_markup=main_keyboard(uid))

# --- تحديث بيانات المستخدم ---
async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✏️ اكتب اسمك الجديد:")
    return ASK_NAME

async def on_update_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_name"] = update.message.text.strip()
    await update.message.reply_text("📞 اكتب رقمك الجديد:")
    return ASK_PHONE

async def on_update_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = context.user_data.get("new_name")
    new_phone = update.message.text.strip()
    uid = update.effective_user.id
    username = update.effective_user.username or ''
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        cell = sheet.find(str(uid))
        if cell:
            sheet.update(f"A{cell.row}:E{cell.row}", [[new_name, new_phone, str(uid), username, timestamp]])
            refresh_cache()
            await update.message.reply_text("✅ تم تحديث بياناتك بنجاح!", reply_markup=main_keyboard(uid))
        else:
            await update.message.reply_text("❌ لم يتم العثور على بياناتك.")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء التحديث: {e}")
    return ConversationHandler.END

# --- إرسال استفسار دراسي ---

async def handle_study_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.effective_user.id
    student_questions[uid] = []
    prompt = (
        "✍️ أرسل أسئلتك واحدة تلو الأخرى (نص أو صورة).\n"
        "عند الانتهاء اضغط على الزر لإرسال جميع الأسئلة."
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("إرسال جميع الأسئلة", callback_data="send_questions")]])
    await update.callback_query.message.reply_text(prompt, reply_markup=kb)
    return ASK_QUESTION

async def collect_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in student_questions:
        return ASK_QUESTION
    t = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if update.message.text:
        student_questions[uid].append(("text", update.message.text.strip(), t))
    elif update.message.photo:
        student_questions[uid].append(("photo", update.message.photo[-1].file_id, t))
    await update.message.reply_text("👌 تم حفظ السؤال. تابع أو اضغط للإرسال.")
    return ASK_QUESTION

async def send_questions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    await cq.answer()
    reply = cq.message.reply_text
    uid = update.effective_user.id
    if not is_sub(uid):
        await reply("❌ هذه الخدمة للمشتركين فقط.")
        return ASK_QUESTION
    buf = student_questions.get(uid, [])
    if not buf:
        await reply("❌ لم ترسل أي سؤال.")
        return ASK_QUESTION
    global admin_round_robin
    aid = ADMINS[admin_round_robin % len(ADMINS)]
    admin_round_robin += 1
    questions_map = {}
    for qtype, cont, t in buf:
        ref = generate_ref()
        questions_sheet.append_row([ref, '', '', '', cont if qtype=='text' else '', cont if qtype=='photo' else '', '', '', '', t, ''])
        txt = f"❓ سؤال الطالب: {cont}\n🔢 {ref}"
        await context.bot.send_message(aid, txt)
        questions_map[ref] = cont
    context.user_data['last_questions'] = questions_map
    context.user_data['last_student'] = uid
    student_questions[uid] = []
    await reply("✅ أُرسلت جميع أسئلتك.")
    return ConversationHandler.END

# --- رد الأدمن على السؤال ---

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aid = update.effective_user.id
    if aid not in ADMINS or not update.message.reply_to_message:
        return

    original_text = update.message.reply_to_message.text or ''
    m = re.search(r'🔢 (Q\d{8}_\d{2})', original_text)
    if not m:
        await update.message.reply_text("❌ الرقم المرجعي غير موجود.")
        return
    ref = m.group(1)

    admin_name = update.effective_user.full_name
    question_text = original_text.replace(f"🔢 {ref}", "").strip()

    # تحديد نوع الرد
    if update.message.text:
        ans_type = "text"
        ans_content = update.message.text.strip()
    elif update.message.photo:
        ans_type = "photo"
        ans_content = update.message.photo[-1].file_id
    elif update.message.voice:
        ans_type = "voice"
        ans_content = update.message.voice.file_id
    else:
        await update.message.reply_text("❌ نوع الرد غير مدعوم.")
        return

    admin_replies.setdefault(aid, []).append((ref, ans_type, ans_content, admin_name, question_text))
    await update.message.reply_text("👌 تم تخزين الرد. استخدم /send_answers لإرساله.")

# --- إرسال كل الردود مرة واحدة للطالب والجروب ---

async def send_answers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aid = update.effective_user.id
    if aid not in ADMINS:
        return
    buf = admin_replies.get(aid, [])
    sid = context.user_data.get('last_student')
    questions_map = context.user_data.get('last_questions', {})
    if not buf or not sid:
        await update.message.reply_text("❌ لا توجد ردود للإرسال.")
        return

    # إرسال الردود للطالب
    for ref, ans_type, ans_content, admin_name, question_text in buf:
        header = f"سؤال الطالب: {question_text}\n"
        footer = f"\nرد من الأدمن: {admin_name}\n🔢 رقم المرجع: {ref}"
        if ans_type == "text":
            await context.bot.send_message(sid, header + ans_content + footer)
        elif ans_type == "photo":
            await context.bot.send_photo(sid, ans_content, caption=header + footer)
        elif ans_type == "voice":
            await context.bot.send_voice(sid, ans_content, caption=header + footer)

    # إرسال الردود للجروب بنفس التنسيق
    for ref, ans_type, ans_content, admin_name, question_text in buf:
        msg = f"سؤال الطالب: {question_text}\n"
        if ans_type == "text":
            msg += f"الاجابة: {ans_content}\n"
        else:
            msg += f"الاجابة: [مرفق {ans_type}]\n"
        msg += f"من الأدمن: {admin_name}\n🔢 رقم المرجع: {ref}"
        if ans_type == "text":
            await context.bot.send_message(GROUP_CHAT_ID, msg)
        elif ans_type == "photo":
            await context.bot.send_photo(GROUP_CHAT_ID, ans_content, caption=msg)
        elif ans_type == "voice":
            await context.bot.send_voice(GROUP_CHAT_ID, ans_content, caption=msg)

    admin_replies[aid] = []
    await update.message.reply_text("✅ تم إرسال الردود مع الأسئلة للطالب والمجموعة.")

# --- لوحة تحكم الأدمن (زر بسيط) ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMINS:
        if update.callback_query:
            await update.callback_query.answer("❌ ليس لديك صلاحية.", show_alert=True)
        return
    keyboard = [
        [InlineKeyboardButton("📝 إرسال رسالة جماعية", callback_data="broadcast")]
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(uid, "لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Conversation Handler setup ---

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            MessageHandler(filters.Regex('^ابدأ ✅$'), on_start_button),
            CallbackQueryHandler(handle_study_question, pattern='^study_question$'),
            CallbackQueryHandler(send_questions_command, pattern='^send_questions$'),
            CallbackQueryHandler(handle_view, pattern='^view$'),
            CallbackQueryHandler(handle_update, pattern='^update$'),
            CallbackQueryHandler(admin_panel, pattern='^admin_panel$'),
        ],
        states={
            ASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_name),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_update_name),
            ],
            ASK_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_update_phone),
            ],
            ASK_QUESTION: [
                MessageHandler(filters.TEXT | filters.PHOTO, collect_question),
                CallbackQueryHandler(send_questions_command, pattern='^send_questions$')
            ]
        },
        fallbacks=[]
    )

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VOICE & filters.REPLY, handle_admin_reply))
    app.add_handler(CommandHandler('send_answers', send_answers_command))

    print('✅ Bot is running')
    app.run_polling()
