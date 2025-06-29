import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
from datetime import datetime

# إعدادات التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# حالات المحادثة
ASK_NAME, ASK_NUMBER = range(2)

# إعداد Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(r"C:\telegram_sheet_bot\credentials\credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Students Data").sheet1

# بدء المحادثة
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا! من فضلك اكتب اسمك:")
    return ASK_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("تمام، اكتب رقمك:")
    return ASK_NUMBER

async def get_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data["name"]
    number = update.message.text
    telegram_id = update.message.from_user.id
    username = update.message.from_user.username or "بدون يوزر"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # قراءة كل البيانات الموجودة
    records = sheet.get_all_records()
    row_index = None

    for idx, record in enumerate(records, start=2):  # نبدأ من الصف الثاني لتجاهل رؤوس الأعمدة
        if str(record.get("telegram_id", "")) == str(telegram_id):
            row_index = idx
            break

    if row_index:
        # تحديث الصف الموجود
        sheet.update(f"A{row_index}:E{row_index}", [[name, number, telegram_id, username, timestamp]])
        await update.message.reply_text("✅ تم تحديث بياناتك بنجاح")
    else:
        # إضافة صف جديد
        sheet.append_row([name, number, telegram_id, username, timestamp])
        await update.message.reply_text("✅ تم تسجيل بياناتك بنجاح")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

# إعداد البوت
app = ApplicationBuilder().token("8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY").build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        ASK_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_number)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

app.add_handler(conv_handler)

if __name__ == "__main__":
    print("✅ Bot is running...")
    app.run_polling()