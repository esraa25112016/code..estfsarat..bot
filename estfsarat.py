import logging
import datetime
import asyncio

from telegram import ReplyKeyboardMarkup, KeyboardButton

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
ADMINS = [1969054373, 411966667, 792154250]

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
(
    STATE_NAME, STATE_PHONE,
    STATE_GATE, STATE_CHOOSE,
    STATE_ONLY_PHOTO, STATE_ONLY_TEXT, STATE_PHOTO_THEN_TEXT
) = range(7)
ADMIN_BROADCAST, ADMIN_BROADCAST_CONFIRM = range(10, 12)

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
    if is_subscribed(uid):
        kb.append([InlineKeyboardButton("🔗 الذهاب إلى بوت تسليم الواجب", url="https://t.me/Homeworkpdf_bot")])

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

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # استدعاء من CallbackQueryHandler
    q = update.callback_query
    await q.answer()
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
    # تأكيد للمستخدم
    await q.message.reply_text("✅ تم تسجيل الحضور.")
    # سجل في جروب المتابعة
    await context.bot.send_message(
        ADMIN_LOG_CHAT_ID,
        f"✅ {q.from_user.full_name} سجل حضور الساعة {ts_str}"
    )

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # استدعاء من CallbackQueryHandler
    q = update.callback_query
    await q.answer()
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
    # تأكيد للمستخدم
    await q.message.reply_text("✅ تم تسجيل الانصراف.")
    # سجل في جروب المتابعة
    await context.bot.send_message(
        ADMIN_LOG_CHAT_ID,
        f"⏹️ {q.from_user.full_name} سجل انصراف الساعة {ts_out_str}\n⏳ المدة: {elapsed}"
    )

# -------------------- STUDY ASK FLOW -----------------------
async def ask_study_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    for rec in Q_SHEET.get_all_records()[::-1]:
        if rec.get("Telegram ID")==str(uid) and not (rec.get("الرد") or "").strip():
            await q.message.reply_text("⚠️ لا يمكنك إرسال سؤال جديد حتى يتم الرد على سؤالك السابق.", reply_markup=RESTART_KB)
            return ConversationHandler.END
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
    await update.message.reply_text(f"اختر من الأزرار.", reply_markup=ASK_TYPE_KB)
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
    texts = [c for t, c in msgs if t == 'text']
    photos = [c for t, c in msgs if t == 'photo']
    question = '\n'.join(texts)
    photo_id = photos[0] if photos else ''
    ask_ts_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row_idx = len(Q_SHEET.get_all_values()) + 1

    # 1) خزّن السؤال في Google Sheet
    Q_SHEET.append_row([
        str(uid),
        update.effective_user.full_name,
        question,
        photo_id,
        ask_ts_str,
        "",      # عمود الرد (فارغ)
        gate,    # اسم الباب
        "",      # وقت الرد
        "",      # مسؤول الرد
        ""       # المدة
    ])

    # 2) أرسل الاستفسار للأدمن بالتناوب
    async with admin_lock:
        global admin_index
        active_admins = [aid for aid, s in admin_status.items() if s['checked_in']]
        aid = active_admins[admin_index % len(active_admins)]
        admin_index += 1

    notif = f"📚 استفسار #{row_idx}\n👤 {update.effective_user.full_name}\n📖 {gate}\n\n{question}"
    if photo_id:
        sent = await context.bot.send_photo(aid, photo_id, caption=notif)
    else:
        sent = await context.bot.send_message(aid, notif)
    admin_message_map[sent.message_id] = (uid, row_idx)

    # 3) أرسل نفس السؤال إلى جروب "أسئلة المشتركين"
    header = (
        f"❓ استفسار #{row_idx}\n"
        f"📖 {gate}\n\n"
        f"{question}"
    )
    await context.bot.send_message(SUBSCRIBERS_CHAT_ID, header)
    if photo_id:
        await context.bot.send_photo(SUBSCRIBERS_CHAT_ID, photo_id)

    # 4) أكد للطالب أن سؤاله تم إرساله
    await update.message.reply_text(
        f"✅ تم إرسال سؤالك بنجاح في {gate}\n"
        f"رقم الاستفسار: {row_idx}\n"
        "انتظر رد الفريق العلمي خلال دقائق بإذن الله",
        reply_markup=RESTART_KB
    )

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
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🚀 إرسال الردود", callback_data="send_reply")]]
        )
        await msg.reply_text(
            "✅ تم تخزين ردّك.\nاضغط **إرسال الردود** عندما تنتهي من إضافة جميع الردود.",
            reply_markup=kb,
            parse_mode='Markdown'
        )
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
    for _, _, typ, content in reps:
        if typ == 'text':
            texts.append(content)
        elif typ == 'photo':
            photos.append(content)
        else:
            voices.append(content)

    reply_ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rep_dt = datetime.datetime.strptime(reply_ts, '%Y-%m-%d %H:%M:%S')
    elapsed = str(rep_dt - ask_dt).split('.')[0]

    summary = "\n".join(texts)
    if photos:  summary += f"\n[صور: {len(photos)}]"
    if voices: summary += f"\n[صوتيات: {len(voices)}]"

    # اسم الأدمن الصحيح
    bot_user = await context.bot.get_me()
    admin_name = bot_user.username or bot_user.first_name

    # تحديث جداول الـ Google Sheets
    Q_SHEET.update_cell(row_idx, 6, summary)
    Q_SHEET.update_cell(row_idx, 8, reply_ts)
    Q_SHEET.update_cell(row_idx, 9, admin_name)
    Q_SHEET.update_cell(row_idx, 10, elapsed)

    # إرسال الرد للطالب
    if texts:
        await context.bot.send_message(sid, "🔔 رد الأدمن:\n" + summary)
    for p in photos:
        await context.bot.send_photo(sid, p)
    for v in voices:
        await context.bot.send_voice(sid, v)

    # --- إرسال المتابعة لجروب الأدمن ---
    header = (
        f"❓ استفسار #{row_idx}\n"
        f"📖 {Q_SHEET.cell(row_idx,7).value}\n"
        f"⏱️ من {ask_ts_str} إلى {reply_ts}\n"
        f"⏳ المدة: {elapsed}\n"
        
    )
    await context.bot.send_message(ADMIN_LOG_CHAT_ID, header)
  
    # --- إرسال السؤال + الإجابة لجروب المشتركين ---
    subscribers_msg = (
        f"❓ استفسار #{row_idx}\n"
        f"{Q_SHEET.row_values(row_idx)[2]}\n\n"
        f"💬 الرد:\n{summary}"
    )
    await context.bot.send_message(SUBSCRIBERS_CHAT_ID, subscribers_msg)
    for p in photos:
        await context.bot.send_photo(SUBSCRIBERS_CHAT_ID, p)
    for v in voices:
        await context.bot.send_voice(SUBSCRIBERS_CHAT_ID, v)


    await query.edit_message_text("✅ تم إرسال جميع الردود دفعة واحدة.")

# -------------------- ADMIN PANEL & BROADCAST --------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 بث جماعي", callback_data="broadcast")],
        [InlineKeyboardButton("🕒 تسجيل حضور", callback_data="do_checkin")],
        [InlineKeyboardButton("🏁 تسجيل انصراف", callback_data="do_checkout")]
    ])
    await q.edit_message_text("\ud83d\udc68\u200d\ud83d\udcbb لوحة الأدمن:", reply_markup=kb)


async def do_checkin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await checkin(update, context)
    # بعد تسجيل الحضور في الشيت وفي جروب المتابعة
    await update.callback_query.message.reply_text("✅ تم تسجيل الحضور.")

async def do_checkout_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await checkout(update, context)
    # بعد تسجيل الانصراف في الشيت وفي جروب المتابعة
    await update.callback_query.message.reply_text("✅ تم تسجيل الانصراف.")

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    await q.edit_message_text("اكتب نص الرسالة...\nضع (اسم الطالب).",reply_markup=None)
    return ADMIN_BROADCAST

async def admin_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broadcast_msg']=update.message.text
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 تأكيد",callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ إلغاء",callback_data="admin_panel")]
    ])
    await update.message.reply_text("هل تؤكد؟",reply_markup=kb)
    return ADMIN_BROADCAST_CONFIRM

async def admin_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    tmp=context.user_data.get('broadcast_msg','')
    cnt=0
    for r in SHEET.get_all_records():
        uid=r.get("Telegram ID"); name=r.get("الاسم") or ""
        if uid and name:
            try: await q.bot.send_message(int(uid),tmp.replace("(اسم الطالب)",name)); cnt+=1
            except: pass
    await q.edit_message_text(f"✅ أرسلت لـ {cnt}")
    return ConversationHandler.END

broadcast_conv=ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_broadcast_start,pattern="^broadcast$")],
    states={
        ADMIN_BROADCAST:[MessageHandler(filters.TEXT&~filters.COMMAND,admin_broadcast_input)],
        ADMIN_BROADCAST_CONFIRM:[CallbackQueryHandler(admin_broadcast_confirm,pattern="^broadcast_confirm$")]
    },
    fallbacks=[CallbackQueryHandler(admin_panel,pattern="^admin_panel$")]
)

# -------------------- RESTART MENU ------------------------
async def restart_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("القائمة الرئيسية:",reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("اختر:",reply_markup=main_keyboard(update.effective_user.id))
    # تعيين آي دي الأدمن
ADMIN_IDS = [123456789]  # ← غيّر الرقم لـ Telegram ID بتاعك

# دالة بدء البث
async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("أرسل الرسالة اللي تحب تبعتها لكل الطلاب.")
    return

# دالة استلام رسالة البث
async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    message = update.message.text
    # تحميل آي دي الطلبة من Google Sheet
    sheet = client.open("1yWJDu9I_T30wddt2lkgEO_m6sr1_SDx-WiDUkoZ9UTI").worksheet("المشتركين")
    data = sheet.get_all_records()
    student_ids = [row['Telegram ID'] for row in data if row['Telegram ID']]

    sent_count = 0
    for user_id in student_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            sent_count += 1
        except:
            continue

    await update.message.reply_text(f"تم إرسال الرسالة إلى {sent_count} طالب.")


# ======================= MAIN ==============================
if __name__=="__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # start & registro
    #app.add_handler(CommandHandler("start", start_cmd))
   # app.add_handler(MessageHandler(filters.Regex("^ابدأ ✅$"), on_start_button))
   # app.add_handler(MessageHandler(filters.Regex("^ابدأ المحادثة من جديد$"), restart_menu))

       # conv تسجيل
       # ------------------ تسجيل جديد ------------------
    # ----------- REGISTRATION FLOW -----------
reg_conv = ConversationHandler(
    entry_points=[
        CommandHandler("start", start_cmd),
        MessageHandler(filters.Regex("^ابدأ ✅$"), on_start_button),
        MessageHandler(filters.Regex("^ابدأ المحادثة من جديد$"), on_start_button),
    ],
    states={
        STATE_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name),
            MessageHandler(filters.Regex("^ابدأ المحادثة من جديد$"), on_start_button),
        ],
        STATE_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone),
            MessageHandler(filters.Regex("^ابدأ المحادثة من جديد$"), on_start_button),
        ],
    },
    fallbacks=[]
)
app.add_handler(reg_conv)



    # استفسارات
study_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_study_start,pattern="^ask_study$")],
        states={
            STATE_GATE:[MessageHandler(filters.TEXT&~filters.COMMAND,gate_choose)],
            STATE_CHOOSE:[MessageHandler(filters.TEXT&~filters.COMMAND,choose_type)],
            STATE_ONLY_PHOTO:[MessageHandler(filters.PHOTO&~filters.COMMAND,only_photo)],
            STATE_ONLY_TEXT:[MessageHandler(filters.TEXT&~filters.COMMAND,only_text)],
            STATE_PHOTO_THEN_TEXT:[
                MessageHandler(filters.PHOTO&~filters.COMMAND,photo_then_text),
                MessageHandler(filters.TEXT&~filters.COMMAND,photo_then_text)
            ]
        },
        fallbacks=[]
    )
app.add_handler(study_conv)

    # رد الأدمن وتجميع
app.add_handler(MessageHandler(
        filters.REPLY & filters.User(ADMINS) & (filters.TEXT|filters.PHOTO|filters.VOICE),
        handle_admin_reply
    ))
app.add_handler(CallbackQueryHandler(send_admin_replies,pattern="^send_reply$"))

    # لوحة الأدمن + بث + حضور/انصراف
app.add_handler(CallbackQueryHandler(admin_panel,pattern="^admin_panel$"))
app.add_handler(broadcast_conv)
app.add_handler(CallbackQueryHandler(do_checkin_cb,pattern="^do_checkin$"))
app.add_handler(CallbackQueryHandler(do_checkout_cb,pattern="^do_checkout$"))
app.add_handler(CommandHandler("broadcast", admin_broadcast_start))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_broadcast_message))



logging.info("✅ Bot is running")

app.add_handler(CallbackQueryHandler(view_profile, pattern="^view$"))

update_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(update_profile_start, pattern="^update$")],
    states={
        STATE_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, update_profile_name),
            MessageHandler(filters.Regex("^ابدأ المحادثة من جديد$"), on_start_button),
        ],
        STATE_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, update_profile_phone),
            MessageHandler(filters.Regex("^ابدأ المحادثة من جديد$"), on_start_button),
        ],
    },
    fallbacks=[]
)
app.add_handler(update_conv)

app.run_polling()