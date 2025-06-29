import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

# إعداد الاتصال بـ Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials/credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Students Data").sheet1

# تعريف حالات المحادثة
ASK_NAME, ASK_PHONE = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("أهلاً بيك! من فضلك اكتب اسمك:")
    return ASK_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text
    await update.message.reply_text("من فضلك اكتب رقم تليفونك:")
    return ASK_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = context.user_data["name"]
    phone = update.message.text
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "بدون اسم مستخدم"
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    records = sheet.get_all_records()
    updated = False

    for i, record in enumerate(records, start=2):  # الصف الثاني عشان الأول عناوين
        if str(record.get("telegram_id")).strip() == str(user_id):
            sheet.update(f"A{i}:E{i}", [[name, phone, str(user_id), username, timestamp]])
            updated = True
            break

    if not updated:
        sheet.append_row([name, phone, str(user_id), username, timestamp])

    await update.message.reply_text("✅ تم تسجيل بياناتك بنجاح.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

# ضع التوكن الخاص بك هنا
app = ApplicationBuilder().token("8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY").build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

app.add_handler(conv_handler)

app.run_polling()
