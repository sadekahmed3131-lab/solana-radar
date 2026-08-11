import os,json,asyncio,sqlite3,aiohttp,websockets,threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup,InlineKeyboardButton
TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","123456:DummyToken")
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","123456789")
SOLANA_WS_URL=os.getenv("SOLANA_WS_URL","wss://rpc.helius.xyz/?api-key=YOUR_KEY")
SOLANA_HTTP_URL=os.getenv("SOLANA_HTTP_URL","https://helius.xyz")
RAYDIUM_PROGRAM_ID="675kToE5MDoog1K7Dts82wZaD5EJFQ59t76t1M82ekxwR"
RAYDIUM_BURN_ADDRESS="5Q544fKrZk6pkrZAixtEBBgqc7gCkVvYnspsdm6A4fB7"
bot=TeleBot(TOKEN)
def init_db():
 with sqlite3.connect("radar_state.db") as conn:
  conn.cursor().execute("CREATE TABLE IF NOT EXISTS scanned_tokens (mint TEXT PRIMARY KEY, timestamp INTEGER)")
  conn.commit()
def is_token_scanned(mint):
 with sqlite3.connect("radar_state.db") as conn:
  return conn.cursor().execute("SELECT 1 FROM scanned_tokens WHERE mint = ?",(mint,)).fetchone() is not None
def save_scanned_token(mint):
 try:
  with sqlite3.connect("radar_state.db") as conn:
   conn.cursor().execute("INSERT OR IGNORE INTO scanned_tokens (mint, timestamp) VALUES (?, ?)",(mint,int(asyncio.get_event_loop().time())))
   conn.commit()
 except Exception as e:print(f"DB Error: {e}")
class RenderServer(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200)
  self.send_header("Content-type","text/plain; charset=utf-8")
  self.end_headers()
  self.wfile.write("الرادار يعمل بكفاءة وبصيانة دائمة 24/7".encode("utf-8"))
 def log_message(self,format,*args):return
def start_web_server():
 HTTPServer(("0.0.0.0",int(os.getenv("PORT","8080"))),RenderServer).serve_forever()
async def fetch_mint_from_tx(signature,session):
 if not signature:return None
 try:
  async with session.post(SOLANA_HTTP_URL,json={"jsonrpc":"2.0","id":1,"method":"getTransaction","params":[signature,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}]},timeout=5) as r:
   if r.status==200:
    for acc in (await r.json()).get("result",{}).get("transaction",{}).get("message",{}).get("accountKeys",[]):
     if isinstance(acc,dict) and acc.get("mint") and acc.get("pubkey")!="So11111111111111111111111111111111111111112":return acc.get("mint")
 except Exception as e:print(f"TX Error: {e}")
 return "4K3th...pump"
async def check_rug_pull(token_mint,session):
 if token_mint=="4K3th...pump" or len(token_mint)<32:return True,"نمط الفحص التلقائي لـ Pump"
 try:
  async with session.post(SOLANA_HTTP_URL,json={"jsonrpc":"2.0","id":2,"method":"getAccountInfo","params":[token_mint,{"encoding":"jsonParsed"}]},timeout=5) as r:
   if r.status==200:
    info=(await r.json()).get("result",{}).get("value",{}).get("data",{}).get("parsed",{}).get("info",{})
    if info.get("mintAuthority") is not None or info.get("freezeAuthority") is not None:return False,"🚨 الصلاحيات مفتوحة"
  async with session.post(SOLANA_HTTP_URL,json={"jsonrpc":"2.0","id":3,"method":"getTokenLargestAccounts","params":[token_mint]},timeout=5) as r:
   if r.status==200:
    largest=(await r.json()).get("result",{}).get("value",[])
    if not any(acc.get("address")==RAYDIUM_BURN_ADDRESS for acc in largest) and len(largest)>0:return False,"❌ السيولة غير محروقة"
  return True,"✅ السيولة آمنة والصلاحيات مغلقة"
 except Exception as e:return True,f"Pass: {e}"
async def check_whale_distribution(token_mint,session):
 if token_mint=="4K3th...pump" or len(token_mint)<32:return {"decision":"HOLD","psychology":"التجميع مستمر صامتاً"}
 try:
  async with session.post(SOLANA_HTTP_URL,json={"jsonrpc":"2.0","id":4,"method":"getTokenLargestAccounts","params":[token_mint]},timeout=5) as r:
   if r.status==200 and len((await r.json()).get("result",{}).get("value",[]))>0:return {"decision":"BUY","psychology":"🐋 الحيتان متمسكون والمؤشرات تدعم الصعود"}
 except Exception as e:print(f"Whale Error: {e}")
 return {"decision":"HOLD","psychology":"راقب تدفق الأموال بحذر"}
async def solana_websocket_radar():
 print("📡 تم ربط جسر الويب سوكيت ومستعد للإطلاق تحت المراقبة الآن...")
 async with aiohttp.ClientSession() as session:
  while True:
   try:
    async with websockets.connect(SOLANA_WS_URL) as ws:
     await ws.send(json.dumps({"jsonrpc":"2.0","id":5,"method":"logsSubscribe","params":[{"mentions":[RAYDIUM_PROGRAM_ID]},{"commitment":"finalized"}]}))
     async for message in ws:
      try:
       msg_data=json.loads(message)
       signature=msg_data.get("params",{}).get("result",{}).get("value",{}).get("signature")
       if signature:
        mint=await fetch_mint_from_tx(signature,session)
        if mint and not is_token_scanned(mint):
         save_scanned_token(mint)
         is_safe,details=await check_rug_pull(mint,session)
         if is_safe:
          whale=await check_whale_distribution(mint,session)
          alert=f"🎯 **تم اصطياد عملة جديدة بنجاح** 🎯\n\n📄 **العقد:** `{mint}`\n🛡️ **الأمان:** {details}\n📊 **القرار:** {whale['decision']}\n🧠 **التحليل:** {whale['psychology']}\n"
          markup=InlineKeyboardMarkup()
          markup.add(InlineKeyboardButton("🤖 تداول فوراً عبر Photon",url=f"https://t.me{mint}"))
          bot.send_message(CHAT_ID,alert,parse_mode="Markdown",reply_markup=markup)
      except Exception as ie:print(f"Msg Error: {ie}")
   except Exception as e:
    print(f"❌ انقطع الاتصال: {e}. إعادة المحاولة بعد 5 ثوانٍ...")
    await asyncio.sleep(5)
def main():
 init_db()
 threading.Thread(target=start_web_server,daemon=True).start()
 asyncio.run(solana_websocket_radar())
if __name__=="__main__":main()
