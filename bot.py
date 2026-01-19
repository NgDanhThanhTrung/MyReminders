import os
import json
import gspread
import datetime
import pytz
from flask import Flask
from threading import Thread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- 1. WEB SERVICE CHO RENDER ---
app = Flask(__name__)
@app.route('/')
def health_check(): return "Bot cá nhân đang hoạt động!", 200

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

# --- 2. KẾT NỐI GOOGLE SHEET ---
def get_sheet():
    json_creds = os.getenv('GCP_SERVICE_ACCOUNT_JSON')
    info = json.loads(json_creds)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
    return gspread.authorize(creds).open("MyReminders").sheet1 # Thay đúng tên file Sheet

# --- 3. CÁC HÀM LỆNH (COMMANDS) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != os.getenv('MY_CHAT_ID'): return
    keyboard = [['📝 Danh sách', '➕ Thêm nhanh'], ['✅ Hoàn thành (/done)', '⚙️ Trạng thái']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("👋 Chào chủ nhân! Tôi đã sẵn sàng.", reply_markup=reply_markup)

async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != os.getenv('MY_CHAT_ID'): return
    try:
        input_text = " ".join(context.args)
        if "|" not in input_text:
            await update.message.reply_text("❌ Định dạng: `/add 15:30 | Nội dung`", parse_mode='Markdown')
            return
        time_p, msg_p = input_text.split("|", 1)
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        today = datetime.datetime.now(vn_tz).strftime("%d/%m/%Y")
        get_sheet().append_row([f"{time_p.strip()} {today}", msg_p.strip(), "Pending"])
        await update.message.reply_text(f"✅ Đã thêm: {time_p.strip()} - {msg_p.strip()}")
    except Exception as e: await update.message.reply_text(f"❌ Lỗi: {e}")

async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != os.getenv('MY_CHAT_ID'): return
    try:
        rows = get_sheet().get_all_values()
        pending = [f"📅 {r[0]}: {r[1]}" for r in rows[1:] if len(r) >= 3 and r[2].strip().lower() == 'pending']
        await update.message.reply_text("📝 **VIỆC CẦN LÀM:**\n\n" + "\n".join(pending) if pending else "✅ Trống!", parse_mode='Markdown')
    except Exception as e: await update.message.reply_text(f"❌ Lỗi: {e}")

async def done_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != os.getenv('MY_CHAT_ID'): return
    try:
        sheet = get_sheet()
        records = sheet.get_all_values()
        pending_rows = [(i, r) for i, r in enumerate(records[1:], start=2) if len(r) >= 3 and r[2].strip().lower() == 'pending']
        
        if not context.args:
            msg = "📝 Chọn số để xong:\n" + "\n".join([f"{i+1}. {r[1]}" for i, (idx, r) in enumerate(pending_rows)])
            await update.message.reply_text(msg + "\n\nVí dụ: `/done 1`")
            return
            
        idx_in_pending = int(context.args[0]) - 1
        actual_row = pending_rows[idx_in_pending][0]
        sheet.update_cell(actual_row, 3, "Done")
        await update.message.reply_text(f"✅ Đã xong việc số {context.args[0]}")
    except: await update.message.reply_text("❌ Vui lòng nhập đúng số thứ tự.")

# --- 4. TỰ ĐỘNG NHẮC & RESET ---

async def auto_check(context: ContextTypes.DEFAULT_TYPE):
    try:
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        now_str = datetime.datetime.now(vn_tz).strftime("%H:%M %d/%m/%Y")
        sheet = get_sheet()
        for i, r in enumerate(sheet.get_all_values()[1:], start=2):
            if len(r) >= 3 and r[2].strip().lower() == 'pending' and r[0].strip() == now_str:
                await context.bot.send_message(os.getenv('MY_CHAT_ID'), text=f"⏰ **ĐẾN GIỜ:** {r[1]}")
                sheet.update_cell(i, 3, "Done")
    except: pass

async def daily_reset(context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        rows = sheet.get_all_values()
        new_rows = [rows[0]] + [r for r in rows[1:] if len(r) >= 3 and r[2].strip().lower() == 'pending']
        sheet.clear()
        sheet.update('A1', new_rows)
        await context.bot.send_message(os.getenv('MY_CHAT_ID'), text="♻️ Đã dọn dẹp các việc cũ.")
    except: pass

# --- 5. XỬ LÝ MENU NÚT BẤM ---
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📝 Danh sách': await list_reminders(update, context)
    elif text == '➕ Thêm nhanh': await update.message.reply_text("Gõ theo mẫu: `/add 15:30 | Nội dung`", parse_mode='Markdown')
    elif text == '⚙️ Trạng thái':
        vn_now = datetime.datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime("%H:%M:%S")
        await update.message.reply_text(f"🤖 Bot Online.\n⏰ Giờ VN: {vn_now}")

# --- 6. MAIN ---
if __name__ == '__main__':
    Thread(target=run_web, daemon=True).start()
    app_tele = ApplicationBuilder().token(os.getenv('TELEGRAM_TOKEN')).build()
    
    app_tele.add_handler(CommandHandler("start", start))
    app_tele.add_handler(CommandHandler("add", add_reminder))
    app_tele.add_handler(CommandHandler("list", list_reminders))
    app_tele.add_handler(CommandHandler("done", done_reminder))
    app_tele.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

    jq = app_tele.job_queue
    jq.run_repeating(auto_check, interval=60)
    jq.run_daily(daily_reset, time=datetime.time(hour=0, minute=1, tzinfo=pytz.timezone('Asia/Ho_Chi_Minh')))

    app_tele.run_polling()
