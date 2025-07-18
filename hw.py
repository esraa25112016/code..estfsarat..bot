import telebot

BOT_TOKEN = '8128843988:AAGetiGPTGuoxS0kI4Muit-o_Jqa6l-Hb8E'
bot = telebot.TeleBot(BOT_TOKEN)

# لما الطالب يضغط على الزر "📤 تسليم الواجب"
@bot.message_handler(func=lambda message: message.text == "📤 تسليم الواجب")
def ask_for_homework(message):
    bot.send_message(message.chat.id, "من فضلك ابعت ملف الواجب بصيغة PDF.")

# استقبال ملفات PDF فقط
@bot.message_handler(content_types=['document'])
def handle_pdf(message):
    if message.document.mime_type == 'application/pdf':
        bot.send_message(message.chat.id, "✔️ تم استلام الملف.")
        print(f"📄 تم استلام واجب من {message.from_user.first_name} - ID: {message.from_user.id}")
    else:
        bot.send_message(message.chat.id, "⚠️ الملف يجب أن يكون PDF فقط.")

# تشغيل البوت بدون تعارض
bot.infinity_polling(skip_pending=True, timeout=60, non_stop=True, non_threaded=True)

