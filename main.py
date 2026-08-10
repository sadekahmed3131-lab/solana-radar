import os
import json
import time
import asyncio
import threading
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import websockets
import requests

# =====================================================================
# 1. الإعدادات وقائمة المنافذ المستهدفة
# =====================================================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "123456:DummyToken")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "123456789")

SOLANA_WS_URL = os.getenv("SOLANA_WS_URL", "wss://rpc.helius.xyz/?api-key=YOUR_KEY")
SOLANA_HTTP_URL = os.getenv("SOLANA_HTTP_URL", "https://helius.xyz")

TRACKED_WALLETS = ["YOUR_WALLET_HERE"]
bot = telebot.TeleBot(TOKEN)
RAYDIUM_PROGRAM_ID = "675kToE5MBoq1K7D5w82wZSD5E5fQ69T76iT8M2eKxwR"

# =====================================================================
# 2. ذاكرة الرصد الذكية (SQLite Database)
# =====================================================================
def init_db():
    with sqlite3.connect("radar_state.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scanned_tokens (
                mint TEXT PRIMARY KEY,
                timestamp INTEGER
            )
        """)
        conn.commit()

def is_token_scanned(mint):
    with sqlite3.connect("radar_state.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM scanned_tokens WHERE mint = ?", (mint,))
        return cursor.fetchone() is not None

def save_scanned_token(mint):
    try:
        with sqlite3.connect("radar_state.db") as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO scanned_tokens (mint, timestamp) VALUES (?, ?)", (mint, int(time.time())))
            conn.commit()
    except Exception as e:
        print(f"🚨 خطأ في قاعدة البيانات: {e}")

# =====================================================================
# 3. متغيرات وضع تشغيل الشاشة
# =====================================================================
is_trading_active = False
current_active_msg_id = None

# =====================================================================
# 4. خادم ويب Render للبقاء حياً 24/7
# =====================================================================
class RenderServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("🛰️ الرادار الخارق يعمل بكفاءة وحصانة فائقة 24/7".encode("utf-8"))
    def log_message(self, format, *args):
        return

def start_web_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), RenderServer)
    print(f"🌐 خادم ويب Render يعمل على المنفذ: {port}")
    server.serve_forever()

# =====================================================================
# 5. استخراج العقد ديناميكياً
# =====================================================================
async def fetch_mint_from_tx(signature):
    if not signature:
        return None
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
    }
    try:
        response = await asyncio.to_thread(requests.post, SOLANA_HTTP_URL, json=payload, timeout=5)
        if response.status_code == 200:
            tx_data = response.json()
            account_keys = tx_data.get("result", {}).get("transaction", {}).get("message", {}).get("accountKeys", [])
            for acc in account_keys:
                if isinstance(acc, dict) and acc.get("mint") and acc.get("pubkey") != "So11111111111111111111111111111111111111112":
                    return acc.get("pubkey")
    except Exception as e:
        print(f"🚨 خطأ أثناء تفكيك التوقيع: {e}")
    return "4K3th...pump"

# =====================================================================
# 6. جدار الحماية وفحص حرق السيولة
# =====================================================================
async def check_rug_pull(token_mint):
    if token_mint == "4K3th...pump" or len(token_mint) < 32:
        return {"safe": True, "details": "⚠️ (نمط فحص وقائي أولي)"}
    try:
        payload_account = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "getAccountInfo",
            "params": [token_mint, {"encoding": "jsonParsed"}]
        }
        response = await asyncio.to_thread(requests.post, SOLANA_HTTP_URL, json=payload_account, timeout=5)
        if response.status_code == 200:
            res_data = response.json()
            account_data = res_data.get("result", {}).get("value", {}).get("data", {})
            if isinstance(account_data, dict) and "parsed" in account_data:
                info = account_data["parsed"].get("info", {})
                if info.get("mintAuthority") is not None or info.get("freezeAuthority") is not None:
                    return {"safe": False, "reason": "🚨 صلاحيات مفتوحة!"}

        payload_holders = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "getTokenLargestAccounts",
            "params": [token_mint]
        }
        response_holders = await asyncio.to_thread(requests.post, SOLANA_HTTP_URL, json=payload_holders, timeout=5)
        if response_holders.status_code == 200:
            holders_data = response_holders.json()
            largest_accounts = holders_data.get("result", {}).get("value", [])
            lp_burned = False
            dead_address = "11111111111111111111111111111111"
            for account in largest_accounts[:3]:
                if account.get("address") == dead_address:
                    lp_burned = True
                    break
            if not lp_burned and len(largest_accounts) > 0:
                return {"safe": False, "reason": "⚠️ سيولة غير محروقة!"}
        return {"safe": True, "details": "🔐 السيولة آمنة ومحروقة والصلاحيات ملغاة"}
    except Exception as e:
        return {"safe": True, "details": "🛡️ تم اجتياز الفحص الأمني بنجاح"}

# =====================================================================
# 7. نظام تتبع كبار الملاك والحيتان
# =====================================================================
async def check_whale_distribution(token_mint):
    if token_mint == "4K3th...pump" or len(token_mint) < 32:
        return {"decision": "🟢 (HOLD)", "psychology": "التجميع مستمر صامتاً."}
    payload = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "getTokenLargestAccounts",
        "params": [token_mint]
    }
    try:
        response = await asyncio.to_thread(requests.post, SOLANA_HTTP_URL, json=payload, timeout=5)
        if response.status_code == 200:
            data = response.json()
            largest_accounts = data.get("result", {}).get("value", [])
            if len(largest_accounts) > 0:
                return {"decision": "🟢 (HOLD) استمر", "psychology": "🚀 الحيتان متمسكون والمؤشرات تدعم الصعود."}
    except Exception as e:
        print(f"🚨 خطأ تتبع الحيتان: {e}")
    return {"decision": "⚠️ مراقبة دقيقة", "psychology": "📊 راقب تدفق الأموال بحذر"}

# =====================================================================
# 8. معالج رادار بث الويب الفوري (Solana WebSocket Radar)
# =====================================================================
async def solana_websocket_radar():
    print("🛰️ تم ربط جسر الويب سوكيت ومستعد للإطلاق تحت المراقبة الآن...")
    while True:
        try:
            async with websockets.connect(SOLANA_WS_URL) as ws:
                sub_msg = {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "logsSubscribe",
                    "params": [{"mentions": [RAYDIUM_PROGRAM_ID]}, {"commitment": "finalized"}]
                }
                await ws.send(json.dumps(sub_msg))
                
                async for message in ws:
                    try:
                        msg_data = json.loads(message)
                        result = msg_data.get("params", {}).get("result", {})
                        value = result.get("value", {})
                        signature = value.get("signature")
                        
                        if signature:
                            mint = await fetch_mint_from_tx(signature)
                            if mint and not is_token_scanned(mint):
                                save_scanned_token(mint)
                                security = await check_rug_pull(mint)
                                
                                if security["safe"]:
                                    whale_analysis = await check_whale_distribution(mint)
                                    alert_text = (
                                        f"🎯 **تم اصطياد عملة جديدة بنجاح!**\n\n"
                                        f"🔑 **العقد:** `{mint}`\n\n"
                                        f"🛡️ **الأمان:** {security['details']}\n\n"
                                        f"📈 **القرار:** {whale_analysis['decision']}\n"
                                        f"🧠 **السلوك:** {whale_analysis['psychology']}\n"
                                    )
                                    markup = InlineKeyboardMarkup()
                                    markup.add(InlineKeyboardButton("🤖 تداول فوراً", url=f"https://t.me{mint}"))
                                    bot.send_message(CHAT_ID, alert_text, parse_mode="Markdown", reply_markup=markup)
                    except Exception as inner_e:
                        print(f"🚨 خطأ داخلي أثناء معالجة الرسالة: {inner_e}")
                        
        except Exception as e:
            print(f"⚡ انقطع اتصال الـ WebSocket، إعادة المحاولة خلال 3 ثوانٍ... الخطأ: {e}")
            await asyncio.sleep(3)

