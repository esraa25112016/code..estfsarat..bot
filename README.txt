📘 إرشادات تشغيل مشروع البوت:

1. ضع ملف Google API (credentials.json) في المسار:
   credentials/credentials.json

2. فعّل Google Sheets API، وشارك الشيت مع إيميل الخدمة.

3. غيّر توكن البوت في bot.py عند:
   app = ApplicationBuilder().token("YOUR_TELEGRAM_BOT_TOKEN").build()

4. ثبّت المتطلبات:

   pip install -r requirements.txt

5. شغل البوت:

   python bot.py

✅ عند بدء المحادثة مع البوت على تليجرام، هيطلب الاسم والرقم، ويسجلهم في Google Sheet مع التوقيت وTelegram ID.