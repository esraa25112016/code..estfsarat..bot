import logging
import datetime
import asyncio
import os
import tempfile
import img2pdf  # pip install img2pdf
import pytz
egypt = pytz.timezone("Africa/Cairo")

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
HOMEWORK_ADMINS = [1969054373]

ADMIN_LOG_CHAT_ID = -1002606054225
SUBSCRIBERS_CHAT_ID = -1002624944424

SHEET_ID = "1yWJDu9I_T30wddt2lkgEO_m6sr1_SDx-WiDUkoZ9UTI"
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPES)
GCLIENT = gspread.authorize(CREDS)
FILE = GCLIENT.open_by_key(SHEET_ID)

SHEET     = FILE.worksheet("Students Data")
SUB_SHEET = FILE.worksheet("المشتركين")
Q_SHEET   = FILE.worksheet("استفسارات الطلاب")
try:
    ATT_SHEET = FILE.worksheet("Attendance")
except gspread.exceptions.WorksheetNotFound:
    ATT_SHEET = FILE.add_worksheet("Attendance", rows=1000, cols=5)
try:
    RESULTS_SHEET = FILE.worksheet("تسجيل الواجبات")
except gspread.exceptions.WorksheetNotFound:
    RESULTS_SHEET = FILE.add_worksheet("تسجيل الواجبات", rows=1000, cols=20)

# ======================= STATES ============================
(
    STATE_NAME, STATE_PHONE,
    STATE_GATE, STATE_CHOOSE,
    STATE_ONLY_PHOTO, STATE_ONLY_TEXT, STATE_PHOTO_THEN_TEXT,
    STATE_HW_PHOTOS
) = range(8)

ADMIN_BROADCAST, ADMIN_BROADCAST_CONFIRM = range(10, 12)
ADMIN_SCOPE_CHOICE, ADMIN_GATE_CHOICE, ADMIN_MSG_INPUT, ADMIN_MSG_CONFIRM = range(30, 34)

# ======================= KEYBOARDS ==========================
MAIN_KB    = ReplyKeyboardMarkup([["ابدأ ✅"]], resize_keyboard=True)
RESTART_KB = ReplyKeyboardMarkup([["ابدأ المحادثة من جديد"]], resize_keyboard=True)
GATES_LIST = ["الباب الأول","الباب الثاني","الباب الثالث","الباب الرابع","الباب الخامس"]
ASK_TYPE_KB= ReplyKeyboardMarkup([["صورة فقط"],["نص فقط"],["صورة مع نص"],["ابدأ المحادثة من جديد"]], resize_keyboard=True)

# ======================= GLOBALS ============================
admin_lock            = asyncio.Lock()
admin_status          = {aid:{'checked_in':False,'checkin_ts':None} for aid in ADMINS}
admin_index           = 0
USERS, SUBSCRIBERS    = {}, {}
pending_questions     = {}
admin_message_map     = {}
pending_admin_replies = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def refresh_caches():
    global USERS, SUBSCRIBERS
    try:
        USERS       = {str(r["Telegram ID"]):r for r in SHEET.get_all_records() if r.get("Telegram ID")}
    except Exception as e:
        logging.error(f"Error loading USERS: {e}")
        USERS = {}
    try:
        SUBSCRIBERS = {str(r["Telegram ID"]):r for r in SUB_SHEET.get_all_records() if r.get("Telegram ID")}
    except Exception as e:
        logging.error(f"Error loading SUBSCRIBERS: {e}")
        SUBSCRIBERS = {}
refresh_caches()

def is_registered(uid:int) -> bool:
    return str(uid) in USERS
def is_subscribed(uid:int) -> bool:
    return str(uid) in SUBSCRIBERS

def main_keyboard(uid:int) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("📋 عرض بياناتك", callback_data="view")],
        [InlineKeyboardButton("✏️ تحديث بياناتك", callback_data="update")],
    ]
    if is_subscribed(uid):
        kb.append([InlineKeyboardButton("✍️ استفسارات دراسية", callback_data="ask_study")])
        kb.append([InlineKeyboardButton("اضغط هنا لتسليم الواجب", callback_data="start_homework_submit")])
    if uid in ADMINS:
        kb.append([InlineKeyboardButton("👨‍💻 لوحة الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

# ====================== تسجيل الطالب =======================
async def start_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اضغط على 'ابدأ ✅' للمتابعة.", reply_markup=MAIN_KB)

async def on_start_button(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_registered(uid):
        await update.message.reply_text("أنت مسجل بالفعل.", reply_markup=main_keyboard(uid))
        return ConversationHandler.END
    await update.message.reply_text("اكتب اسمك الكامل:")
    return STATE_NAME

async def reg_name(update:Update, context:ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text.strip()
    await update.message.reply_text("اكتب رقم هاتفك:")
    return STATE_PHONE

async def reg_phone(update:Update, context:ContextTypes.DEFAULT_TYPE):
    name = context.user_data.pop('name', None)
    if not name:
        await update.message.reply_text("حدث خطأ، يرجى بدء التسجيل من جديد.", reply_markup=RESTART_KB)
        return ConversationHandler.END
    phone = update.message.text.strip()
    uid = update.effective_user.id
    username = update.effective_user.username or ''
    ts = datetime.datetime.now(egypt).strftime('%Y-%m-%d %H:%M:%S')
    try:
        SHEET.append_row([name, phone, str(uid), username, ts])
        refresh_caches()
        await update.message.reply_text("✅ تم التسجيل.", reply_markup=main_keyboard(uid))
        await update.message.reply_text("لإعادة عرض القائمة، اضغط:", reply_markup=RESTART_KB)
    except Exception as e:
        logging.error(f"Error during registration append_row: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء التسجيل، حاول لاحقًا.")
    return ConversationHandler.END

# ================ استعراض وتحديث الملف الشخصي =================
async def view_profile(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not is_registered(uid):
        return await q.edit_message_text("❌ لم نعثر على بياناتك.")
    d = USERS.get(str(uid), {})
    text = (
        f"👤 اسم: {escape_markdown(str(d.get('الاسم','-')),2)}\n"
        f"📱 هاتف: {escape_markdown(str(d.get('رقم التليفون','-')),2)}\n"
        f"🔗 @{escape_markdown(str(d.get('Username','-')),2)}"
    )
    await q.edit_message_text(text, parse_mode='MarkdownV2', reply_markup=main_keyboard(uid))

async def update_profile_start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("✏️ اكتب اسمك الجديد:")
    return STATE_NAME

async def update_profile_name(update:Update, context:ContextTypes.DEFAULT_TYPE):
    context.user_data['new_name'] = update.message.text.strip()
    await update.message.reply_text("📞 اكتب رقمك الجديد:")
    return STATE_PHONE

async def update_profile_phone(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    new_name = context.user_data.pop('new_name', None)
    if not new_name:
        await update.message.reply_text("حدث خطأ، يرجى بدء التحديث من جديد.", reply_markup=RESTART_KB)
        return ConversationHandler.END
    new_phone= update.message.text.strip()
    username = update.effective_user.username or ''
    ts       = datetime.datetime.now(egypt).strftime('%Y-%m-%d %H:%M:%S')
    cell     = None
    try:
        cell = SHEET.find(str(uid))
    except Exception as e:
        logging.error(f"Error finding user cell: {e}")
    if cell:
        try:
            SHEET.update(range_name=f"A{cell.row}:E{cell.row}", values=[[new_name, new_phone, str(uid), username, ts]])
            refresh_caches()
            await update.message.reply_text("✅ تم التحديث.", reply_markup=main_keyboard(uid))
        except Exception as e:
            logging.error(f"Error updating profile: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء التحديث، حاول مرة أخرى.")
    else:
        await update.message.reply_text("❌ لم نعثر على بياناتك.")
    return ConversationHandler.END

# ===================== تسجيل الحضور والانصراف =====================
async def checkin(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if uid not in ADMINS: return
    st = admin_status[uid]
    if st['checked_in']:
        await q.message.reply_text("⚠️ أنت مسجل دخول بالفعل."); return
    ts = datetime.datetime.now(egypt); ts_str = ts.strftime('%Y-%m-%d %H:%M:%S')
    st['checked_in'], st['checkin_ts'] = True, ts
    ATT_SHEET.append_row([str(uid), q.from_user.full_name, 'checkin', ts_str, ''])
    await q.message.reply_text("✅ تم تسجيل الحضور.")
    await context.bot.send_message(ADMIN_LOG_CHAT_ID,
                                   f"✅ {q.from_user.full_name} سجل حضور الساعة {ts_str}")

async def checkout(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if uid not in ADMINS: return
    st = admin_status[uid]
    if not st['checked_in']:
        await q.message.reply_text("⚠️ لم تسجل حضور بعد."); return
    ts_out = datetime.datetime.now(egypt); ts_out_str = ts_out.strftime('%Y-%m-%d %H:%M:%S')
    elapsed = str(ts_out - st['checkin_ts']).split('.')[0]
    st['checked_in'] = False
    ATT_SHEET.append_row([str(uid), q.from_user.full_name, 'checkout', ts_out_str, elapsed])
    await q.message.reply_text("✅ تم تسجيل الانصراف.")
    await context.bot.send_message(
        ADMIN_LOG_CHAT_ID,
        f"⏹️ {q.from_user.full_name} سجل انصراف الساعة {ts_out_str}\n⏳ المدة: {elapsed}"
    )

# ==================== اسئلة دراسية ====================
async def ask_study_start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    for rec in Q_SHEET.get_all_records()[::-1]:
        if rec.get("Telegram ID")==str(uid) and not (rec.get("الرد") or "").strip():
            await q.message.reply_text("⚠️ لا يمكنك إرسال سؤال جديد حتى يتم الرد.", reply_markup=RESTART_KB)
            return ConversationHandler.END
    if not any(s['checked_in'] for s in admin_status.values()):
        await q.message.reply_text("⚠️ الخدمة غير متاحة خارج ساعات عمل الأدمن.", reply_markup=RESTART_KB)
        return ConversationHandler.END
    if not is_subscribed(uid):
        return await q.answer("❌ هذه الخدمة للمشتركين فقط.", show_alert=True)
    await q.message.reply_text("اختر الباب:", reply_markup=ReplyKeyboardMarkup([[g] for g in GATES_LIST]+[["ابدأ المحادثة من جديد"]], resize_keyboard=True))
    return STATE_GATE

async def gate_choose(update:Update, context:ContextTypes.DEFAULT_TYPE):
    text=update.message.text
    if text not in GATES_LIST:
        await update.message.reply_text("اختر من الأزرار فقط.", reply_markup=ReplyKeyboardMarkup([[g] for g in GATES_LIST]+[["ابدأ المحادثة من جديد"]], resize_keyboard=True))
        return STATE_GATE
    student=SUBSCRIBERS.get(str(update.effective_user.id),{})
    if student.get(text,"").strip()!="تم":
        await update.message.reply_text(f"غير مشترك في {text}.", reply_markup=ReplyKeyboardMarkup([[g] for g in GATES_LIST]+[["ابدأ المحادثة من جديد"]], resize_keyboard=True))
        return STATE_GATE
    context.user_data["current_gate"]=text
    await update.message.reply_text("اختر النوع:", reply_markup=ASK_TYPE_KB)
    return STATE_CHOOSE

async def choose_type(update:Update, context:ContextTypes.DEFAULT_TYPE):
    t=update.message.text
    pending_questions[update.effective_user.id]=[]
    if t=="صورة فقط":
        await update.message.reply_text("ابعت الصورة.",reply_markup=RESTART_KB); return STATE_ONLY_PHOTO
    if t=="نص فقط":
        await update.message.reply_text("اكتب سؤالك.",reply_markup=RESTART_KB); return STATE_ONLY_TEXT
    if t=="صورة مع نص":
        await update.message.reply_text("ابعت الصورة أولاً.",reply_markup=RESTART_KB); return STATE_PHOTO_THEN_TEXT
    await update.message.reply_text("اختر من الأزرار.",reply_markup=ASK_TYPE_KB); return STATE_CHOOSE

async def only_photo_study(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        pending_questions[update.effective_user.id]=[('photo',update.message.photo[-1].file_id)]
        return await send_study_question(update, context)
    await update.message.reply_text("يجب إرسال صورة."); return STATE_ONLY_PHOTO

async def only_text_study(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if update.message.text:
        pending_questions[update.effective_user.id]=[('text',update.message.text.strip())]
        return await send_study_question(update, context)
    await update.message.reply_text("يجب إرسال نص."); return STATE_ONLY_TEXT

async def photo_then_text_study(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if 'waiting_text' not in context.user_data:
        if update.message.photo:
            context.user_data['photo_id']=update.message.photo[-1].file_id
            context.user_data['waiting_text']=True
            await update.message.reply_text("اكتب نص."); return STATE_PHOTO_THEN_TEXT
        await update.message.reply_text("يجب إرسال صورة."); return STATE_PHOTO_THEN_TEXT
    if update.message.text:
        pending_questions[uid]=[('photo',context.user_data.pop('photo_id')),('text',update.message.text.strip())]
        context.user_data.pop('waiting_text',None)
        return await send_study_question(update, context)
    await update.message.reply_text("يجب إرسال نص بعد الصورة."); return STATE_PHOTO_THEN_TEXT

async def send_study_question(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id; msgs=pending_questions.pop(uid,[])
    gate=context.user_data.get("current_gate","-")
    texts=[c for t,c in msgs if t=='text']; photos=[c for t,c in msgs if t=='photo']
    question="\n".join(texts); photo_id=photos[0] if photos else ""
    ask_ts=datetime.datetime.now(egypt).strftime('%Y-%m-%d %H:%M:%S')
    row_idx=len(Q_SHEET.get_all_values())+1
    Q_SHEET.append_row([str(uid),update.effective_user.full_name,question,photo_id,ask_ts,"",gate,"","",""])
    async with admin_lock:
        global admin_index
        active=[aid for aid,s in admin_status.items() if s['checked_in']]
        aid=active[admin_index%len(active)]; admin_index+=1
    notif=f"📚 استفسار #{row_idx}\n👤 {update.effective_user.full_name}\n📖 {gate}\n\n{question}"
    if photo_id:
        sent=await context.bot.send_photo(aid,photo_id,caption=notif)
    else:
        sent=await context.bot.send_message(aid,notif)
    admin_message_map[sent.message_id]=(uid,row_idx)
    await context.bot.send_message(SUBSCRIBERS_CHAT_ID,f"❓ استفسار #{row_idx}\n📖 {gate}\n\n{question}")
    if photo_id:
        await context.bot.send_photo(SUBSCRIBERS_CHAT_ID,photo_id)
    await update.message.reply_text(f"✅ تم إرسال سؤالك #{row_idx}",reply_markup=RESTART_KB)
    return ConversationHandler.END

async def handle_admin_reply(update:Update, context:ContextTypes.DEFAULT_TYPE):
    msg=update.message; aid=msg.from_user.id
    if aid not in ADMINS or not msg.reply_to_message: return
    mapping=admin_message_map.get(msg.reply_to_message.message_id)
    if not mapping: return
    sid,row_idx=mapping
    try:
        if (Q_SHEET.cell(row_idx,6).value or "").strip():
            await msg.reply_text("⚠️ تم الرد مسبقًا."); return
    except Exception as e:
        logging.error(f"Error reading Q_SHEET cell: {e}")
        return
    if msg.text: typ,content='text',msg.text
    elif msg.photo: typ,content='photo',msg.photo[-1].file_id
    elif msg.voice: typ,content='voice',msg.voice.file_id
    else:
        await msg.reply_text("❌ نوع الرد غير مدعوم."); return
    st=pending_admin_replies.setdefault(aid,[])
    st.append((sid,row_idx,typ,content))
    if len(st)==1:
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 إرسال الردود",callback_data="send_reply")]])
        await msg.reply_text("✅ تم تخزين ردّك.\nاضغط إرسال الردود.",reply_markup=kb)
    else:
        await msg.reply_text("✅ تم تخزين رد إضافي.")

async def send_admin_replies(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    aid=q.from_user.id; reps=pending_admin_replies.pop(aid,[])
    if not reps:
        return await q.edit_message_text("❌ لا توجد ردود لإرسال.")
    sid,row_idx,*_ = reps[0]
    try:
        ask_ts_str=Q_SHEET.cell(row_idx,5).value
        ask_dt=datetime.datetime.strptime(ask_ts_str,'%Y-%m-%d %H:%M:%S')
    except Exception as e:
        logging.error(f"Error reading question timestamp: {e}")
        await q.edit_message_text("❌ خطأ في قراءة بيانات السؤال.")
        return
    texts,photos,voices=[],[],[]
    for *_ ,typ,content in reps:
        if typ=='text': texts.append(content)
        elif typ=='photo': photos.append(content)
        else: voices.append(content)
    reply_ts=datetime.datetime.now(egypt).strftime('%Y-%m-%d %H:%M:%S')
    elapsed=str(datetime.datetime.strptime(reply_ts,'%Y-%m-%d %H:%M:%S')-ask_dt).split('.')[0]
    summary="\n".join(texts)
    if photos: summary+=f"\n[صور: {len(photos)}]"
    if voices: summary+=f"\n[صوتيات: {len(voices)}]"
    admin_name=q.from_user.full_name
    try:
        Q_SHEET.update_cell(row_idx,6,summary)
        Q_SHEET.update_cell(row_idx,8,reply_ts)
        Q_SHEET.update_cell(row_idx,9,admin_name)
        Q_SHEET.update_cell(row_idx,10,elapsed)
    except Exception as e:
        logging.error(f"Error updating Q_SHEET with replies: {e}")
        await q.edit_message_text("❌ حدث خطأ أثناء تحديث بيانات الردود.")
        return
    try:
        if texts: await context.bot.send_message(sid,"🔔 رد الأدمن:\n"+summary)
        for p in photos: await context.bot.send_photo(sid,p)
        for v in voices: await context.bot.send_voice(sid,v)
        header=(
            f"❓ استفسار #{row_idx}\n"
            f"📖 {Q_SHEET.cell(row_idx,7).value}\n"
            f"👨‍💻 رد بواسطة: {admin_name}\n"
            f"⏱️ من {ask_ts_str} إلى {reply_ts}\n"
            f"⏳ المدة: {elapsed}"
        )
        await context.bot.send_message(ADMIN_LOG_CHAT_ID,header)
        sub_msg=(
            f"❓ استفسار #{row_idx}\n{Q_SHEET.row_values(row_idx)[2]}\n\n"
            f"💬 الرد:\n{summary}"
        )
        await context.bot.send_message(SUBSCRIBERS_CHAT_ID,sub_msg)
        for p in photos: await context.bot.send_photo(SUBSCRIBERS_CHAT_ID,p)
        for v in voices: await context.bot.send_voice(SUBSCRIBERS_CHAT_ID,v)
        await q.edit_message_text("✅ تم إرسال جميع الردود دفعة واحدة.")
    except Exception as e:
        logging.error(f"Error sending replies messages: {e}")
        await q.edit_message_text("❌ حدث خطأ أثناء إرسال الردود.")

# ==================== لوحة الأدمن والبث ====================
async def admin_panel(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 تسجيل حضور", callback_data="do_checkin")],
        [InlineKeyboardButton("🏁 تسجيل انصراف", callback_data="do_checkout")],
        [InlineKeyboardButton("📨 بث بأسماء الطلاب", callback_data="custom_broadcast")],
    ])
    await q.edit_message_text("لوحة الأدمن:", reply_markup=kb)

async def do_checkin_cb(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await checkin(update, context)

async def do_checkout_cb(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await checkout(update, context)

# -------------------- البث المخصص ------------------------
async def custom_broadcast_choice(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📣 لجميع المشتركين", callback_data="scope_all")],
        [InlineKeyboardButton("🚪 حسب الباب", callback_data="scope_gate")],
        [InlineKeyboardButton("❌ إلغاء",      callback_data="admin_panel")],
    ])
    await q.edit_message_text("اختر المستلمين:", reply_markup=kb)
    return ADMIN_SCOPE_CHOICE

async def custom_broadcast_gate_menu(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    btns = []
    for idx, g in enumerate(GATES_LIST, start=1):
        btns.append([InlineKeyboardButton(g, callback_data=f"gate_{idx}")])
    btns.append([InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel")])
    await q.edit_message_text("اختر الباب:", reply_markup=InlineKeyboardMarkup(btns))
    return ADMIN_GATE_CHOICE

async def custom_broadcast_message(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data['broadcast_scope'] = q.data  # "scope_all" or "gate_N"
    await q.edit_message_text(
        "✏️ اكتب نص الرسالة:\n"
        "استخدم (اسم الطالب) لاستبداله."
    )
    return ADMIN_MSG_INPUT

async def custom_broadcast_confirm_input(update:Update, context:ContextTypes.DEFAULT_TYPE):
    context.user_data['broadcast_msg'] = update.message.text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 أرسل الآن", callback_data="do_broadcast")],
        [InlineKeyboardButton("❌ إلغاء",   callback_data="admin_panel")],
    ])
    await update.message.reply_text(
        f"📝 معاينة:\n\n{update.message.text}\n\n"
        "اضغط 🚀 للإرسال أو ❌ للإلغاء.",
        reply_markup=kb
    )
    return ADMIN_MSG_CONFIRM

async def custom_broadcast_execute(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q     = update.callback_query; await q.answer()
    scope = context.user_data.get('broadcast_scope', '')
    tpl   = context.user_data.get('broadcast_msg', '')
    sent  = 0

    gate_filter = None
    if scope.startswith("gate_"):
        idx = int(scope.split("_")[1]) - 1
        gate_filter = GATES_LIST[idx]

    for rec in SUB_SHEET.get_all_records():
        uid  = rec.get("Telegram ID")
        name = rec.get("الاسم")
        if not uid or not name:
            continue
        if gate_filter and rec.get(gate_filter, "").strip() != "تم":
            continue
        text = tpl.replace("(اسم الطالب)", name)
        try:
            await context.bot.send_message(int(uid), text)
            sent += 1
        except Exception as e:
            logging.error(f"Error sending broadcast to {uid}: {e}")
            continue

    await q.edit_message_text(f"✅ أرسل {sent} رسالة.")
    context.user_data.pop('broadcast_scope', None)
    context.user_data.pop('broadcast_msg', None)
    return ConversationHandler.END

custom_broadcast_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(custom_broadcast_choice, pattern="^custom_broadcast$")],
    states={
        ADMIN_SCOPE_CHOICE: [
            CallbackQueryHandler(custom_broadcast_gate_menu, pattern="^scope_gate$"),
            CallbackQueryHandler(custom_broadcast_message,  pattern="^scope_all$"),
        ],
        ADMIN_GATE_CHOICE: [
            CallbackQueryHandler(custom_broadcast_message, pattern="^gate_")
        ],
        ADMIN_MSG_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, custom_broadcast_confirm_input)
        ],
        ADMIN_MSG_CONFIRM: [
            CallbackQueryHandler(custom_broadcast_execute, pattern="^do_broadcast$")
        ],
    },
    fallbacks=[CallbackQueryHandler(admin_panel, pattern="^admin_panel$")],
    per_message=False, per_user=True
)

# ===================== تسليم الواجب =====================
async def show_homework_list(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    try:
        hw_sheet=FILE.worksheet("تسجيل الواجبات")
    except Exception as e:
        logging.error(f"Error opening homework sheet: {e}")
        return await q.edit_message_text("❌ شيت 'تسجيل الواجبات' غير موجود.")
    try:
        records=hw_sheet.get_all_records()
        hw_names=sorted({r.get("اسم الواجب","").strip() for r in records if r.get("اسم الواجب","").strip()})
    except Exception as e:
        logging.error(f"Error reading homework records: {e}")
        return await q.edit_message_text("❌ حدث خطأ أثناء جلب الواجبات.")
    if not hw_names:
        return await q.edit_message_text("⚠️ لا توجد واجبات مسجلة حالياً.")
    buttons=[[InlineKeyboardButton(name,callback_data=f"select_hw::{name}")] for name in hw_names]
    buttons.append([InlineKeyboardButton("❌ إلغاء",callback_data="cancel_homework")])
    await q.edit_message_text("اختر اسم الواجب المطلوب تسليمه:",reply_markup=InlineKeyboardMarkup(buttons))

async def handle_homework_selection(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); data=q.data
    if data=="cancel_homework":
        return await q.edit_message_text("تم إلغاء تسليم الواجب.")
    if data.startswith("select_hw::"):
        hw_name=data.split("::",1)[1]
        context.user_data['selected_homework']=hw_name
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("رفع صور",callback_data="hw_submit_photos")],
            [InlineKeyboardButton("رفع PDF",callback_data="hw_submit_pdf")],
            [InlineKeyboardButton("❌ إلغاء",callback_data="cancel_homework")]
        ])
        return await q.edit_message_text(f"✅ اخترت الواجب: *{hw_name}*\n\nكيف تريد التسليم؟",parse_mode='Markdown',reply_markup=kb)

async def handle_hw_submit_method(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); data=q.data
    if data=="hw_submit_photos":
        context.user_data['hw_photos']=[]; context.user_data.pop('last_send_button_msg_id',None)
        return await q.edit_message_text("اتفضل ابعت جميع صور السؤال.\nعندما تنتهي اضغط زر 'إرسال'.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إرسال",callback_data="send_photos_pdf")]]))
    if data=="hw_submit_pdf":
        context.user_data['awaiting_pdf']=True
        return await q.edit_message_text("من فضلك ارفع ملف PDF الخاص بالواجب.")
    if data=="cancel_homework":
        return await q.edit_message_text("تم إلغاء تسليم الواجب.")

async def receive_hw_photos(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photos=context.user_data.setdefault('hw_photos',[])
        photos.append(update.message.photo[-1].file_id)
        if 'last_send_button_msg_id' in context.user_data:
            try: await update.message.delete_message(context.user_data['last_send_button_msg_id'])
            except: pass
        sent=await update.message.reply_text(f"✅ استلمت صورة {len(photos)}. ابعت صور أكثر أو اضغط إرسال.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إرسال",callback_data="send_photos_pdf")]]))
        context.user_data['last_send_button_msg_id']=sent.message_id
        return STATE_HW_PHOTOS
    return await update.message.reply_text("يرجى إرسال صورة فقط.")

async def send_photos_as_pdf(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    photos=context.user_data.get('hw_photos',[])
    if not photos:
        return await q.edit_message_text("لم ترسل أي صور بعد.")
    uid=q.from_user.id; hw_name=context.user_data.get('selected_homework','غير محدد')
    ts=datetime.datetime.now(egypt)
    date_str=ts.strftime('%Y-%m-%d'); time_str=ts.strftime('%H:%M:%S')
    with tempfile.TemporaryDirectory() as tmpdir:
        paths=[]
        for i,fid in enumerate(photos):
            file=await context.bot.get_file(fid)
            p=os.path.join(tmpdir,f"img_{i}.jpg")
            await file.download_to_drive(p); paths.append(p)
        pdf_path=os.path.join(tmpdir,f"{hw_name}_{uid}.pdf")
        with open(pdf_path,"wb") as f: f.write(img2pdf.convert(paths))
        try:
            RESULTS_SHEET.append_row([USERS[str(uid)]["الاسم"],str(uid),"",date_str,"",hw_name,time_str,""])
        except Exception as e: logging.error(e)
        student_name=USERS[str(uid)]["الاسم"]
        for aid in HOMEWORK_ADMINS:
            try:
                with open(pdf_path,"rb") as doc:
                    await context.bot.send_document(aid,doc,caption=(
                        f"📥 تسليم واجب جديد\n👤 {student_name} ({uid})\n📝 {hw_name}\n⏰ {date_str} {time_str}"
                    ))
            except Exception as e: logging.error(e)
    await send_homework_evaluation_to_admin(context, uid, student_name, hw_name)
    context.user_data.pop('hw_photos',None); context.user_data.pop('selected_homework',None)
    await q.edit_message_text("✅ تم إنشاء ملف PDF وإرساله للأدمن لمراجعته.\nسوف تصلك نتيجة التقييم قريبًا.", reply_markup=main_keyboard(uid))
    return ConversationHandler.END

async def only_photo(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if context.user_data.get('awaiting_pdf'):
        doc=update.message.document
        if doc and doc.mime_type=="application/pdf":
            fid=doc.file_id; hw_name=context.user_data['selected_homework']
            ts=datetime.datetime.now(egypt)
            date_str=ts.strftime('%Y-%m-%d'); time_str=ts.strftime('%H:%M:%S')
            try:
                RESULTS_SHEET.append_row([USERS[str(uid)]["الاسم"],str(uid),"",date_str,"",hw_name,time_str,""])
            except Exception as e: logging.error(e)
            student_name=USERS[str(uid)]["الاسم"]
            for aid in HOMEWORK_ADMINS:
                try:
                    await context.bot.send_document(aid,fid,caption=(
                        f"📥 تسليم واجب جديد\n👤 {student_name} ({uid})\n📝 {hw_name}\n📄 PDF\n⏰ {date_str} {time_str}"
                    ))
                except Exception as e: logging.error(e)
            await send_homework_evaluation_to_admin(context, uid, student_name, hw_name)
            context.user_data.pop('awaiting_pdf',None); context.user_data.pop('selected_homework',None)
            await update.message.reply_text(f"✅ تم استلام ملف PDF للواجب '{hw_name}'. شكراً لك.",reply_markup=main_keyboard(uid))
            return ConversationHandler.END
        await update.message.reply_text("❌ الرجاء إرسال ملف PDF فقط."); return STATE_ONLY_PHOTO
    await update.message.reply_text("يرجى إرسال صورة أو ملف PDF.",reply_markup=RESTART_KB)
    return STATE_ONLY_PHOTO

async def send_homework_evaluation_to_admin(context:ContextTypes.DEFAULT_TYPE, sid:int, student_name:str, hw_name:str):
    kb=InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ صحيح",callback_data=f"hw_eval_correct::{sid}::{hw_name}"),
        InlineKeyboardButton("❌ خطأ", callback_data=f"hw_eval_wrong::{sid}::{hw_name}")
    ]])
    for aid in HOMEWORK_ADMINS:
        try:
            await context.bot.send_message(aid,
                f"📥 واجب جديد من الطالب:\n👤 {student_name} ({sid})\n📝 {hw_name}\n\nاختر التقييم:",
                reply_markup=kb
            )
        except Exception as e: logging.error(e)

async def handle_homework_evaluation(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    try:
        action,sid_str,hw_name=q.data.split("::")
        sid=int(sid_str)
    except Exception as e:
        logging.error(f"Error parsing homework eval callback data: {e}")
        return await q.edit_message_text("❌ بيانات غير صحيحة.")
    student=USERS.get(str(sid))
    if not student:
        return await q.edit_message_text("❌ بيانات الطالب غير موجودة.")
    correct_val=1 if action=="hw_eval_correct" else 0
    try:
        records=RESULTS_SHEET.get_all_records()
    except Exception as e:
        logging.error(f"Error fetching homework records: {e}")
        return await q.edit_message_text("❌ حدث خطأ في جلب بيانات الواجبات.")
    row_idx=None
    for idx, rec in enumerate(records[::-1], 1):
        if rec.get("اسم الطالب")==student.get("الاسم") and str(rec.get("Telegram ID"))==str(sid) and rec.get("تسليم واجب الطالب")==hw_name and rec.get("الحالة")=="":
            row_idx=len(records)-idx+2
            break
    if not row_idx:
        return await q.edit_message_text("لم يتم العثور على تسليم مناسب.")
    try:
        RESULTS_SHEET.update_cell(row_idx,8,correct_val)
        RESULTS_SHEET.update_cell(row_idx,3,q.from_user.full_name)
    except Exception as e:
        logging.error(f"Error updating homework evaluation: {e}")
        return await q.edit_message_text("خطأ في تحديث الشيت.")
    reply_text = f"✅ الملف صحيح، أحسنت! الواجب: {hw_name}" if correct_val else f"❌ الملف خطأ، برجاء إعادة تسليم الواجب: {hw_name}"
    try:
        await context.bot.send_message(sid,reply_text)
    except Exception as e:
        logging.error(f"Error sending evaluation result to student: {e}")
    status_str="صحيح" if correct_val else "خطأ"
    await q.edit_message_text(f"✅ تم تسجيل تقييم '{status_str}' للطالب {student.get('الاسم','')} على الواجب '{hw_name}'.")

# ================ زر إعادة المحادثة دومًا ظاهر ===================
async def restart_menu(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("القائمة الرئيسية:",reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("اختر:",reply_markup=main_keyboard(update.effective_user.id))

# ======================= MAIN ================================
if __name__ == "__main__":
    app=ApplicationBuilder().token(BOT_TOKEN).build()

    # تسجيل
    reg_conv=ConversationHandler(
        entry_points=[
            CommandHandler("start",start_cmd),
            MessageHandler(filters.Regex("^ابدأ ✅$"),on_start_button),
            MessageHandler(filters.Regex("^ابدأ المحادثة من جديد$"),on_start_button),
        ],
        states={
            STATE_NAME : [MessageHandler(filters.TEXT & ~filters.COMMAND,reg_name)],
            STATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND,reg_phone)]
        },
        fallbacks=[]
    )
    app.add_handler(reg_conv)

    # عرض وتحديث الملف الشخصي
    app.add_handler(CallbackQueryHandler(view_profile,pattern="^view$"))
    update_conv=ConversationHandler(
        entry_points=[CallbackQueryHandler(update_profile_start,pattern="^update$")],
        states={
            STATE_NAME : [MessageHandler(filters.TEXT & ~filters.COMMAND,update_profile_name)],
            STATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND,update_profile_phone)]
        },
        fallbacks=[]
    )
    app.add_handler(update_conv)

    # أسئلة دراسية
    study_conv=ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_study_start,pattern="^ask_study$")],
        states={
            STATE_GATE           : [MessageHandler(filters.TEXT & ~filters.COMMAND,gate_choose)],
            STATE_CHOOSE         : [MessageHandler(filters.TEXT & ~filters.COMMAND,choose_type)],
            STATE_ONLY_PHOTO     : [MessageHandler(filters.PHOTO & ~filters.COMMAND,only_photo_study)],
            STATE_ONLY_TEXT      : [MessageHandler(filters.TEXT  & ~filters.COMMAND,only_text_study)],
            STATE_PHOTO_THEN_TEXT: [
                MessageHandler(filters.PHOTO & ~filters.COMMAND,photo_then_text_study),
                MessageHandler(filters.TEXT  & ~filters.COMMAND,photo_then_text_study)
            ],
        },
        fallbacks=[]
    )
    app.add_handler(study_conv)

    # رد على استفسارات الأدمن
    app.add_handler(MessageHandler(filters.REPLY & filters.User(ADMINS) & (filters.TEXT|filters.PHOTO|filters.VOICE),handle_admin_reply))
    app.add_handler(CallbackQueryHandler(send_admin_replies,pattern="^send_reply$"))

    # لوحة الأدمن وبث
    app.add_handler(CallbackQueryHandler(admin_panel,pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(do_checkin_cb,pattern="^do_checkin$"))
    app.add_handler(CallbackQueryHandler(do_checkout_cb,pattern="^do_checkout$"))
    app.add_handler(custom_broadcast_conv)

    # تسليم الواجب
    app.add_handler(CallbackQueryHandler(show_homework_list,pattern="^start_homework_submit$"))
    app.add_handler(CallbackQueryHandler(handle_homework_selection,pattern="^select_hw::"))
    app.add_handler(CallbackQueryHandler(handle_homework_selection,pattern="^cancel_homework$"))
    app.add_handler(CallbackQueryHandler(handle_hw_submit_method,pattern="^hw_submit_"))
    app.add_handler(CallbackQueryHandler(send_photos_as_pdf,pattern="^send_photos_pdf$"))
    app.add_handler(MessageHandler(filters.PHOTO,receive_hw_photos))
    app.add_handler(MessageHandler(filters.Document.PDF,only_photo))
    app.add_handler(CallbackQueryHandler(handle_homework_evaluation,pattern="^hw_eval_(correct|wrong)::"))

    # زر إعادة المحادثة دومًا ظاهر
    app.add_handler(MessageHandler(filters.Regex("^ابدأ المحادثة من جديد$"),restart_menu))

    logging.info("✅ Bot is running")
    app.run_polling()
