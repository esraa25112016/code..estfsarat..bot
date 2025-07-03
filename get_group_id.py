from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

async def print_chat_id(update, context):
    await update.message.reply_text(f"Group Chat ID: {update.effective_chat.id}")

app = ApplicationBuilder().token("8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY").build()
app.add_handler(MessageHandler(filters.ALL, print_chat_id))
app.run_polling()
