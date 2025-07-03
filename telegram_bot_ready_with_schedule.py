import os
import datetime
import gspread
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from oauth2client.service_account import ServiceAccountCredentials

# حالات المحادثة
ASK_PHONE, SAVE_DATA = range(2)

# فحص هل المستخدم مسجل مسبقاً
def check_user_exists(sheet, user_id):
    records = sheet.get_all_records()
    for record in records:
        if str(record["Telegram ID"]) == user_id:
            return True
    return False

# أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["ابدأ ✅"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "أهلاً بيك! 👋\nلو حابب تسجل أو تحدّث بياناتك، اضغط الزر:",
        reply_markup=reply_markup
    )
    return ConversationHandler.END

# بدء التسجيل أو التحديث
async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # الاتصال بـ Google Sheets
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("Students Data ").sheet1

    if check_user_exists(sheet, user_id):
        keyboard = [["تحديث البيانات 🔄"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "📌 بياناتك مسجلة بالفعل.\nلو حابب تحدثها، اضغط الزر:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("ما اسمك؟")
        return ASK_PHONE

# عرض البيانات القديمة
async def show_existing_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # الاتصال بـ Google Sheets
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("Students Data ").sheet1

    records = sheet.get_all_records()
    for record in records:
        if str(record["Telegram ID"]) == user_id:
            name = record.get("الاسم", record.get("Name", ""))
            phone = record.get("الرقم", record.get("Phone", ""))
            username = record.get("اسم المستخدم", record.get("Username", ""))
            timestamp = record.get("تاريخ", record.get("Timestamp", ""))

            msg = (
                f"📋 بياناتك الحالية:\n"
                f"الاسم: {name}\n"
                f"الرقم: {phone}\n"
                f"اسم المستخدم: {username}\n"
                f"آخر تحديث: {timestamp}\n\n"
                f"⬇️ من فضلك اكتب اسمك الجديد لتحديث البيانات:"
            )
            await update.message.reply_text(msg)
            return ASK_PHONE

    await update.message.reply_text("❌ لم يتم العثور على بياناتك.")
    return ConversationHandler.END

# استلام الاسم
async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or ""

    context.user_data["name"] = name
    context.user_data["user_id"] = user_id
    context.user_data["username"] = username

    await update.message.reply_text("ما رقمك؟")
    return SAVE_DATA

# استلام الرقم وحفظ البيانات
async def save_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    name = context.user_data.get("name", "")
    user_id = context.user_data.get("user_id", "")
    username = context.user_data.get("username", "")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # الاتصال بـ Google Sheets
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("Students Data ").sheet1

    records = sheet.get_all_records()
    row_number = None

    for i, record in enumerate(records, start=2):
        if str(record["Telegram ID"]) == user_id:
            row_number = i
            break

    if row_number:
        sheet.update(f"A{row_number}:E{row_number}", [[name, phone, user_id, username, timestamp]])
        await update.message.reply_text("✅ تم تحديث بياناتك بنجاح!")
    else:
        sheet.append_row([name, phone, user_id, username, timestamp])
        await update.message.reply_text("✅ تم تسجيل بياناتك بنجاح!")

    return ConversationHandler.END

# إلغاء
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.")
    return ConversationHandler.END

# تشغيل البوت
TOKEN = "8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY"
app = ApplicationBuilder().token(TOKEN).build()

# محادثة التسجيل
conv_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^ابدأ ✅$"), ask_name),
        MessageHandler(filters.Regex("^تحديث البيانات 🔄$"), show_existing_data),
    ],
    states={
        ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
        SAVE_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_data)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

app.add_handler(CommandHandler("start", start))
app.add_handler(conv_handler)

app.run_polling()