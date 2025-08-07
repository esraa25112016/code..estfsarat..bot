import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)
from telegram import Bot
from telegram.error import BadRequest
from telegram.helpers import escape_markdown
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ========== إعدادات ==========
BOT_TOKEN = "8428307246:AAEy5fwNf9aMo_ZQD12IMtagSI-0nGvtE_o"
STATE_FILEID = 1
bot = Bot(token=BOT_TOKEN)

# Google Sheets setup
gc_scopes = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", gc_scopes)
gc = gspread.authorize(creds)

# Replace with your sheet key and worksheet name containing File IDs
SHEET_KEY = "1yWJDu9I_T30wddt2lkgEO_m6sr1_SDx-WiDUkoZ9UTI"
VALIDATION_WS = "اختبار الباب الأول"

# ========== الدوال ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً! استخدم /fileid لاستخراج file_id من صورة، أو /validate_ids للتحقق من صلاحية جميع file_id في الشيت."
    )

async def fileid_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['in_fileid_mode'] = True
    await update.message.reply_text("📸 ابعت صورة لأعطيك الـ file_id الخاص بها.")
    return STATE_FILEID

async def fileid_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo and context.user_data.get('in_fileid_mode'):
        fid = update.message.photo[-1].file_id
        # لا حاجة للهروب هنا لأن نرسل كـ plain text
        await update.message.reply_text(f"✅ file_id:\n{fid}")
        context.user_data['in_fileid_mode'] = False
        return ConversationHandler.END
    await update.message.reply_text("❌ أرسل صورة فقط.")
    return STATE_FILEID

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 تم إلغاء العملية.")
    return ConversationHandler.END

async def validate_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 جاري التحقق من File IDs في الشيت...")
    # جلب الورقة
    try:
        sheet = gc.open_by_key(SHEET_KEY).worksheet(VALIDATION_WS)
    except gspread.exceptions.WorksheetNotFound:
        await msg.edit_text(f"⚠️ الورقة `{VALIDATION_WS}` غير موجودة.")
        return
    # كتابة عنوان العمود C
    sheet.update_cell(1, 3, "Valid?")

    all_values = sheet.get_all_values()
    # تجاهل الصف الأول (العنوان)
    rows = all_values[1:]
    results = []
    for idx, row in enumerate(rows, start=2):
        fid = row[1].strip() if len(row) > 1 else ""
        if not fid:
            status = "❌ فارغ"
        else:
            try:
                bot.get_file(fid)
                status = "✅ صالح"
            except BadRequest:
                status = "❌ غير صالح"
            except Exception:
                status = "❌ خطأ"
        # تحديث الحالة في العمود C
        sheet.update_cell(idx, 3, status)
        results.append(f"صف {idx}: {status}")
    # إرسال ملخص النتائج
    summary = "\n".join(results)
    await msg.edit_text("✅ انتهى التحقق:\n" + summary)
    from telegram import Update
from telegram.ext import ContextTypes

async def group_photo_fileid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # لو الصورة بُعتت في جروب أو قناة
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        await update.message.reply_text(f"file_id (من البوت ده):\n{file_id}", quote=True)
    elif update.message.document and update.message.document.mime_type.startswith("image/"):
        file_id = update.message.document.file_id
        await update.message.reply_text(f"file_id (من البوت ده):\n{file_id}", quote=True)


# ========== الكونفرسيشن ==========
fileid_conv = ConversationHandler(
    entry_points=[CommandHandler("fileid", fileid_start)],
    states={
        STATE_FILEID: [
            MessageHandler(filters.PHOTO & ~filters.COMMAND, fileid_receive),
            MessageHandler(~filters.PHOTO & ~filters.COMMAND, lambda u, c: u.message.reply_text("❌ أرسل صورة فقط."))
        ]
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
    per_chat=True
)

# ========== تشغيل البوت ==========
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(fileid_conv)
    app.add_handler(CommandHandler("validate_ids", validate_ids))
    from telegram.ext import MessageHandler, filters

    app.add_handler(
         MessageHandler(
        (filters.PHOTO | (filters.Document.IMAGE)) & filters.ChatType.GROUPS,
        group_photo_fileid
    )
)

    print("🤖 Bot is running...")
    app.run_polling()
