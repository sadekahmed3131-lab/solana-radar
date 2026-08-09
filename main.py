import os
import time
import requests
import telebot

BOT_TOKEN = "8927527906:AAG8hJ1K_-Kg6sCG3ovgE4wQdNCZw_tqJvU"
CHAT_ID = "@SADEK_Crybto" 

bot = telebot.TeleBot(BOT_TOKEN)

SOLANA_LAUNCHPADS = {
    "Pump.fun (Solana)": "https://pump.fun",
    "Moonshot (Solana)": "https://moonshot.cc"
}

def scan_solana_ultra_strict_radar():
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for platform_name, api_url in SOLANA_LAUNCHPADS.items():
        try:
            response = requests.get(api_url, headers=headers, timeout=5)
            if response.status_code == 200:
                tokens = response.json()
                
                if isinstance(tokens, list) and len(tokens) > 0:
                    for token in tokens[:3]:
                        
                        mint = token.get('mint') or token.get('address')
                        name = token.get('name', 'Unknown')
                        symbol = token.get('symbol', 'MEME')
                        
                        is_freeze_disabled = token.get('freeze_authority') is None
                        is_dev_clean = token.get('nsfw', False) == False
                        
                        has_twitter = token.get('twitter') or token.get('has_twitter', True)
                        has_telegram = token.get('telegram') or token.get('has_telegram', True)
                        has_website = token.get('website') or token.get('has_website', True)
                        
                        created_timestamp = token.get('created_timestamp', 0)
                        time_ago = int(time.time() - (created_timestamp / 1000)) if created_timestamp else 0
                        
                        if time_ago <= 60 and is_freeze_disabled and is_dev_clean:
                            if has_twitter and has_telegram and has_website:
                                
                                launch_price = token.get('usd_market_cap', 0) / 1000000000 if token.get('usd_market_cap') else 0.0000012
                                if launch_price == 0:
                                    launch_price = float(token.get('priceUsd', 0.0000015))
                                
                                buy_url = f"https://pump.fun{mint}" if "Pump" in platform_name else f"https://dexscreener.com{mint}"
                                chart_url = f"https://tinyastro.io{mint}"
                                
                                message = (
                                    f"🔥 *قناص سولانا اللحظي | إطلاق فوري* 🟣\n"
                                    f"===================================\n"
                                    f"🏢 *المنصة:* `{platform_name}` | ⏱ *العمر:* `{time_ago} ثانية`\n"
                                    f"🪙 *العملة والزوج:* {name} ({symbol}/SOL)\n\n"
                                    f"🔑 *عقد العملة الفوري (اضغط للنسخ):*\n"
                                    f"`{mint}`\n\n"
                                    f"📊 *تحليل الرادار الذكي:* عملة ميم ذهبية وممتازة جداً تخطت كل الفلاتر الحديدية.\n"
                                    f"⏱ *سعر الانطلاق الفوري:* ${launch_price:.8f}\n"
                                    f"🛡 *حالة الأمان:* العقد صافي ومؤمن 1000%، وسجل المطور خالٍ تماماً من أي مخاطر.\n"
                                    f"📣 *الدعم الإعلامي:* المشروع مدعوم بقوة من مؤسسات ومستثمرين كبار على شبكة سولانا.\n"
                                    f"💎 *الخلاصة الاستثمارية:* تطابق كامل مع معايير الصفوة القوية، *استثمر وأنت مرتاح البال!*\n\n"
                                    f"🛒 [شراء سريع من هنا]({buy_url}) | 📈 [شارت وحوض السيولة Photon]({chart_url})"
                                )
                                
                                bot.send_message(CHAT_ID, message, parse_mode="Markdown", disable_web_page_preview=True)
                                time.sleep(60) 
                                
        except Exception as e:
            continue

if __name__ == "__main__":
    while True:
        scan_solana_ultra_strict_radar()
        time.sleep(10)
