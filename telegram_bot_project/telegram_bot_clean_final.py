import datetime
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from oauth2client.service_account import ServiceAccountCredentials
from telegram.helpers import escape_markdown
import telegram.error

ADMINS = [1969054373, 411966667]

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Students Data ").sheet1

ASK_NAME, ASK_PHONE, UPDATE_NAME, UPDATE_PHONE, BROADCAST, PREVIEW_CONFIRM, BROADCAST_RETRY = range(7)

def is_user_registered(user_id):
    records = sheet.get_all_records()
    for row in records:
        if str(row.get("Telegram ID", "")).strip() == str(user_id):
            return row
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["ابدأ ✅"]]
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    await update.message.reply_text("اضغط على 'ابدأ ✅' للمتابعة", reply_markup=markup)

async def handle_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = is_user_registered(user_id)
    keyboard = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث البيانات", callback_data="update")]
    ]
    if user_data:
        await update.message.reply_text("أنت مسجل بالفعل، اختر من القائمة:", reply_markup=InlineKeyboardMarkup(keyboard))
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
    keyboard = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث البيانات", callback_data="update")]
    ]
    await update.message.reply_text("اختر من القائمة:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✏️ اكتب اسمك الجديد:")
    return UPDATE_NAME

async def update_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_name"] = update.message.text.strip()
    await update.message.reply_text("📞 اكتب رقمك الجديد:")
    return UPDATE_PHONE

async def update_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = context.user_data.get("new_name")
    new_phone = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username or "بدون يوزر"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cell = sheet.find(str(user_id))
    if cell:
        sheet.update(range_name=f"A{cell.row}:E{cell.row}", values=[[new_name, new_phone, str(user_id), username, timestamp]])
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="menu")]]
        await update.message.reply_text("✅ تم تحديث بياناتك بنجاح!", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("❌ لم يتم العثور على بياناتك.")
    return ConversationHandler.END

async def handle_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = is_user_registered(user_id)
    if data:
        text = (
            f"👤 *اسمك:* {escape_markdown(str(data.get('الاسم', 'غير متوفر')), version=2)}\n"
            f"📱 *رقمك:* {escape_markdown(str(data.get('رقم التليفون', 'غير متوفر')), version=2)}\n"
            f"🔗 *Username:* {escape_markdown('@' + data['Username'], version=2) if data.get('Username') else 'غير متوفر'}"
        )
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="menu")]]
        await query.edit_message_text(text=text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.edit_message_text("❌ لم يتم العثور على بياناتك.")

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث البيانات", callback_data="update")]
    ]
    await query.edit_message_text("اختر من القائمة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("❌ ليس لديك صلاحية الوصول لهذه القائمة.")
        return
    keyboard = [[InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="broadcast")]]
    await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def ask_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("📝 اكتب الرسالة اللي تحب تبعتها لكل الطلاب. استخدم (اسم الطالب) وسيتم استبداله.")
    return BROADCAST

async def preview_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["broadcast_template"] = update.message.text
    records = sheet.get_all_records()
    sample_name = records[0].get("الاسم", "الطالب") if records else "الطالب"
    preview_message = context.user_data["broadcast_template"].replace("(اسم الطالب)", sample_name)
    keyboard = [
        [InlineKeyboardButton("✅ نعم، أرسل", callback_data="confirm_broadcast")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_broadcast")]
    ]
    await update.message.reply_text(f"📤 *معاينة الرسالة:*\n\n{preview_message}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return PREVIEW_CONFIRM

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    template = context.user_data.get("broadcast_template", "")
    records = sheet.get_all_records()
    count = 0
    for row in records:
        student_id = row.get("Telegram ID")
        student_name = row.get("الاسم", "الطالب")
        if student_id:
            try:
                message = template.replace("(اسم الطالب)", student_name)
                await context.bot.send_message(chat_id=int(student_id), text=message)
                count += 1
            except Exception as e:
                print(f"❌ Failed for {student_name}: {e}")
    await query.edit_message_text(f"✅ تم إرسال الرسالة إلى {count} طالب.")
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📝 نعم، أريد إرسال رسالة أخرى", callback_data="broadcast")],
        [InlineKeyboardButton("❌ لا، شكراً", callback_data="cancel_final")]
    ]
    await query.edit_message_text("❓ هل تود إرسال رسالة جماعية أخرى؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return BROADCAST_RETRY

async def cancel_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ تم الإلغاء. شكرًا لك!")
    return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token("8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY").build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^ابدأ ✅$"), handle_start_button),
                      CallbackQueryHandler(handle_update, pattern="^update$")],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            UPDATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_name)],
            UPDATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_phone)],
        },
        fallbacks=[]
    )

    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_broadcast_message, pattern="^broadcast$")],
        states={
            BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, preview_broadcast)],
            PREVIEW_CONFIRM: [CallbackQueryHandler(execute_broadcast, pattern="^confirm_broadcast")],
            BROADCAST_RETRY: [CallbackQueryHandler(ask_broadcast_message, pattern="^broadcast"),
                              CallbackQueryHandler(cancel_final, pattern="^cancel_final")]
        },
        fallbacks=[CallbackQueryHandler(cancel_broadcast, pattern="^cancel_broadcast")]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(handle_view, pattern="^view$"))
    app.add_handler(CallbackQueryHandler(show_menu, pattern="^menu$"))
    app.add_handler(conv_handler)
    app.add_handler(broadcast_conv)

    print("✅ Bot is running...")
    app.run_polling()
