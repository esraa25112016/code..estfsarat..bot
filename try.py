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
import gspread.exceptions

# ====================== CONFIGURATION ======================
BOT_TOKEN = "8032423352:AAFn2CRF-lrshrnYmFf_TJ7onWER2rD_tDY"
ADMINS = [1969054373, 411966667]

# جروب متابعة ردود الأدمن (للردود، ولتسجيل الحضور والانصراف)
ADMIN_LOG_CHAT_ID = -1002606054225
# جروب المشتركين (لنشر السؤال+الرد بدون بيانات الطالب)
SUBSCRIBERS_CHAT_ID = -1002624944424

SHEET_ID = "1yWJDu9I_T30wddt2lkgEO_m6sr1_SDx-WiDUkoZ9UTI"
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPES)
GCLIENT = gspread.authorize(CREDS)
FILE = GCLIENT.open_by_key(SHEET_ID)

# أوراق البيانات
SHEET       = FILE.worksheet("Students Data")
SUB_SHEET   = FILE.worksheet("المشتركين")
Q_SHEET     = FILE.worksheet("استفسارات الطلاب")
# ورقة الحضور
try:
    ATT_SHEET = FILE.worksheet("Attendance")
except gspread.exceptions.WorksheetNotFound:
    ATT_SHEET = FILE.add_worksheet("Attendance", rows=1000, cols=5)

# ======================= STATES ============================
STATE_NAME, STATE_PHONE = range(2)
STATE_GATE, STATE_CHOOSE = range(2, 4)
STATE_ONLY_PHOTO, STATE_ONLY_TEXT, STATE_PHOTO_THEN_TEXT = range(4, 7)
# حالات البث الجماعي
STATE_BCAST_TEXT, STATE_BCAST_CONFIRM, STATE_BCAST_OPTION = range(20, 23)
ADMIN_BROADCAST, ADMIN_BROADCAST_CONFIRM = STATE_BCAST_TEXT, STATE_BCAST_CONFIRM

# ======================= KEYBOARDS =========================
MAIN_KB = ReplyKeyboardMarkup([["ابدأ ✅"]], resize_keyboard=True)
RESTART_KB = ReplyKeyboardMarkup([["ابدأ المحادثة من جديد"]], resize_keyboard=True)

GATES_LIST = ["الباب الأول", "الباب الثاني", "الباب الثالث", "الباب الرابع", "الباب الخامس"]
GATES_KB = ReplyKeyboardMarkup([[g] for g in GATES_LIST] + [["ابدأ المحادثة من جديد"]], resize_keyboard=True)

ASK_TYPE_KB = ReplyKeyboardMarkup(
    [["صورة فقط"], ["نص فقط"], ["صورة مع نص"], ["ابدأ المحادثة من جديد"]],
    resize_keyboard=True
)

# ======================= GLOBALS ===========================
admin_lock = asyncio.Lock()
admin_status = {aid: {'checked_in': False, 'checkin_ts': None} for aid in ADMINS}
admin_index = 0

USERS = {}
SUBSCRIBERS = {}
pending_questions = {}
admin_message_map = {}
pending_admin_replies = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def refresh_caches():
    global USERS, SUBSCRIBERS
    USERS = {str(r["Telegram ID"]): r for r in SHEET.get_all_records() if r.get("Telegram ID")}
    SUBSCRIBERS = {str(r["Telegram ID"]): r for r in SUB_SHEET.get_all_records() if r.get("Telegram ID")}

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
    data = USERS[str(uid)]
    text = (
        f"👤 اسم: {escape_markdown(str(data.get('الاسم','-')),2)}\n"
        f"📱 هاتف: {escape_markdown(str(data.get('رقم التليفون','-')),2)}\n"
        f"🔗 @{escape_markdown(str(data.get('Username','-')),2)}"
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
    new_name = context.user_data['new_name']
    new_phone = update.message.text.strip()
    username = update.effective_user.username or ''
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cell = SHEET.find(str(uid))
    if cell:
        SHEET.update(f"A{cell.row}:E{cell.row}", [[new_name,new_phone,str(uid),username,ts]])
        refresh_caches()
        await update.message.reply_text("✅ تم التحديث.", reply_markup=main_keyboard(uid))
    else:
        await update.message.reply_text("❌ لم نعثر على بياناتك.")
    return ConversationHandler.END

# -------------------- ATTENDANCE ---------------------------
async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if uid not in ADMINS:
        return
    status = admin_status[uid]
    if status['checked_in']:
        await q.message.reply_text("⚠️ أنت مسجل دخول بالفعل.")
        return
    ts = datetime.datetime.now()
    ts_str = ts.strftime('%Y-%m-%d %H:%M:%S')
    status['checked_in'] = True
    status['checkin_ts'] = ts
    ATT_SHEET.append_row([str(uid), q.from_user.full_name, 'checkin', ts_str, ''])
    await q.message.reply_text("✅ تم تسجيل الحضور.")
    await context.bot.send_message(ADMIN_LOG_CHAT_ID, f"✅ {q.from_user.full_name} سجل حضور الساعة {ts_str}")

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if uid not in ADMINS:
        return
    status = admin_status[uid]
    if not status['checked_in']:
        await q.message.reply_text("⚠️ لم تسجل حضور بعد.")
        return
    ts_out = datetime.datetime.now()
    ts_out_str = ts_out.strftime('%Y-%m-%d %H:%M:%S')
    ts_in = status['checkin_ts']
    elapsed = str(ts_out - ts_in).split('.')[0]
    status['checked_in'] = False
    ATT_SHEET.append_row([str(uid), q.from_user.full_name, 'checkout', ts_out_str, elapsed])
    await q.message.reply_text("✅ تم تسجيل الانصراف.")
    await context.bot.send_message(
        ADMIN_LOG_CHAT_ID,
        f"⏹️ {q.from_user.full_name} سجل انصراف الساعة {ts_out_str}\n⏳ المدة: {elapsed}"
    )

# -------------------- STUDY ASK FLOW -----------------------
async def ask_study_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    # منع سؤال جديد قبل الرد السابق
    for rec in Q_SHEET.get_all_records()[::-1]:
        if rec.get("Telegram ID")==str(uid) and not (rec.get("الرد") or "").strip():
            await q.message.reply_text("⚠️ لا يمكنك إرسال سؤال جديد حتى يتم الرد على سؤالك السابق.", reply_markup=RESTART_KB)
            return ConversationHandler.END
    # التأكد من ساعات عمل الأدمن
    active = [aid for aid,s in admin_status.items() if s['checked_in']]
    if not active:
        await q.message.reply_text("⚠️ الخدمة غير متاحة خارج ساعات عمل الأدمن.", reply_markup=RESTART_KB)
        return ConversationHandler.END
    if not is_subscribed(uid):
        return await q.answer("❌ هذه الخدمة للمشتركين فقط.", show_alert=True)
    await q.message.reply_text("اختر الباب المشترك فيه:", reply_markup=GATES_KB)
    return STATE_GATE

async def gate_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text not in GATES_LIST:
        await update.message.reply_text("يرجى اختيار الباب من الأزرار فقط.", reply_markup=GATES_KB)
        return STATE_GATE
    student = SUBSCRIBERS.get(str(update.effective_user.id),{})
    if student.get(text,"").strip()!="تم":
        await update.message.reply_text(f"عذراً، غير مشترك في {text}.", reply_markup=GATES_KB)
        return STATE_GATE
    context.user_data["current_gate"] = text
    await update.message.reply_text(f"اتفضل ابعت استفسارك في {text}.", reply_markup=ASK_TYPE_KB)
    return STATE_CHOOSE

async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    pending_questions[update.effective_user.id] = []
    if t == "صورة فقط":
        await update.message.reply_text("اتفضل ابعت صورة السؤال.", reply_markup=RESTART_KB)
        return STATE_ONLY_PHOTO
    if t == "نص فقط":
        await update.message.reply_text("اتفضل اكتب سؤالك.", reply_markup=RESTART_KB)
        return STATE_ONLY_TEXT
    if t == "صورة مع نص":
        await update.message.reply_text("اتفضل ابعت صورة السؤال أولاً.", reply_markup=RESTART_KB)
        return STATE_PHOTO_THEN_TEXT
    await update.message.reply_text("اختر من الأزرار.", reply_markup=ASK_TYPE_KB)
    return STATE_CHOOSE

async def only_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        pending_questions[update.effective_user.id] = [('photo', update.message.photo[-1].file_id)]
        return await send_study_question(update, context)
    await update.message.reply_text("يجب إرسال صورة فقط.")
    return STATE_ONLY_PHOTO

async def only_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text:
        pending_questions[update.effective_user.id] = [('text', update.message.text.strip())]
        return await send_study_question(update, context)
    await update.message.reply_text("يجب كتابة نص فقط.")
    return STATE_ONLY_TEXT

async def photo_then_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if 'waiting_text' not in context.user_data:
        if update.message.photo:
            context.user_data['photo_id'] = update.message.photo[-1].file_id
            context.user_data['waiting_text'] = True
            await update.message.reply_text("اتفضل اكتب نص بخصوص الصورة.")
            return STATE_PHOTO_THEN_TEXT
        await update.message.reply_text("يجب إرسال صورة أولاً.")
        return STATE_PHOTO_THEN_TEXT
    if update.message.text:
        pending_questions[uid] = [
            ('photo', context.user_data.pop('photo_id')),
            ('text', update.message.text.strip())
        ]
        context.user_data.pop('waiting_text', None)
        return await send_study_question(update, context)
    await update.message.reply_text("يجب كتابة نص بعد الصورة.")
    return STATE_PHOTO_THEN_TEXT

async def send_study_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msgs = pending_questions.pop(uid, [])
    gate = context.user_data.get("current_gate", "غير محدد")
    texts = [c for t,c in msgs if t=='text']
    photos = [c for t,c in msgs if t=='photo']
    question = '\n'.join(texts)
    photo_id = photos[0] if photos else ''
    ask_ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row_idx = len(Q_SHEET.get_all_values()) + 1
    Q_SHEET.append_row([
        str(uid),
        update.effective_user.full_name,
        question,
        photo_id,
        ask_ts,
        "",     # الرد
        gate,
        "",     # وقت الرد
        "",     # مسؤول
        ""      # المدة
    ])

    active = [aid for aid,s in admin_status.items() if s['checked_in']]
    if not active:
        await update.message.reply_text("⚠️ الخدمة غير متاحة الآن.", reply_markup=RESTART_KB)
        return ConversationHandler.END

    async with admin_lock:
        global admin_index
        aid = active[admin_index % len(active)]
        admin_index += 1

    caption = f"📚 استفسار #{row_idx}\n👤 {update.effective_user.full_name}\n📖 {gate}\n\n{question}"
    if photo_id:
        sent = await context.bot.send_photo(aid, photo_id, caption=caption)
    else:
        sent = await context.bot.send_message(aid, caption)

    admin_message_map[sent.message_id] = (uid, row_idx)
    await update.message.reply_text(f"✅ تم الإرسال #{row_idx}. انتظر الرد.", reply_markup=RESTART_KB)
    return ConversationHandler.END

# -------------------- ADMIN REPLY & SEND ----------------
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    aid = msg.from_user.id
    if aid not in ADMINS or not msg.reply_to_message:
        return
    mapping = admin_message_map.get(msg.reply_to_message.message_id)
    if not mapping:
        return
    sid, row_idx = mapping
    existing_reply = (Q_SHEET.cell(row_idx, 6).value or "").strip()
    if existing_reply:
        await msg.reply_text("⚠️ تم الرد على هذا السؤال مسبقًا، لا يمكنك الرد مرة أخرى.")
        return
    # خزّن الرد مؤقتًا
    if msg.text:
        typ, content = 'text', msg.text
    elif msg.photo:
        typ, content = 'photo', msg.photo[-1].file_id
    elif msg.voice:
        typ, content = 'voice', msg.voice.file_id
    else:
        await msg.reply_text("❌ نوع الرد غير مدعوم.")
        return
    stored = pending_admin_replies.setdefault(aid, [])
    stored.append((sid, row_idx, typ, content))
    if len(stored) == 1:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 إرسال الردود", callback_data="send_reply")]])
        await msg.reply_text("✅ تم تخزين ردّك.\nاضغط **إرسال الردود** عندما تنتهي.", reply_markup=kb, parse_mode='Markdown')
    else:
        await msg.reply_text("✅ تم تخزين ردّك الإضافي.")

async def send_admin_replies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    aid = query.from_user.id
    reps = pending_admin_replies.pop(aid, [])
    if not reps:
        return await query.edit_message_text("❌ لا توجد ردود لإرسال.")
    sid, row_idx, *_ = reps[0]
    ask_ts_str = Q_SHEET.cell(row_idx,5).value
    ask_dt = datetime.datetime.strptime(ask_ts_str, '%Y-%m-%d %H:%M:%S')
    texts, photos, voices = [], [], []
    for _, _, typ, cont in reps:
        if typ=='text': texts.append(cont)
        elif typ=='photo': photos.append(cont)
        else: voices.append(cont)
    # اسم الأدمن
    bot_user = await context.bot.get_me()
    admin_name = bot_user.username
    reply_ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rep_dt = datetime.datetime.strptime(reply_ts, '%Y-%m-%d %H:%M:%S')
    elapsed = str(rep_dt - ask_dt).split('.')[0]
    summary = "\n".join(texts)
    if photos: summary += f"\n[صور: {len(photos)}]"
    if voices: summary += f"\n[صوتيات: {len(voices)}]"
    # تحديث الشيت
    Q_SHEET.update_cell(row_idx,6,summary)
    Q_SHEET.update_cell(row_idx,8,reply_ts)
    Q_SHEET.update_cell(row_idx,9,admin_name)
    Q_SHEET.update_cell(row_idx,10,elapsed)
    # إرسال للطالب
    if texts: await context.bot.send_message(sid, "🔔 رد الأدمن:\n"+summary)
    for p in photos: await context.bot.send_photo(sid,p)
    for v in voices: await context.bot.send_voice(sid,v)
    # جروب متابعة الأدمن
    header = (
        f"❓ استفسار #{row_idx}\n"
        f"{Q_SHEET.row_values(row_idx)[2]}\n"
        f"📖 {Q_SHEET.cell(row_idx,7).value}\n"
        f"⏱️ من {ask_ts_str} إلى {reply_ts}\n"
        f"⏳ المدة: {elapsed}\n"
        f"💬 الرد:\n{summary}"
    )
    await context.bot.send_message(ADMIN_LOG_CHAT_ID, header)
    for p in photos: await context.bot.send_photo(ADMIN_LOG_CHAT_ID,p)
    for v in voices: await context.bot.send_voice(ADMIN_LOG_CHAT_ID,v)
    # جروب المشتركين
    simple = (
        f"❓ استفسار #{row_idx}\n"
        f"{Q_SHEET.row_values(row_idx)[2]}\n\n"
        f"💬 الرد:\n{summary}"
    )
    await context.bot.send_message(SUBSCRIBERS_CHAT_ID, simple)
    await query.edit_message_text("✅ تم إرسال جميع الردود دفعة واحدة.")

# -------------------- ADMIN PANEL & BROADCAST --------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ بث جماعي", callback_data="broadcast")],
        [InlineKeyboardButton("🕒 تسجيل حضور", callback_data="do_checkin")],
        [InlineKeyboardButton("🏁 تسجيل انصراف", callback_data="do_checkout")]
    ])
    await q.edit_message_text("👨‍💻 لوحة الأدمن:", reply_markup=kb)

# دوال مساعدة للحضور
async def do_checkin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await checkin(update, context)
async def do_checkout_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await checkout(update, context)

# ---- سيناريو البث الجماعي ----
async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "اتفضل اكتب نص الرسالة الجماعية (استخدم `(اسم الطالب)` ليتم الاستبدال تلقائيًا):",
        reply_markup=None
    )
    return STATE_BCAST_TEXT

async def admin_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broadcast_msg'] = update.message.text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("نعم ارسل", callback_data="broadcast_send")],
        [InlineKeyboardButton("لا الغاء", callback_data="broadcast_cancel")]
    ])
    await update.message.reply_text("هل تريد تأكيد الإرسال؟", reply_markup=kb)
    return STATE_BCAST_CONFIRM

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    template = context.user_data.get('broadcast_msg', '')
    cnt = 0
    for r in SUB_SHEET.get_all_records():
        uid = r.get("Telegram ID")
        name = r.get("الاسم") or r.get("Name","")
        if uid and name:
            try:
                await q.bot.send_message(int(uid), template.replace("(اسم الطالب)", name))
                cnt += 1
            except:
                pass
    await q.edit_message_text(f"✅ تم الإرسال إلى {cnt} طالب/ة.", reply_markup=None)
    # عودة للقائمة الرئيسية
    await q.message.reply_text("القائمة الرئيسية:", reply_markup=ReplyKeyboardRemove())
    await q.message.reply_text("اختر من القائمة:", reply_markup=main_keyboard(q.from_user.id))
    return ConversationHandler.END

async def admin_broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("اريد ارسال رسالة اخرى", callback_data="broadcast_retry")],
        [InlineKeyboardButton("الغاء", callback_data="broadcast_abort")]
    ])
    await q.edit_message_text("هل تريد إرسال رسالة أخرى أم إلغاء العملية؟", reply_markup=kb)
    return STATE_BCAST_OPTION

async def admin_broadcast_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "اتفضل اكتب نص الرسالة الجماعية (استخدم `(اسم الطالب)`):",
        reply_markup=None
    )
    return STATE_BCAST_TEXT

async def admin_broadcast_abort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("تم الإلغاء. شكراً.", reply_markup=None)
    # عودة للقائمة الرئيسية
    await q.message.reply_text("القائمة الرئيسية:", reply_markup=ReplyKeyboardRemove())
    await q.message.reply_text("اختر من القائمة:", reply_markup=main_keyboard(q.from_user.id))
    return ConversationHandler.END

broadcast_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern="^broadcast$")],
    states={
        STATE_BCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_input)],
        STATE_BCAST_CONFIRM: [
            CallbackQueryHandler(admin_broadcast_send, pattern="^broadcast_send$"),
            CallbackQueryHandler(admin_broadcast_cancel, pattern="^broadcast_cancel$")
        ],
        STATE_BCAST_OPTION: [
            CallbackQueryHandler(admin_broadcast_retry, pattern="^broadcast_retry$"),
            CallbackQueryHandler(admin_broadcast_abort, pattern="^broadcast_abort$")
        ],
    },
    fallbacks=[CallbackQueryHandler(admin_panel, pattern="^admin_panel$")],
    per_message=False
)

# -------------------- RESTART MENU ------------------------
async def restart_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("القائمة الرئيسية:", reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("اختر:", reply_markup=main_keyboard(update.effective_user.id))

# ======================= MAIN ==============================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # تسجيل
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_cmd), MessageHandler(filters.Regex("^ابدأ ✅$"), on_start_button)],
        states={
            STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            STATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone)]
        },
        fallbacks=[]
    )
    app.add_handler(reg_conv)
    app.add_handler(MessageHandler(filters.Regex("^ابدأ المحادثة من جديد$"), restart_menu))

    # عرض / تحديث بيانات
    app.add_handler(CallbackQueryHandler(view_profile, pattern="^view$"))
    upd_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(update_profile_start, pattern="^update$")],
        states={
            STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_profile_name)],
            STATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_profile_phone)]
        },
        fallbacks=[]
    )
    app.add_handler(upd_conv)

    # استفسارات دراسية
    study_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_study_start, pattern="^ask_study$")],
        states={
            STATE_GATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, gate_choose)],
            STATE_CHOOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_type)],
            STATE_ONLY_PHOTO: [MessageHandler(filters.PHOTO & ~filters.COMMAND, only_photo)],
            STATE_ONLY_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, only_text)],
            STATE_PHOTO_THEN_TEXT: [
                MessageHandler(filters.PHOTO & ~filters.COMMAND, photo_then_text),
                MessageHandler(filters.TEXT & ~filters.COMMAND, photo_then_text)
            ]
        },
        fallbacks=[]
    )
    app.add_handler(study_conv)

    # رد الأدمن وتجميع
    app.add_handler(MessageHandler(
        filters.REPLY & filters.User(ADMINS) & (filters.TEXT | filters.PHOTO | filters.VOICE),
        handle_admin_reply
    ))
    app.add_handler(CallbackQueryHandler(send_admin_replies, pattern="^send_reply$"))

    # لوحة الأدمن + بث + حضور/انصراف
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(do_checkin_cb, pattern="^do_checkin$"))
    app.add_handler(CallbackQueryHandler(do_checkout_cb, pattern="^do_checkout$"))
    app.add_handler(broadcast_conv)

    logging.info("✅ Bot is running")
    app.run_polling()
