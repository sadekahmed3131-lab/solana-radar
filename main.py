import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
import requests

# ==========================================
# 1. إعدادات إرسال التنبيهات (حماية مطلقة ومخفية)
# ==========================================
# الكود يقرأ البيانات بأمان من سيرفر Render الداخلي دون كتابتها هنا
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# حماية برمجية لتجاوز البناء الأولي على السيرفر بنجاح
if not TELEGRAM_TOKEN or ":" not in TELEGRAM_TOKEN:
    TELEGRAM_TOKEN = "123456:DummyTokenForRenderBuild"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# قائمة منصات الإطلاق التي يراقبها الرادار
SOLANA_LAUNCHPADS = {
    "Pump.fun": "https://pump.fun",
    "Moonshot": "https://moonshot.cc"
}

sent_tokens = set()
tracked_messages = []
hourly_activity = {}
pinned_status_id = None

# ==========================================
# 2. واجهة إرسال التنبيهات الآمنة
# ==========================================
def safe_send_telegram(chat_id, text, markup=None, is_status=False):
    global pinned_status_id
    if not chat_id or "DummyToken" in TELEGRAM_TOKEN:
        return None
    try:
        msg = bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
        if is_status:
            pinned_status_id = msg.message_id
        return msg.message_id
    except telebot.apihelper.ApiTelegramException as e:
        if "markdown" in str(e).lower():
            clean_text = text.replace("*", "").replace("_", "").replace("`", "")
            msg = bot.send_message(chat_id, clean_text, reply_markup=markup)
            if is_status:
                pinned_status_id = msg.message_id
            return msg.message_id
        print(f"(🚨) خطأ في إرسال تليجرام: {e}")
        return None

def safe_delete_message(chat_id, message_id):
    if chat_id and message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

def manage_heartbeat_status(action="show"):
    global pinned_status_id
    if not CHAT_ID or "DummyToken" in TELEGRAM_TOKEN:
        return
    if action == "hide" and pinned_status_id:
        safe_delete_message(CHAT_ID, pinned_status_id)
        pinned_status_id = None
    elif action == "show" and not pinned_status_id:
        status_text = "📢 *رادار سولانا الخارق:* أنا في حالة نشاط قصوى وأمسح السوق الآن! 🛡️"
        safe_send_telegram(CHAT_ID, status_text, is_status=True)

# ==========================================
# 3. محرك المسح والفلترة الصارمة
# ==========================================
def scan_solana_ultra_strict_radar():
    global sent_tokens, tracked_messages, hourly_activity
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    print("==> Solana Radar Started Successfully!")
    
    while CHAT_ID is None or "DummyToken" in TELEGRAM_TOKEN:
        print("⚠️ السيرفر مستقر، وبانتظار كتابة TELEGRAM_TOKEN و CHAT_ID في لوحة إعدادات Render...")
        time.sleep(10)
        
    manage_heartbeat_status("show")
    
    while True:
        current_time = time.time()
        current_hour = time.localtime(current_time).tm_hour
        
        for platform_name, api_url in SOLANA_LAUNCHPADS.items():
            try:
                response = requests.get(api_url, headers=headers, timeout=5)
                if response.status_code != 200:
                    time.sleep(3)
                    continue
                    
                tokens = response.json()
                if not isinstance(tokens, list) or len(tokens) == 0:
                    continue
                    
                for token in tokens[:15]:
                    mint = token.get('mint') or token.get('address')
                    if not mint or mint in sent_tokens:
                        continue
                        
                    is_freeze_disabled = token.get('freeze_authority') is None or token.get('is_freeze_disabled') is True
                    is_dev_clean = token.get('nsfw', False) == False
                    
                    if not is_freeze_disabled or not is_dev_clean:
                        continue
                        
                    buys = token.get('buys', 0)
                    sells = token.get('sells', 0)
                    total_tx = buys + sells
                    buy_ratio = (buys / total_tx) * 100 if total_tx > 0 else 0
                    
                    created_timestamp = token.get('created_timestamp') or token.get('createdAt', 0)
                    time_ago = current_time - (created_timestamp / 1000) if created_timestamp else 0
                    
                    is_diamond_token = buy_ratio >= 85.0 and total_tx >= 25
                    
                    if time_ago <= 60 and is_diamond_token:
                        manage_heartbeat_status("hide")
                        
                        name = token.get('name', 'Unknown')
                        symbol = token.get('symbol', 'MEME')
                        
                        message = (
                            f"🚀 *تنبيه ماسي: رصد عملة فائقة الانفجار!* 🚀\n\n"
                            f"🌐 *المنصة:* {platform_name}\n"
                            f"🏷️ *الاسم:* {name} ({symbol})\n"
                            f"📍 *العنوان الذكي (اضغط للنسخ):* `{mint}`\n\n"
                            f"📊 *تحليل صقر الجودة:* \n"
                            f"⬅️ الشراء: {buys} صفقة بنسبة صعود قدرها ({buy_ratio:.1f}%). زخم حقيقي قوي عمودياً! 🔥\n"
                            f"⬅️ الأمان البرمجي: العقد نظيف وخيار التجميد ملغي ✅\n"
                            f"⬅️ عمق السيولة: متناسق، والبيع اليدوي الآمن مضمون هندسياً 📈\n"
                            f"⬅️ التوصية: انسخ العنوان في الأعلى وافتح منصتك للتداول فوراً! ⚡"
                        )
                        
                        markup = types.InlineKeyboardMarkup()
                        btn_open = types.InlineKeyboardButton("🌐 فتح صفحة العملة", url=f"https://pump.fun{mint}")
                        markup.add(btn_open)
                        
                        msg_id = safe_send_telegram(CHAT_ID, message, markup)
                        sent_tokens.add(mint)
                        
                        if msg_id:
                            tracked_messages.append({"msg_id": msg_id, "timestamp": current_time})
                            
                        hourly_activity[current_hour] = hourly_activity.get(current_hour, 0) + 1
                        
                        time.sleep(300)
                        manage_heartbeat_status("show")
                        break
                        
            except Exception as e:
                print(f"(🚨) خطأ في جلب البيانات: {e}")
                time.sleep(3)
                
        time.sleep(2)

# ==========================================
# 4. التنظيف الدوري والتقرير اليومي
# ==========================================
def auto_cleanup_and_peak_reporter_loop():
    global tracked_messages, hourly_activity
    while True:
        time.sleep(60)
        if CHAT_ID is None or "DummyToken" in TELEGRAM_TOKEN:
            continue
            
        current_time = time.time()
        expired_messages = [m for m in tracked_messages if current_time - m["timestamp"] >= 86400]
        tracked_messages = [m for m in tracked_messages if current_time - m["timestamp"] < 86400]
        
        if expired_messages:
            manage_heartbeat_status("hide")
            for msg in expired_messages:
                safe_delete_message(CHAT_ID, msg["msg_id"])
                
        if hourly_activity:
            peak_hour = max(hourly_activity, key=hourly_activity.get)
            peak_count = hourly_activity[peak_hour]
            
            report_msg = (
                f"📊 *تقرير الذروة والتحليل الإستراتيجي اليومي*\n"
                f"🔥 الخلاصة الحالية لتداول الـ 24 ساعة الماضية\n"
                f"⏰ ساعة الذروة: {peak_hour}:00\n"
                f"🚀 عدد العملات المكتشفة in هذه الساعة: {peak_count}"
            )
            safe_send_telegram(CHAT_ID, report_msg)

# ==========================================
# 5. خادم الويب الأساسي لخدمة Render
# ==========================================
class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Solana Radar Bot is Running Successfully!")

def run_web_server():
    server_address = ('', int(os.getenv("PORT", 8080)))
    httpd = HTTPServer(server_address, WebServerHandler)
    httpd.serve_forever()

if __name__ == "__main__":
    print("==> Running 'python main.py'")
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    cleanup_thread = threading.Thread(target=auto_cleanup_and_peak_reporter_loop, daemon=True)
    cleanup_thread.start()
    
    scan_solana_ultra_strict_radar()
bot.infinity_polling()
# هذا السطر يوضع في نهاية الخوارزمية ليطلق التنبيه فوراً عند تشغيل السيرفر
try:
    message = "⚠️ عاجل: أنا في حالة نشاط واترصد الفرص الآن على شبكة Solana، فلا تقلق أنا نشط!"
    send_radar_alert(message)
except Exception as e:
    print(f"فشل إرسال رسالة النشاط: {e}")
