import logging
import gspread
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, ConversationHandler
)
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import random
import string
import re

# === إعدادات أساسية ===
BOT_TOKEN = "8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY"
ADMINS = [1969054373]  # ضع هنا IDs الأدمن
GROUP_CHAT_ID = -1002606054225

GOOGLE_SHEET_ID = "1yWJDu9I_T30wddt2lkgEO_m6sr1_SDx-WiDUkoZ9UTI"
SUBSCRIBERS_SHEET_NAME = "المشتركين"
QUESTIONS_SHEET_NAME = "استفسارات الطلاب"

# === ربط Google Sheets ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
subscribers_sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SUBSCRIBERS_SHEET_NAME)
questions_sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(QUESTIONS_SHEET_NAME)

# === إعدادات البوت ===
admin_round_robin = 0
pending_questions = {}
handled_questions = set()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# === التحقق من الطالب ===
def is_user_registered(user_id):
    all_records = subscribers_sheet.get_all_records()
    for row in all_records:
        if str(row.get("Telegram ID", "")).strip() == str(user_id):
            return row
    return None

# === إرسال السؤال ===
ASK_QUESTION, ASK_PHOTO = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك في بوت الأسئلة!\nاختر ما تريد:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("استفسار في المنهج", callback_data="ask_question")]])
    )

async def ask_question_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = is_user_registered(user_id)
    if not user:
        await query.message.reply_text("❌ أنت غير مشترك. لا يمكنك استخدام هذه الخدمة.")
        return ConversationHandler.END
    context.user_data.clear()
    await query.message.reply_text("📝 اكتب سؤالك (نصيًا):")
    return ASK_QUESTION

async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["question"] = update.message.text
    await update.message.reply_text("📷 أرسل صورة توضيحية (أو اكتب تخطي إذا لا يوجد):")
    return ASK_PHOTO

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["photo"] = None
    await process_question(update, context)
    return ConversationHandler.END

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file_id = photo.file_id
    context.user_data["photo"] = file_id
    await process_question(update, context)
    return ConversationHandler.END

def generate_ref():
    now = datetime.now().strftime("%Y%m%d")
    suffix = "".join(random.choices(string.digits, k=3))
    return f"Q{now}_{suffix}"

async def process_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    question = context.user_data.get("question")
    photo = context.user_data.get("photo")
    user_data = is_user_registered(user.id)
    ref = generate_ref()
    context.user_data["ref"] = ref

    # توزيع السؤال على ADMINS مباشرة (بدون حضور)
    global admin_round_robin
    if not ADMINS:
        await update.message.reply_text("لا يوجد إدمن متاح حالياً.")
        return

    admin_id = ADMINS[admin_round_robin % len(ADMINS)]
    admin_round_robin += 1

    pending_questions[ref] = {
        "student_id": user.id,
        "student_name": user_data.get("الاسم", user.full_name),
        "student_username": user.username,
        "question": question,
        "photo": photo,
        "assigned_admin": admin_id,
        "ref": ref,
        "asked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "answer": "",
        "answered_at": "",
        "admin_name": ""
        # admin_id سيتم إضافته بعد الرد
    }

    msg = (
        f"سؤال جديد:\n"
        f"👤 <b>اسم الطالب:</b> {user_data.get('الاسم', user.full_name)}\n"
        f"🆔 <b>ID:</b> {user.id}\n"
        f"📄 <b>السؤال:</b> {question}\n"
        f"🔢 <b>الرقم المرجعي:</b> {ref}\n"
    )
    if photo:
        await context.bot.send_photo(admin_id, photo, caption=msg, parse_mode="HTML")
    else:
        await context.bot.send_message(admin_id, msg, parse_mode="HTML")
    await update.message.reply_text(
        "✅ تم استلام سؤالك.\nسوف يتم الرد على استفسارك في أقرب وقت بإذن الله.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 استفسار جديد", callback_data="ask_question")]
        ])
    )

# === استخراج الرقم المرجعي من النص أو الكابتشن لأي رسالة ===
def extract_ref_from_message(message_text):
    match = re.search(r'Q\d{8}_\d{3,}', message_text)
    if match:
        return match.group(0).strip()
    for line in message_text.splitlines():
        if "الرقم المرجعي" in line:
            return line.split(":")[-1].strip()
    return None

# === الرد على السؤال بالـ Reply فقط (text أو caption) ===
async def admin_reply_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        return
    if not update.message.reply_to_message:
        return
    ref = None
    # جرب في نص الرسالة الأصلية
    if update.message.reply_to_message.text:
        ref = extract_ref_from_message(update.message.reply_to_message.text)
    # إذا لم يجد جرب في الكابتشن
    if not ref and update.message.reply_to_message.caption:
        ref = extract_ref_from_message(update.message.reply_to_message.caption)
    if not ref:
        await update.message.reply_text("تعذر معرفة الرقم المرجعي لهذا السؤال.")
        return

    answer = update.message.text
    q = pending_questions.get(ref)
    if not q:
        await update.message.reply_text("❌ الرقم المرجعي غير صحيح أو تم الرد بالفعل.")
        return
    if q["assigned_admin"] != user_id:
        await update.message.reply_text("❌ لا يمكنك الرد على سؤال غير مخصص لك.")
        return
    if ref in handled_questions:
        await update.message.reply_text("تم الرد على هذا السؤال بالفعل.")
        return

    # حفظ اسم وID الأدمن
    q["admin_name"] = update.effective_user.full_name
    q["admin_id"] = user_id

    # إرسال الرد للطالب
    await context.bot.send_message(q["student_id"],
        f"رد الإدمن على سؤالك ({ref}):\n{answer}")
    # نشر في الجروب مع إظهار اسم وID الأدمن
    group_msg = (
        f"❓ <b>سؤال جديد</b>\n"
        f"👤 <b>الطالب:</b> {q['student_name']} (@{q['student_username']})\n"
        f"📝 <b>السؤال:</b> {q['question']}\n"
        f"🔢 <b>الرقم المرجعي:</b> {ref}\n\n"
        f"✅ <b>رد الإدمن:</b> {answer}\n"
        f"👤 <b>اسم الأدمن:</b> {q['admin_name']} | <b>ID:</b> {q['admin_id']}\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    if q["photo"]:
        await context.bot.send_photo(GROUP_CHAT_ID, q["photo"], caption=group_msg, parse_mode="HTML")
    else:
        await context.bot.send_message(GROUP_CHAT_ID, group_msg, parse_mode="HTML")

    q["answer"] = answer
    q["answered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # حفظ الرد مع ID الأدمن في الشيت
    questions_sheet.append_row([
        q["ref"], q["student_name"], q["student_id"], q["student_username"],
        q["question"], q["photo"], answer, q["admin_name"], q["admin_id"], q["asked_at"], q["answered_at"]
    ])
    handled_questions.add(ref)
    del pending_questions[ref]
    await update.message.reply_text("✅ تم إرسال الرد وحفظه.")

# === تشغيل البوت ===
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, admin_reply_direct))
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_question_button, pattern="ask_question")],
        states={
            ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question)],
            ASK_PHOTO: [
                MessageHandler(filters.PHOTO, receive_photo),
                MessageHandler(filters.Regex("^(تخطي|skip)$"), skip_photo)
            ],
        },
        fallbacks=[],
    )
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
