import logging
import datetime
import asyncio

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from telegram.helpers import escape_markdown

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ====================== CONFIGURATION ======================
BOT_TOKEN = "8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY"
ADMINS = [1969054373, 411966667]
GROUP_CHAT_ID = -1002606054225

SHEET_ID = "1yWJDu9I_T30wddt2lkgEO_m6sr1_SDx-WiDUkoZ9UTI"
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPES)
GCLIENT = gspread.authorize(CREDS)
FILE = GCLIENT.open_by_key(SHEET_ID)
SHEET = FILE.worksheet("Students Data")
SUB_SHEET = FILE.worksheet("المشتركين")
Q_SHEET = FILE.worksheet("استفسارات الطلاب")

# ======================= STATES ============================
STATE_NAME, STATE_PHONE, STATE_STUDY = range(3)
ADMIN_BROADCAST, ADMIN_BROADCAST_CONFIRM = range(10, 12)  # للحالة بتاعت البث

# ======================= KEYBOARDS =========================
MAIN_KB = ReplyKeyboardMarkup([["ابدأ ✅"]], resize_keyboard=True)
RESTART_KB = ReplyKeyboardMarkup([["ابدأ المحادثة من جديد"]], resize_keyboard=True)
STUDY_KB = ReplyKeyboardMarkup(
    [["ارسال استفسارك"], ["ابدأ المحادثة من جديد"]],
    resize_keyboard=True
)

# ======================= GLOBALS ===========================
admin_lock = asyncio.Lock()
admin_index = 0
USERS = {}
SUBSCRIBERS = set()
pending_questions = {}
admin_message_map = {}

# ======================= LOGGING ===========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------------- HELPERS ----------------------------
def refresh_caches():
    global USERS, SUBSCRIBERS
    USERS = {str(r.get("Telegram ID")): r for r in SHEET.get_all_records() if r.get("Telegram ID")}
    SUBSCRIBERS = {str(r.get("Telegram ID")) for r in SUB_SHEET.get_all_records() if r.get("Telegram ID")}

refresh_caches()

def is_registered(uid: int) -> bool:
    return str(uid) in USERS

def is_subscribed(uid: int) -> bool:
    return str(uid) in SUBSCRIBERS

def main_keyboard(uid: int) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث بياناتك", callback_data="update")]
    ]
    if is_subscribed(uid):
        kb.append([InlineKeyboardButton("✍️ استفسارات دراسية", callback_data="ask_study")])
    if uid in ADMINS:
        kb.append([InlineKeyboardButton("👨‍💻 لوحة الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

# -------------------- REGISTRATION ------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اضغط على 'ابدأ ✅' للمتابعة.", reply_markup=MAIN_KB)

async def on_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_registered(uid):
        await update.message.reply_text("أنت مسجل بالفعل.", reply_markup=main_keyboard(uid))
        return ConversationHandler.END
    await update.message.reply_text("اكتب اسمك الكامل:")
    return STATE_NAME

async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text.strip()
    await update.message.reply_text("اكتب رقم هاتفك:")
    return STATE_PHONE

async def reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.pop('name')
    phone = update.message.text.strip()
    uid = update.effective_user.id
    username = update.effective_user.username or ''
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    SHEET.append_row([name, phone, str(uid), username, ts])
    refresh_caches()
    await update.message.reply_text("✅ تم التسجيل.", reply_markup=main_keyboard(uid))
    await update.message.reply_text("لإعادة عرض القائمة، اضغط:", reply_markup=RESTART_KB)
    return ConversationHandler.END

# -------------------- PROFILE ------------------------------
async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not is_registered(uid):
        return await q.edit_message_text("❌ لم نعثر على بياناتك.")
    data = USERS.get(str(uid), {})
    text = (
        f"👤 اسم: {escape_markdown(str(data.get('الاسم','-')), 2)}\n"
        f"📱 هاتف: {escape_markdown(str(data.get('رقم التليفون','-')), 2)}\n"
        f"🔗 @{escape_markdown(str(data.get('Username','-')), 2)}"
    )
    await q.edit_message_text(text, parse_mode='MarkdownV2', reply_markup=main_keyboard(uid))

async def update_profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("✏️ اكتب اسمك الجديد:")
    return STATE_NAME

async def update_profile_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_name'] = update.message.text.strip()
    await update.message.reply_text("📞 اكتب رقمك الجديد:")
    return STATE_PHONE

async def update_profile_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    new_name = context.user_data.get('new_name')
    new_phone = update.message.text.strip()
    username = update.effective_user.username or ''
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cell = SHEET.find(str(uid))
    if cell:
        SHEET.update(f"A{cell.row}:E{cell.row}", [[new_name, new_phone, str(uid), username, ts]])
        refresh_caches()
        await update.message.reply_text("✅ تم التحديث.", reply_markup=main_keyboard(uid))
    else:
        await update.message.reply_text("❌ لم نعثر على بياناتك.")
    return ConversationHandler.END

# -------------------- STUDY FLOW ---------------------------
async def ask_study_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not is_subscribed(uid):
        return await q.answer("❌ هذه الخدمة للمشتركين فقط.", show_alert=True)
    pending_questions[uid] = []
    await q.message.reply_text(
        "✍️ اكتب سؤالك (متعدد رسائل)، ثم اضغط 'ارسال استفسارك'.",
        reply_markup=STUDY_KB
    )
    return STATE_STUDY

async def store_study_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in pending_questions:
        return STATE_STUDY
    if update.message.text:
        pending_questions[uid].append(('text', update.message.text.strip()))
    elif update.message.photo:
        pending_questions[uid].append(('photo', update.message.photo[-1].file_id))
    return STATE_STUDY

async def send_study_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msgs = pending_questions.pop(uid, [])
    if not msgs:
        return await update.message.reply_text("❌ لم تكتب أي شيء.", reply_markup=RESTART_KB)
    texts = [c for t, c in msgs if t == 'text']
    photos = [c for t, c in msgs if t == 'photo']
    question = '\n'.join(texts)
    photo_id = photos[0] if photos else None
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row_idx = len(Q_SHEET.get_all_values()) + 1
    Q_SHEET.append_row([str(uid), update.effective_user.full_name, question, photo_id or '', ts, ''])
    async with admin_lock:
        global admin_index
        aid = ADMINS[admin_index % len(ADMINS)]
        admin_index += 1
    notif = f"📚 استفسار #{row_idx}\n👤 {update.effective_user.full_name}\n\n{question}"
    if photo_id:
        sent = await context.bot.send_photo(aid, photo_id, caption=notif)
    else:
        sent = await context.bot.send_message(aid, notif)
    admin_message_map[sent.message_id] = (uid, row_idx)
    await update.message.reply_text(
        f"✅ تم إرسال سؤالك بنجاح\nرقم الاستفسار: {row_idx}\nيمكنك متابعة الرد قريبًا.",
        reply_markup=RESTART_KB
    )
    return ConversationHandler.END

# -------------------- ADMIN REPLY -------------------------
pending_admin_replies = {}  # aid -> list of (sid,row_idx, type, content)

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    aid = msg.from_user.id
    if aid not in ADMINS or not msg.reply_to_message:
        return
    mapping = admin_message_map.get(msg.reply_to_message.message_id)
    if not mapping:
        return
    sid, row_idx = mapping
    existing_reply = Q_SHEET.cell(row_idx, 6).value
    if existing_reply and existing_reply.strip() != '':
        await msg.reply_text("⚠️ تم الرد على هذا السؤال مسبقًا، لا يمكن الرد مرة أخرى.")
        return
    if msg.text:
        typ, content = 'text', msg.text
    elif msg.photo:
        typ, content = 'photo', msg.photo[-1].file_id
    elif msg.voice:
        typ, content = 'voice', msg.voice.file_id
    else:
        await msg.reply_text("❌ نوع الرد غير مدعوم.")
        return
    pending_admin_replies.setdefault(aid, []).append((sid, row_idx, typ, content))
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 ارسال الردود", callback_data="send_reply")]])
    await msg.reply_text("تم تخزين ردك. اضغط 'ارسال الردود' للإرسال.", reply_markup=kb)

# -------------------- SEND ADMIN REPLY BATCH ----------------
async def send_admin_replies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    aid = query.from_user.id
    replies = pending_admin_replies.pop(aid, [])
    if not replies:
        return await query.edit_message_text("❌ لا توجد ردود لإرسال.")
    sid, row_idx, *_ = replies[0]
    original = Q_SHEET.row_values(row_idx)[2]
    texts, photos, voices = [], [], []
    for _, _, typ, content in replies:
        if typ == "text":
            texts.append(content)
        elif typ == "photo":
            photos.append(content)
        elif typ == "voice":
            voices.append(content)
    reply_summary = ""
    if texts:
        reply_summary += "\n".join(texts)
    if photos:
        reply_summary += f"\n[صور: {len(photos)}]"
    if voices:
        reply_summary += f"\n[مقاطع صوتية: {len(voices)}]"
    Q_SHEET.update_cell(row_idx, 6, reply_summary.strip())
    if texts:
        await context.bot.send_message(sid, "🔔 رد الأدمن:\n" + "\n".join(texts))
    for idx, photo in enumerate(photos):
        cap = "🔔 رد الأدمن (صورة)" if idx == 0 and not texts else None
        await context.bot.send_photo(sid, photo, caption=cap)
    for idx, voice in enumerate(voices):
        cap = "🔔 رد الأدمن (صوت)" if idx == 0 and not texts and not photos else None
        await context.bot.send_voice(sid, voice, caption=cap)
    grp_header = f"❓ استفسار #{row_idx}\n{original}\n\n💬 الرد:"
    if texts:
        await context.bot.send_message(GROUP_CHAT_ID, grp_header + "\n" + "\n".join(texts))
    for idx, photo in enumerate(photos):
        cap = grp_header + "\n(صورة)" if idx == 0 and not texts else None
        await context.bot.send_photo(GROUP_CHAT_ID, photo, caption=cap)
    for idx, voice in enumerate(voices):
        cap = grp_header + "\n(صوت)" if idx == 0 and not texts and not photos else None
        await context.bot.send_voice(GROUP_CHAT_ID, voice, caption=cap)
    await query.edit_message_text("✅ تم إرسال كل الردود مجمعة للطالب والجروب.")

# -------------------- ADMIN PANEL -------------------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id not in ADMINS:
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ ارسال رسالة جماعية", callback_data="broadcast")],
    ])
    await q.edit_message_text("👨‍💻 لوحة الأدمن:", reply_markup=kb)

# --- لوحة الأدمن: رسالة جماعية ---
async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        """اكتب نص الرسالة الجماعية.

ضع كلمة (اسم الطالب) في مكان اسم كل طالب.""",
        reply_markup=None
    )
    return ADMIN_BROADCAST

async def admin_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broadcast_msg'] = update.message.text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 تأكيد الإرسال", callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel")],
    ])
    await update.message.reply_text("هل تريد تأكيد إرسال هذه الرسالة؟", reply_markup=kb)
    return ADMIN_BROADCAST_CONFIRM

async def admin_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    msg_template = context.user_data.get('broadcast_msg', '')
    sheet_records = SHEET.get_all_records()
    count = 0
    for row in sheet_records:
        uid = row.get("Telegram ID")
        name = row.get("الاسم") or row.get("اسم") or row.get("Name") or ""
        if not uid or not name:
            continue
        msg = msg_template.replace("(اسم الطالب)", name)
        try:
            await q.bot.send_message(chat_id=int(uid), text=msg)
            count += 1
        except Exception as e:
            logging.warning(f"Failed to send to {uid}: {e}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ إرسال رسالة جماعية جديدة", callback_data="broadcast")],
        [InlineKeyboardButton("❌ إنهاء", callback_data="admin_panel")],
    ])
    await q.edit_message_text(
        f"✅ تم إرسال الرسالة إلى {count} طالب/ة.\n\nهل ترغب في إرسال رسالة أخرى؟",
        reply_markup=kb
    )
    return ConversationHandler.END

# دالة إعادة تشغيل البث
async def admin_broadcast_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await admin_broadcast_start(update, context)
    return ADMIN_BROADCAST

broadcast_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern="^broadcast$")],
    states={
        ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_input)],
        ADMIN_BROADCAST_CONFIRM: [
            CallbackQueryHandler(admin_broadcast_confirm, pattern="^broadcast_confirm$"),
            CallbackQueryHandler(admin_broadcast_restart, pattern="^broadcast$"),
        ]
    },
    fallbacks=[CallbackQueryHandler(admin_panel, pattern="^admin_panel$")]
)

# --------------------- RESTART ----------------------------
async def restart_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("القائمة الرئيسية:", reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("اختر من القائمة:", reply_markup=main_keyboard(update.effective_user.id))

# ======================= MAIN ==============================
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.Regex("^ابدأ المحادثة من جديد$"), restart_menu))
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler('start', start_cmd), MessageHandler(filters.Regex("^ابدأ ✅$"), on_start_button)],
        states={STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)], STATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone)]},
        fallbacks=[]
    )
    app.add_handler(reg_conv)
    app.add_handler(CallbackQueryHandler(view_profile, pattern="^view$"))
    upd_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(update_profile_start, pattern="^update$")],
        states={STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_profile_name)], STATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_profile_phone)]},
        fallbacks=[]
    )
    app.add_handler(upd_conv)
    study_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_study_start, pattern="^ask_study$")],
        states={STATE_STUDY: [MessageHandler(filters.Regex("^ارسال استفسارك$"), send_study_question), MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, store_study_question)]},
        fallbacks=[]
    )
    app.add_handler(study_conv)
    app.add_handler(MessageHandler(filters.REPLY & filters.User(ADMINS) & (filters.TEXT | filters.PHOTO | filters.VOICE), handle_admin_reply))
    app.add_handler(CallbackQueryHandler(send_admin_replies, pattern="^send_reply$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(broadcast_conv)  # <-- مهم جداً تضيفه هنا عشان البث يشتغل
    logging.info("✅ Bot is running")
    app.run_polling()
