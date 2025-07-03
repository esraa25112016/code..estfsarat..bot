import asyncio
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Bot

# ✏️ الرسالة المخصصة
exam_date = "15 يونيو"
custom_message = "بنفكرك باختبار شامل بتاريخ"

# إعداد الاتصال بجوجل شيت
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials/credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Students Data ").sheet1
data = sheet.get_all_records()

# إعداد البوت
BOT_TOKEN = "8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY"
bot = Bot(token=BOT_TOKEN)

# دالة الإرسال الرئيسية
async def send_messages():
    for row in data:
        name = row.get("name") or row.get("الاسم") or "الطالب"
        telegram_id = row.get("Telegram ID") or row.get("telegram id")
        if telegram_id:
            message = f"الطالب العزيز {name}\n{custom_message} {exam_date}"
            try:
                await bot.send_message(chat_id=int(telegram_id), text=message)
                print(f"✅ تم الإرسال إلى: {name}")
            except Exception as e:
                print(f"❌ فشل الإرسال إلى {name}: {e}")

# تشغيل الإرسال
asyncio.run(send_messages())
