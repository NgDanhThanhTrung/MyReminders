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

# ==========================================================
# 1. CẤU HÌNH BIẾN MÔI TRƯỜNG (ĐẶT Ở ĐẦU CHO DỄ NHÌN)
# ==========================================================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
MY_CHAT_ID = os.getenv('MY_CHAT_ID')
GCP_JSON_STR = os.getenv('GCP_SERVICE_ACCOUNT_JSON')
PORT = int(os.environ.get("PORT", 8000))
SHEET_NAME = "MyReminders" # Tên file Google Sheet của bạn

# ==========================================================
# 2. TẠO SERVER FLASK (GIỮ BOT LUÔN THỨC TRÊN RENDER)
# ==========================================================
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

def run_web_service():
    app.run(host='0.0.0.0', port=PORT)

# ==========================================================
# 3. KẾT NỐI GOOGLE SHEET
# ==========================================================
def get_sheet():
    info = json.loads(GCP_JSON_STR)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1

# ==========================================================
# 4. CÁC HÀM LỆNH (COMMAND HANDLERS)
# ==========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != MY_CHAT_ID: return
    keyboard = [['📝 Danh sách', '➕ Thêm nhanh'], ['✅ Hoàn thành (/done)', '⚙️ Trạng thái']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("👋 Chào chủ nhân! Hệ thống nhắc hẹn đã sẵn sàng.", reply_markup=reply_markup)

async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != MY_CHAT_ID: return
    try:
        input_text = " ".join(context.args)
        if "|" not in input_text:
            await update.message.reply_text("❌ Nhập: `/add 15:30 | Nội dung`", parse_mode='Markdown')
            return
        time_p, msg_p = input_text.split("|", 1)
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        today = datetime.datetime.now(vn_tz).strftime("%d/%m/%Y")
        get_sheet().append_row([f"{time_p.strip()} {today}", msg_p.strip(), "Pending"])
        await update.message.reply_text(f"✅ Đã thêm: {time_p.strip()} - {msg_p.strip()}")
    except Exception as e: await update.message.reply_text(f"❌ Lỗi: {e}")

async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != MY_CHAT_ID: return
    try:
        rows = get_sheet().get_all_values()
        pending = [f"🔹 {r[0]}: {r[1]}" for r in rows[1:] if len(r) >= 3 and r[2].strip().lower() == 'pending']
        await update.message.reply_text("📝 **DANH SÁCH:**\n\n" + "\n".join(pending) if pending else "✅ Trống!", parse_mode='Markdown')
    except Exception as e: await update.message.reply_text(f"❌ Lỗi: {e}")

async def done_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != MY_CHAT_ID: return
    try:
        sheet = get_sheet()
        records = sheet.get_all_values()
        pending_rows = [(i, r) for i, r in enumerate(records[1:], start=2) if len(r) >= 3 and r[2].strip().lower() == 'pending']
        if not context.args:
            msg = "🔢 Chọn số để hoàn thành:\n" + "\n".join([f"{i+1}. {r[1]}" for i, (idx, r) in enumerate(pending_rows)])
            await update.message.reply_text(msg + "\n\nVí dụ: `/done 1`")
            return
        idx = int(context.args[0]) - 1
        sheet.update_cell(pending_rows[idx][0], 3, "Done")
        await update.message.reply_text(f"✅ Đã xong việc số {context.args[0]}")
    except: await update.message.reply_text("❌ Nhập số thứ tự hợp lệ.")

# ==========================================================
# 5. TỰ ĐỘNG QUÉT NHẮC HẸN & DỌN DẸP
# ==========================================================

async def auto_check(context: ContextTypes.DEFAULT_TYPE):
    try:
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        now_str = datetime.datetime.now(vn_tz).strftime("%H:%M %d/%m/%Y")
        sheet = get_sheet()
        for i, r in enumerate(sheet.get_all_values()[1:], start=2):
            if len(r) >= 3 and r[2].strip().lower() == 'pending' and r[0].strip() == now_str:
                await context.bot.send_message(MY_CHAT_ID, text=f"⏰ **BÁO THỨC:**\n\n🔔 {r[1]}")
                sheet.update_cell(i, 3, "Done")
    except: pass

async def auto_reset(context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        rows = sheet.get_all_values()
        new_rows = [rows[0]] + [r for r in rows[1:] if len(r) >= 3 and r[2].strip().lower() == 'pending']
        sheet.clear()
        sheet.update('A1', new_rows)
        await context.bot.send_message(MY_CHAT_ID, text="♻️ Đã dọn dẹp các việc cũ ngày hôm qua.")
    except: pass

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📝 Danh sách': await list_reminders(update, context)
    elif text == '➕ Thêm nhanh': await update.message.reply_text("Gõ: `/add Giờ:Phút | Nội dung`", parse_mode='Markdown')
    elif text == '⚙️ Trạng thái':
        vn_now = datetime.datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime("%H:%M:%S")
        await update.message.reply_text(f"🟢 Bot Online\n⏰ Giờ VN: {vn_now}")

# ==========================================================
# 6. KHỞI CHẠY (MAIN)
# ==========================================================
if __name__ == '__main__':
    # Chạy Web Server (luồng riêng)
    Thread(target=run_web_service, daemon=True).start()

    # Khởi tạo Telegram Bot
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Đăng ký xử lý lệnh và tin nhắn
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_reminder))
    application.add_handler(CommandHandler("list", list_reminders))
    application.add_handler(CommandHandler("done", done_reminder))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

    # Lịch trình tự động
    jq = application.job_queue
    jq.run_repeating(auto_check, interval=60, first=10)
    # Chạy dọn dẹp lúc 00:01 sáng mỗi ngày
    reset_time = datetime.time(hour=0, minute=1, tzinfo=pytz.timezone('Asia/Ho_Chi_Minh'))
    jq.run_daily(auto_reset, time=reset_time)

    print("Bot is starting...")
    application.run_polling()
