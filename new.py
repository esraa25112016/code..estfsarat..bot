import datetime
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from oauth2client.service_account import ServiceAccountCredentials
from telegram.helpers import escape_markdown

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

ASK_NAME, ASK_PHONE, UPDATE_NAME, UPDATE_PHONE, ASK_QUESTION = range(5)

admin_round_robin = 0
USERS_CACHE = {}
SUBSCRIBERS_CACHE = set()

def refresh_cache():
    global USERS_CACHE, SUBSCRIBERS_CACHE
    USERS_CACHE.clear()
    for row in sheet.get_all_records():
        user_id = str(row.get("Telegram ID", "")).strip()
        if user_id:
            USERS_CACHE[user_id] = row
    SUBSCRIBERS_CACHE = set(
        str(row.get("Telegram ID", "")).strip()
        for row in subscribers_sheet.get_all_records()
    )
refresh_cache()

def is_user_registered(user_id): return USERS_CACHE.get(str(user_id))
def is_subscribed(user_id): return str(user_id) in SUBSCRIBERS_CACHE

def main_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث البيانات", callback_data="update")]
    ]
    if is_subscribed(user_id):
        keyboard.append([InlineKeyboardButton("✍️ استفسار دراسي", callback_data="study_question")])
    if user_id in ADMINS:
        keyboard.append([InlineKeyboardButton("👨‍💻 لوحة تحكم الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

# ========== نظام الأسئلة ==========

student_questions_buffer = {}

def generate_ref():
    now = datetime.datetime.now().strftime("%Y%m%d")
    suffix = "".join(str(i) for i in [datetime.datetime.now().second, datetime.datetime.now().microsecond][::-1])[-3:]
    return f"Q{now}_{suffix}"

async def handle_study_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    student_questions_buffer[user_id] = []
    await update.callback_query.message.reply_text(
        "✍️ اكتب كل أسئلتك (نص أو صورة)، وعندما تنتهي اضغط على الزر بالأسفل لإرسال جميع الأسئلة.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 إرسال جميع الأسئلة", callback_data="send_all_questions")]])
    )
    return ASK_QUESTION

async def collect_student_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in student_questions_buffer:
        student_questions_buffer[user_id] = []
    if update.message.text:
        student_questions_buffer[user_id].append({
            "type": "text", "content": update.message.text.strip(), "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        })
    elif update.message.photo:
        student_questions_buffer[user_id].append({
            "type": "photo", "content": update.message.photo[-1].file_id, "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        })
    return ASK_QUESTION

async def send_all_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # تصحيح طريقة الرد بناء على نوع الرسالة
    msg_func = update.callback_query.message.reply_text if hasattr(update, "callback_query") and update.callback_query else update.message.reply_text

    if not is_subscribed(user_id):
        await msg_func("❌ الخدمة متاحة فقط للمشتركين.")
        return ConversationHandler.END
    global admin_round_robin
    admin_id = ADMINS[admin_round_robin % len(ADMINS)]
    admin_round_robin += 1

    to_send = student_questions_buffer.get(user_id, [])
    if not to_send:
        await msg_func("لم تقم بإدخال أي سؤال!")
        return ConversationHandler.END

    for q in to_send:
        ref = generate_ref()
        asked_at = q["time"]
        row = [ref, "", "", "", q['content'], q['content'] if q["type"]=="photo" else "", "", "", "", asked_at, ""]
        questions_sheet.append_row(row)
        row_number = len(questions_sheet.get_all_values())
        # إرسال للإدمن (بدون بيانات الطالب)
        if q["type"] == "text":
            msg = f"📝 <b>سؤال جديد</b>\n📄 <b>السؤال:</b> {q['content']}\n🔢 <b>الرقم المرجعي:</b> {ref}"
            await context.bot.send_message(admin_id, msg, parse_mode="HTML")
        elif q["type"] == "photo":
            msg = f"📝 <b>سؤال جديد</b>\n🔢 <b>الرقم المرجعي:</b> {ref}"
            await context.bot.send_photo(admin_id, q["content"], caption=msg, parse_mode="HTML")
        # الرد للطالب مع رقم الصف
        await msg_func(f"✅ تم إرسال سؤالك. رقم السؤال: {row_number}")

    student_questions_buffer[user_id] = []
    await msg_func(f"تم إرسال جميع أسئلتك.")
    return ConversationHandler.END

# ========== تسجيل وتحديث البيانات ==========

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
    refresh_cache()
    await update.message.reply_text("✅ تم تسجيلك بنجاح!")
    await update.message.reply_text("اختر من القائمة:", reply_markup=main_keyboard(user_id))
    return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^ابدأ ✅$"), handle_start_button),
            CallbackQueryHandler(handle_study_question, pattern="^study_question$"),
            CallbackQueryHandler(send_all_questions, pattern="^send_all_questions$")
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            ASK_QUESTION: [MessageHandler(filters.TEXT | filters.PHOTO, collect_student_question)],
        },
        fallbacks=[]
    )
    app.add_handler(conv_handler)
    print("✅ Bot is running...")
    app.run_polling()
