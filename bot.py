import os
import json
import gspread
import datetime
import pytz
import logging
from flask import Flask
from threading import Thread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import ReplyKeyboardMarkup, Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- CẤU HÌNH LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================================
# 1. CẤU HÌNH BIẾN MÔI TRƯỜNG
# ==========================================================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
MY_CHAT_ID = os.getenv('MY_CHAT_ID')
GCP_JSON_STR = os.getenv('GCP_SERVICE_ACCOUNT_JSON')
PORT = int(os.environ.get("PORT", 8000))
SHEET_NAME = "MyReminders"
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# ==========================================================
# 2. WEB SERVER (CHỐNG NGỦ)
# ==========================================================
app = Flask(__name__)
@app.route('/')
def health_check(): return "Bot is Online!", 200

def run_web_service():
    app.run(host='0.0.0.0', port=PORT)

# ==========================================================
# 3. KẾT NỐI GOOGLE SHEET
# ==========================================================
def get_sheet():
    try:
        info = json.loads(GCP_JSON_STR)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
        client = gspread.authorize(creds)
        return client.open(SHEET_NAME).sheet1
    except Exception as e:
        logging.error(f"Lỗi kết nối Sheet: {e}")
        return None

# ==========================================================
# 4. CÁC HÀM XỬ LÝ LỆNH
# ==========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != MY_CHAT_ID: return
    
    # --- THIẾT LẬP NÚT MENU GÓC TRÁI (COMMANDS) ---
    commands = [
        BotCommand("start", "Khởi động bot"),
        BotCommand("list", "Xem danh sách việc hôm nay"),
        BotCommand("done", "Xác nhận đã xong việc"),
        BotCommand("add", "Hướng dẫn: /add 08:00 - 09:00 | Việc")
    ]
    await context.bot.set_my_commands(commands)

    user_name = update.effective_user.first_name
    keyboard = [['📝 Danh sách', '➕ Thêm nhanh'], ['✅ Hoàn thành (/done)', '⚙️ Trạng thái']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"👋 Quản gia Telegram xin chào {user_name}", 
        reply_markup=reply_markup
    )

async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != MY_CHAT_ID: return
    try:
        input_text = " ".join(context.args)
        if "|" not in input_text or "-" not in input_text:
            await update.message.reply_text("❌ Định dạng: `/add 08:00 - 09:00 | Nội dung`", parse_mode='Markdown')
            return
            
        time_part, msg_p = input_text.split("|", 1)
        start_t, end_t = time_part.split("-", 1)
        today = datetime.datetime.now(VN_TZ).strftime("%d/%m/%Y")
        
        sheet = get_sheet()
        sheet.append_row([f"{start_t.strip()} {today}", f"{end_t.strip()} {today}", msg_p.strip(), "Pending"])
        
        await update.message.reply_text(f"✅ Đã ghi nhận: {start_t.strip()} ➔ {end_t.strip()} | {msg_p.strip()}")
    except Exception as e: await update.message.reply_text(f"❌ Lỗi: {e}")

async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != MY_CHAT_ID: return
    try:
        rows = get_sheet().get_all_values()
        pending = [f"🔹 `{r[0].split()[0]} - {r[1].split()[0]}`: {r[2]}" for r in rows[1:] if len(r) >= 4 and r[3].strip().lower() == 'pending']
        
        text = "📅 **LỊCH TRÌNH CỦA BẠN:**\n\n" + ("\n".join(pending) if pending else "✅ Đã xong hết mọi việc!")
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e: await update.message.reply_text(f"❌ Lỗi: {e}")

async def done_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != MY_CHAT_ID: return
    try:
        sheet = get_sheet()
        records = sheet.get_all_values()
        pending_rows = [(i, r) for i, r in enumerate(records[1:], start=2) if len(r) >= 4 and r[3].strip().lower() == 'pending']
        
        if not context.args:
            msg = "🔢 **Chọn số để hoàn thành:**\n\n"
            msg += "\n".join([f"{i+1}. {r[2]}" for i, (idx, r) in enumerate(pending_rows)])
            await update.message.reply_text(msg + "\n\nVí dụ: `/done 1`", parse_mode='Markdown')
            return
            
        idx = int(context.args[0]) - 1
        sheet.update_cell(pending_rows[idx][0], 4, "Done")
        await update.message.reply_text(f"✅ Xong việc: *{pending_rows[idx][1][2]}*", parse_mode='Markdown')
    except: await update.message.reply_text("❌ Nhập số thứ tự hợp lệ.")

# ==========================================================
# 5. TỰ ĐỘNG THÔNG BÁO & DỌN DẸP
# ==========================================================

async def auto_check(context: ContextTypes.DEFAULT_TYPE):
    try:
        now_str = datetime.datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
        sheet = get_sheet()
        data = sheet.get_all_values()
        
        for i, r in enumerate(data[1:], start=2):
            if len(r) >= 4 and r[3].strip().lower() == 'pending':
                if r[0].strip() == now_str:
                    await context.bot.send_message(MY_CHAT_ID, text=f"🚀 **BẮT ĐẦU:** {r[2]}\n(Dự kiến kết thúc: {r[1].split()[0]})")
                elif r[1].strip() == now_str:
                    await context.bot.send_message(MY_CHAT_ID, text=f"🏁 **HẾT GIỜ:** {r[2]}\nBạn đã hoàn thành chưa?")
    except Exception as e: logging.error(f"Lỗi quét: {e}")

async def auto_reset(context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        rows = sheet.get_all_values()
        new_rows = [rows[0]] + [r for r in rows[1:] if len(r) >= 4 and r[3].strip().lower() == 'pending']
        sheet.clear()
        sheet.update('A1', new_rows)
        await context.bot.send_message(MY_CHAT_ID, text="♻️ Hệ thống đã dọn dẹp các việc cũ.")
    except Exception as e: logging.error(f"Lỗi dọn dẹp: {e}")

async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📝 Danh sách': await list_reminders(update, context)
    elif text == '➕ Thêm nhanh': await update.message.reply_text("Gõ: `/add 08:00 - 09:00 | Nội dung`", parse_mode='Markdown')
    elif text == '⚙️ Trạng thái':
        now = datetime.datetime.now(VN_TZ).strftime("%H:%M:%S")
        await update.message.reply_text(f"🟢 Bot Online\n⏰ Giờ VN: {now}")

# ==========================================================
# 6. KHỞI CHẠY (MAIN)
# ==========================================================
if __name__ == '__main__':
    Thread(target=run_web_service, daemon=True).start()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_reminder))
    application.add_handler(CommandHandler("list", list_reminders))
    application.add_handler(CommandHandler("done", done_reminder))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))

    jq = application.job_queue
    jq.run_repeating(auto_check, interval=60, first=10)
    reset_time = datetime.time(hour=0, minute=1, tzinfo=VN_TZ)
    jq.run_daily(auto_reset, time=reset_time)

    logging.info("Bot đang khởi động...")
    application.run_polling()
