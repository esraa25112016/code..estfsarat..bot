
import gspread
import asyncio
import schedule
import time
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
import logging

logging.basicConfig(level=logging.INFO)

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

    for i, record in enumerate(records, start=2):
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

# إرسال رسالة جماعية أسبوعياً
BOT_TOKEN = "8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY"
bot = Bot(token=BOT_TOKEN)

def send_weekly_reminder():
    try:
        records = sheet.get_all_records()
        for record in records:
            telegram_id = record.get("telegram_id")
            student_name = record.get("name", "طالبنا العزيز")
            if telegram_id:
                message = f"📌 بنفكرك يا {student_name} بعمل الواجب الأسبوعي"
                asyncio.run(bot.send_message(chat_id=int(telegram_id), text=message))
    except Exception as e:
        logging.error(f"❌ خطأ في الإرسال الجماعي: {e}")

# جدولة كل سبت 23:55
schedule.every().sunday.at("00:15").do(send_weekly_reminder)

# بدء تطبيق البوت
app = ApplicationBuilder().token(BOT_TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

app.add_handler(conv_handler)

# تشغيل البوت وجدولة الرسائل
async def main():
    app_task = asyncio.create_task(app.run_polling())
    while True:
        schedule.run_pending()
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
