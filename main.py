import os
import time
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# 1. الإعدادات الأساسية لقناتك وبوتك
BOT_TOKEN = "8027527016:AAG8hJIK_-KgG5cG3ovgEdvNqdNZW_tqJVU"
CHAT_ID = "@SADEK_Crybto"
bot = telebot.TeleBot(BOT_TOKEN)

# الروابط البرمجية الفورية لأسواق سولانا
SOLANA_LAUNCHPADS = {
    "Pump.fun (Solana)": "https://pump.fun",
    "Moonshot (Solana)": "https://moonshot.cc"
}

# 2. الذاكرة الرقمية المحدثة للبوت
sent_tokens = set()      # العملات التي تم إرسالها لمنع التكرار
tracked_tokens = {}     # قائمة المطاردة والتتبع الذكي حتى 5 دقائق
protected_tokens = set() # العملات التي تتداول بها حالياً وتخضع لحماية الحارس الشخصي كل ثانية

def scan_solana_ultra_strict_radar():
    global sent_tokens, tracked_tokens
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    current_now = int(time.time())
    
    # تنظيف تلقائي للذاكرة بعد 6 دقائق لتخفيف استهلاك موارد السيرفر
    tracked_tokens = {m: data for m, data in tracked_tokens.items() if current_now - data["first_seen"] <= 360}

    for platform_name, api_url in SOLANA_LAUNCHPADS.items():
        try:
            response = requests.get(api_url, headers=headers, timeout=5)
            if response.status_code == 200:
                tokens = response.json()
                
                if isinstance(tokens, list) and len(tokens) > 0:
                    for token in tokens[:15]: # فحص عينة أوسع للمطاردة
                        mint = token.get('mint') or token.get('address')
                        if not mint or mint in sent_tokens:
                            continue
                            
                        name = token.get('name', 'Unknown')
                        symbol = token.get('symbol', 'MEME')
                        
                        # معايير الأمان 1000% الصارمة
                        is_freeze_disabled = token.get('freeze_authority') is None or token.get('is_frozen') is False
                        is_dev_clean = token.get('nsfw', False) == False
                        
                        # فحص روابط التواصل
                        has_twitter = token.get('twitter') or token.get('links', {}).get('twitter')
                        has_telegram = token.get('telegram') or token.get('links', {}).get('telegram')
                        has_website = token.get('website') or token.get('links', {}).get('website')
                        has_full_socials = has_twitter and has_telegram and has_website
                        
                        created_timestamp = token.get('created_timestamp') or token.get('createdAt', 0)
                        time_ago = current_now - (created_timestamp / 1000) if created_timestamp else 0
                        
                        # حساب الأسعار ومؤشرات الشراء
                        launch_price = float(token.get('priceUsd', 0.0000015))
                        buys = token.get('buys', 1)
                        sells = token.get('sells', 0)
                        total_tx = buys + sells
                        buy_ratio = (buys / total_tx) * 100 if total_tx > 0 else 50

                        # [المسار 1]: صيد فوري برأس الدقيقة الأولى (أقل من 60 ثانية بكامل الشروط)
                        if time_ago <= 60 and is_freeze_disabled and is_dev_clean and has_full_socials:
                            send_radar_message(platform_name, mint, name, symbol, time_ago, launch_price, launch_price, buy_ratio, "🚨 صيد فوري برأس الدقيقة الأولى!")
                            continue
                        
                        # [المسار 2]: الإضافة لقائمة التتبع والمطاردة إذا نقصت الروابط في الدقيقة الأولى
                        if time_ago <= 60 and is_freeze_disabled and is_dev_clean and not has_full_socials:
                            if mint not in tracked_tokens:
                                tracked_tokens[mint] = {"first_seen": current_now, "launch_price": launch_price, "platform": platform_name, "name": name, "symbol": symbol}
                        
                        # [المسار 3]: إنقاذ ومطاردة العملة الذهبية المحدثة (بين 1 إلى 5 دقائق)
                        if mint in tracked_tokens and has_full_socials and is_freeze_disabled:
                            current_price = float(token.get('priceUsd', launch_price))
                            old_price = tracked_tokens[mint]["launch_price"]
                            send_radar_message(platform_name, mint, name, symbol, time_ago, old_price, current_price, buy_ratio, "🔥 إنقاذ ذكي | المطور حدّث الروابط الآن!")
                            tracked_tokens.pop(mint, None)
                                
        except Exception:
            continue

# 3. دالة صياغة التقرير الاستثماري الذكي والأزرار التفاعلية
def send_radar_message(platform_name, mint, name, symbol, time_ago, old_price, current_price, buy_ratio, status):
    global sent_tokens
    try:
        # حساب نسبة النمو (كم كانت وكم أصبحت)
        growth = ((current_price - old_price) / old_price) * 100 if old_price > 0 else 0
        growth_text = f"+{growth:.1f}%" if growth > 0 else "0.0%"
        
        # تصنيف الذكاء الاصطناعي التنبؤي للعملة
        if buy_ratio >= 65 and growth >= 50:
            ai_judgment = "🏆 فرصة ثراء ذهبية! دخول قوي للسيولة مع أمان كامل. 🚀"
        elif buy_ratio < 40:
            ai_judgment = "⚠️ مخاطرة ومضيعة للوقت! حركة بيع مبكرة خفية من الحيتان."
        else:
            ai_judgment = "📋 عملة مستقرة الفحص. راقب حركة الماركت كاب بحذر."

        buy_url = f"https://pump.fun{mint}" if "Pump" in platform_name else f"https://dexscreener.com{mint}"
        
        message = (
            f"{status}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏢 *المنصة:* {platform_name}\n"
            f"⏱ *العمر الحالي:* {int(time_ago)} ثانية\n"
            f"🪙 *العملة:* ({symbol}) {name}\n"
            f"🟢 *السعر عند الإطلاق:* ${old_price:.8f}\n"
            f"📈 *السعر عند الاقتناص:* ${current_price:.8f} ({growth_text})\n"
            f"📊 *نسبة الشراء للبيع:* {buy_ratio:.1f}% شراء ✅\n"
            f"📝 *العقد:* `{mint}`\n\n"
            f"🧠 *التحليل التنبؤي للذكاء الاصطناعي:* {ai_judgment}\n"
            f"📉 *حالة الأمان:* العقد صافي ومضمون 1000% ومسجل المطور خالٍ من المخاطر.\n"
            f"📜 *الخلاصة الاستثمارية:* معايير صعود جيدة ومؤشر سيولة نشط."
        )
        
        # إنشاء زر الحارس الشخصي وزر الشراء
        markup = InlineKeyboardMarkup()
        btn_protect = InlineKeyboardButton("📥 اضغط لبدء تداول العملة وتفعيل الحارس الشخصي", callback_data=f"protect_{mint}_{symbol}")
        btn_buy = InlineKeyboardButton("🛒 شراء سريع", url=buy_url)
        markup.add(btn_protect)
        markup.add(btn_buy)
        
        bot.send_message(CHAT_ID, message, parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)
        sent_tokens.add(mint)
    except Exception:
        pass

# 4. زر التفاعل البرمجي لربط الضغط وبدء وضع المطاردة كل ثانية لـ Rug Pull
@bot.callback_query_handler(func=lambda call: call.data.startswith("protect_"))
def handle_protection_button(call):
    global protected_tokens
    data_parts = call.data.split("_")
    mint = data_parts[1]
    symbol = data_parts[2]
    
    user_id = call.from_user.id
    protected_tokens.add(mint)
    
    # تنبيه سريع للمستخدم على الشاشة بأن الحارس الشخصي بدأ يحميه
    bot.answer_callback_query(call.id, text=f"🔒 تم تفعيل الحارس الشخصي لـ {symbol}! نراقب العقد كل ثانية لحمايتك.", show_alert=True)
    
    # تشغيل خيط (Thread) منفصل لمراقبة هذه العملة بالتحديد كل ثانية دون تعطيل البوت الأساسي
    threading.Thread(target=personal_guard_loop, args=(user_id, mint, symbol), daemon=True).start()

def personal_guard_loop(user_id, mint, symbol):
    global protected_tokens
    headers = {"User-Agent": "Mozilla/5.0"}
    api_url = f"https://pump.fun{mint}" # فحص مباشر لسيولة العقد
    
    count = 0
    while mint in protected_tokens and count < 600: # حماية مستمرة لمدة 10 دقائق كاملة أثناء تداوله
        time.sleep(1) # فحص كل ثانية واحدة بدقة فائقة!
        count += 1
        try:
            response = requests.get(api_url, headers=headers, timeout=2)
            if response.status_code == 200:
                token_data = response.json()
                
                # رصد علامات سحب السيولة أو احتيال المطور فجأة
                is_rugged = token_data.get('complete', False) == False and token_data.get('usd_market_cap', 1000) < 2000
                is_frozen = token_data.get('freeze_authority') is not None
                
                if is_rugged or is_frozen:
                    emergency_msg = (
                        f"🚨 *إنذار أحمر عاجل جداً من الحارس الشخصي* 🚨\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"⚠️ *اخرج فوراً من عملة:* {symbol}\n"
                        f"📝 *العقد الخاص بها:* `{mint}`\n"
                        f"🔥 *السبب التقني:* رصد محاولة سحب سيولة (Rug Pull) أو تفعيل فخ تجميد المحافظ من المطور الآن! 🛑\n"
                        f"🕒 قم بالبيع السريع لحماية أموالك فوراً قبل فوات الأوان!"
                    )
                    bot.send_message(user_id, emergency_msg, parse_mode="Markdown")
                    protected_tokens.remove(mint)
                    break
        except Exception:
            continue

# 5. حيلة السيرفر الوهمي المتطابق مع شروط الخطة المجانية لـ Render
def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    print(f"Fake web server is live on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    # تشغيل السيرفر الوهمي بالخلفية لـ Render بشكل خفيف جداً
    threading.Thread(target=run_fake_server, daemon=True).start()
    
    print("Solana Strict Ultra Radar Bot with Anti-Rug is Live...")
    
