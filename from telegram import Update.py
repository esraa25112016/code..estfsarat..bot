from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from telegram import Update

BOT_TOKEN = "8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY"

async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Chat ID هنا: {chat_id}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.ALL, get_chat_id))

    print("✅ Bot is running...")
    app.run_polling()
