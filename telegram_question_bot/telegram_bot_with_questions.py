
# ✅ الكود بعد إضافة خاصية سؤال منهجي وتسجيل الرد في الجروب
import datetime
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from oauth2client.service_account import ServiceAccountCredentials
from telegram.helpers import escape_markdown

ADMINS = [1969054373, 411966667]
GROUP_CHAT_ID = -1002107302191

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Students Data ").sheet1
subscribers_sheet = client.open("Students Data ").worksheet("المشتركين")

ASK_NAME, ASK_PHONE, UPDATE_NAME, UPDATE_PHONE, BROADCAST, PREVIEW_CONFIRM, BROADCAST_RETRY, ASK_QUESTION = range(8)

def is_user_registered(user_id):
    records = sheet.get_all_records()
    for row in records:
        if str(row.get("Telegram ID", "")).strip() == str(user_id):
            return row
    return None

def is_subscribed(user_id):
    records = subscribers_sheet.get_all_records()
    for row in records:
        if str(row.get("Telegram ID", "")).strip() == str(user_id):
            return True
    return False

admin_index = 0
def get_next_admin():
    global admin_index
    admin = ADMINS[admin_index % len(ADMINS)]
    admin_index += 1
    return admin

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["ابدأ ✅"]]
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    await update.message.reply_text("اضغط على 'ابدأ ✅' للمتابعة", reply_markup=markup)

async def handle_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = is_user_registered(user_id)
    buttons = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث البيانات", callback_data="update")]
    ]
    if user_data:
        if is_subscribed(user_id):
            buttons.append([InlineKeyboardButton("❓ استفسار في المنهج", callback_data="ask_question")])
        await update.message.reply_text("أنت مسجل بالفعل، اختر من القائمة:", reply_markup=InlineKeyboardMarkup(buttons))
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
    buttons = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث البيانات", callback_data="update")]
    ]
    if is_subscribed(user_id):
        buttons.append([InlineKeyboardButton("❓ استفسار في المنهج", callback_data="ask_question")])
    await update.message.reply_text("اختر من القائمة:", reply_markup=InlineKeyboardMarkup(buttons))
    return ConversationHandler.END

async def handle_question_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("📩 اكتب استفسارك الآن:")
    return ASK_QUESTION

async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    student_id = update.effective_user.id
    student_name = update.effective_user.full_name
    question = update.message.text
    assigned_admin = get_next_admin()
    context.user_data["question"] = question
    context.user_data["student_id"] = student_id
    context.user_data["student_name"] = student_name

    await context.bot.send_message(chat_id=assigned_admin, text=f"📥 استفسار جديد من {student_name}:

{question}

رد باستخدام الأمر التالي:
/reply {student_id} <نص الرد>")
    await update.message.reply_text("✅ تم إرسال سؤالك للمسؤول، سيتم الرد عليك قريبًا.")
    return ConversationHandler.END

async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _, student_id_str, *response_parts = update.message.text.split()
        student_id = int(student_id_str)
        response_text = " ".join(response_parts)
        await context.bot.send_message(chat_id=student_id, text=f"📬 رد على سؤالك:
{response_text}")
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=f"🧑 الطالب: [{student_id}](tg://user?id={student_id})
📌 سؤاله: {context.user_data.get('question', 'غير متوفر')}
🗣️ الرد: {response_text}", parse_mode="Markdown")
        await update.message.reply_text("✅ تم إرسال الرد وتسجيله في الجروب.")
    except Exception as e:
        await update.message.reply_text("❌ فشل في إرسال الرد. تأكد من الصيغة: /reply [student_id] [نص الرد]")

if __name__ == '__main__':
    app = ApplicationBuilder().token("8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reply", reply_command))
    app.add_handler(CallbackQueryHandler(handle_question_request, pattern="^ask_question$"))
    app.add_handler(MessageHandler(filters.Regex("^ابدأ ✅$"), handle_start_button))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_question_request, pattern="^ask_question$")],
        states={ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question)]},
        fallbacks=[]
    ))
    print("✅ Bot is running...")
    app.run_polling()
