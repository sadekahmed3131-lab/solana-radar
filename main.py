import os
import json
import time
import asyncio
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp
import websockets
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton


# ============================================================
# SOLANA RADAR
# Gold / Diamond / Whale Support / Live Guardian
# Monitoring only - NO automatic trading
# ============================================================

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

SOLANA_HTTP_URL = os.environ.get(
    "SOLANA_HTTP_URL",
    "https://api.mainnet-beta.solana.com"
).strip()

SOLANA_WS_URL = os.environ.get(
    "SOLANA_WS_URL",
    "wss://api.mainnet-beta.solana.com"
).strip()

RAYDIUM_PROGRAM_ID = os.environ.get(
    "RAYDIUM_PROGRAM_ID",
    "675k1v2wPyEaAC6fGgFiTMvU5khRfw731gCxnhcnKC7m"
).strip()

DEX_API = "https://api.dexscreener.com/latest/dex/tokens/{}"

MIN_LIQUIDITY = float(
    os.environ.get("MIN_LIQUIDITY_USD", "15000")
)

MIN_VOLUME_5M = float(
    os.environ.get("MIN_VOLUME_5M_USD", "2500")
)

MIN_GOLD_SCORE = float(
    os.environ.get("MIN_GOLD_SCORE", "72")
)

MIN_DIAMOND_SCORE = float(
    os.environ.get("MIN_DIAMOND_SCORE", "88")
)

GUARDIAN_INTERVAL = int(
    os.environ.get("GUARDIAN_INTERVAL", "5")
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("SOLANA_RADAR")


# ============================================================
# VALIDATION
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is missing"
    )

if not CHAT_ID:
    raise RuntimeError(
        "CHAT_ID is missing"
    )


# ============================================================
# TELEGRAM BOT
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="Markdown"
)


# ============================================================
# GLOBAL STATE
# ============================================================

radar_active = True

position_active = False
position_mint = None
position_entry_price = None
position_message_id = None

event_loop = None
http_session = None

seen_signatures = set()
seen_mints = set()

candidates = {}

event_history = deque(maxlen=5000)

daily_stats = {
    "events": 0,
    "gold": 0,
    "diamond": 0,
    "danger": 0,
    "last_date": datetime.now(timezone.utc).date()
}

hourly_activity = [0] * 24


# ============================================================
# DATA MODEL
# ============================================================

@dataclass
class TokenSnapshot:

    mint: str

    symbol: str = "UNKNOWN"

    name: str = "Unknown"

    price: float = 0.0

    liquidity: float = 0.0

    volume_5m: float = 0.0

    buys_5m: int = 0

    sells_5m: int = 0

    price_change_5m: float = 0.0

    pair_address: str = ""

    dex_id: str = ""

    url: str = ""

    raw: dict = field(
        default_factory=dict
    )


@dataclass
class Candidate:

    snapshot: TokenSnapshot

    security_score: float

    market_score: float

    behavior_score: float

    final_score: float

    whale_score: float

    status: str

    evidence: list = field(
        default_factory=list
    )

    warnings: list = field(
        default_factory=list
    )

    created_at: float = field(
        default_factory=time.time
    )


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    )


def current_hour():
    return utc_now().hour


def reset_daily_stats():

    today = utc_now().date()

    if today != daily_stats["last_date"]:

        daily_stats["events"] = 0
        daily_stats["gold"] = 0
        daily_stats["diamond"] = 0
        daily_stats["danger"] = 0

        for i in range(24):
            hourly_activity[i] = 0

        daily_stats["last_date"] = today


# ============================================================
# FORMATTERS
# ============================================================

def money(value):

    try:
        value = float(value)
    except Exception:
        return "$0"

    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"

    if value >= 1_000:
        return f"${value / 1_000:.1f}K"

    if value >= 1:
        return f"${value:.4f}"

    return f"${value:.8f}"


def percent(value):

    try:
        return f"{float(value):+.2f}%"
    except Exception:
        return "0.00%"


def short_address(address):

    if not address:
        return "غير معروف"

    if len(address) <= 14:
        return address

    return (
        address[:7]
        + "..."
        + address[-7:]
    )


# ============================================================
# TELEGRAM HELPERS
# ============================================================

async def send_message(
    text,
    reply_markup=None
):

    try:

        return await asyncio.to_thread(
            bot.send_message,
            CHAT_ID,
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

    except Exception as exc:

        logger.warning(
            "Telegram send error: %s",
            exc
        )

        return None


async def edit_message(
    message_id,
    text,
    reply_markup=None
):

    try:

        await asyncio.to_thread(
            bot.edit_message_text,
            text,
            chat_id=CHAT_ID,
            message_id=message_id,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

    except Exception as exc:

        logger.debug(
            "Telegram edit error: %s",
            exc
        )


# ============================================================
# SOLANA RPC
# ============================================================

async def rpc_request(
    method,
    params
):

    global http_session

    if http_session is None:

        http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=15
            )
        )

    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000),
        "method": method,
        "params": params
    }

    for attempt in range(3):

        try:

            async with http_session.post(
                SOLANA_HTTP_URL,
                json=payload
            ) as response:

                if response.status != 200:

                    raise RuntimeError(
                        f"RPC HTTP {response.status}"
                    )

                result = await response.json()

                if result.get("error"):

                    raise RuntimeError(
                        str(result["error"])
                    )

                return result.get("result")

        except Exception as exc:

            if attempt == 2:

                logger.warning(
                    "RPC error: %s",
                    exc
                )

            await asyncio.sleep(
                1 + attempt
            )

    return None


async def get_transaction(
    signature
):

    return await rpc_request(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    )


# ============================================================
# DEXSCREENER MARKET DATA
# ============================================================

async def fetch_market_data(
    mint
):

    global http_session

    if http_session is None:

        http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=10
            )
        )

    try:

        url = DEX_API.format(
            mint
        )

        async with http_session.get(
            url
        ) as response:

            if response.status != 200:

                return None

            data = await response.json()

        pairs = data.get(
            "pairs"
        ) or []

        solana_pairs = [

            pair

            for pair in pairs

            if pair.get("chainId")
            == "solana"

        ]

        if not solana_pairs:

            return None

        pair = max(

            solana_pairs,

            key=lambda x: float(
                (
                    x.get("liquidity")
                    or {}
                ).get("usd")
                or 0
            )

        )

        base = (
            pair.get("baseToken")
            or {}
        )

        liquidity = (
            pair.get("liquidity")
            or {}
        )

        volume = (
            pair.get("volume")
            or {}
        )

        transactions = (
            pair.get("txns")
            or {}
        )

        five_minutes = (
            transactions.get("m5")
            or {}
        )

        changes = (
            pair.get("priceChange")
            or {}
        )

        try:
            price = float(
                pair.get("priceUsd")
                or 0
            )
        except Exception:
            price = 0.0

        return TokenSnapshot(

            mint=mint,

            symbol=str(
                base.get("symbol")
                or "UNKNOWN"
            ),

            name=str(
                base.get("name")
                or "Unknown"
            ),

            price=price,

            liquidity=float(
                liquidity.get("usd")
                or 0
            ),

            volume_5m=float(
                volume.get("m5")
                or 0
            ),

            buys_5m=int(
                five_minutes.get("buys")
                or 0
            ),

            sells_5m=int(
                five_minutes.get("sells")
                or 0
            ),

            price_change_5m=float(
                changes.get("m5")
                or 0
            ),

            pair_address=str(
                pair.get("pairAddress")
                or ""
            ),

            dex_id=str(
                pair.get("dexId")
                or ""
            ),

            url=str(
                pair.get("url")
                or ""
            ),

            raw=pair
        )

    except Exception as exc:

        logger.debug(
            "DEX lookup failed for %s: %s",
            short_address(mint),
            exc
        )

        return None


# ============================================================
# SECURITY FILTER
# ============================================================

def security_analysis(
    snapshot
):

    score = 50.0

    evidence = []

    warnings = []

    if snapshot.liquidity >= 50_000:

        score += 25

        evidence.append(
            "السيولة قوية"
        )

    elif snapshot.liquidity >= MIN_LIQUIDITY:

        score += 15

        evidence.append(
            "السيولة مقبولة"
        )

    else:

        score -= 30

        warnings.append(
            "السيولة ضعيفة"
        )

    if snapshot.volume_5m >= 25_000:

        score += 15

        evidence.append(
            "حجم تداول قوي"
        )

    elif snapshot.volume_5m >= MIN_VOLUME_5M:

        score += 8

        evidence.append(
            "حجم تداول مقبول"
        )

    else:

        score -= 15

        warnings.append(
            "حجم التداول ضعيف"
        )

    if (
        snapshot.buys_5m
        + snapshot.sells_5m
        >= 10
    ):

        score += 10

        evidence.append(
            "نشاط تداول واضح"
        )

    else:

        score -= 10

        warnings.append(
            "نشاط التداول منخفض"
        )

    return (
        max(0, min(100, score)),
        evidence,
        warnings
    )


# ============================================================
# MARKET ANALYSIS
# ============================================================

def market_analysis(
    snapshot
):

    score = 50.0

    evidence = []

    warnings = []

    total = (
        snapshot.buys_5m
        + snapshot.sells_5m
    )

    if total > 0:

        buy_ratio = (
            snapshot.buys_5m
            / total
        )

        if buy_ratio >= 0.65:

            score += 25

            evidence.append(
                "ضغط شراء قوي"
            )

        elif buy_ratio >= 0.55:

            score += 15

            evidence.append(
                "ضغط شراء إيجابي"
            )

        elif buy_ratio <= 0.35:

            score -= 25

            warnings.append(
                "ضغط بيع مرتفع"
            )

    if snapshot.price_change_5m > 0:

        score += 10

        evidence.append(
            "زخم سعري إيجابي"
        )

    if snapshot.price_change_5m <= -10:

        score -= 25

        warnings.append(
            "هبوط سعري حاد"
        )

    if snapshot.price_change_5m >= 100:

        score -= 10

        warnings.append(
            "ارتفاع قصير شديد يحتاج حذرًا"
        )

    return (
        max(0, min(100, score)),
        evidence,
        warnings
    )


# ============================================================
# BEHAVIOR ANALYSIS
# ============================================================

def behavior_analysis(
    snapshot
):

    score = 50.0

    evidence = []

    warnings = []

    if (
        snapshot.buys_5m
        > snapshot.sells_5m
    ):

        score += 20

        evidence.append(
            "المشترون أقوى حاليًا"
        )

    if (
        snapshot.sells_5m
        > snapshot.buys_5m * 1.5
    ):

        score -= 25

        warnings.append(
            "البيع أسرع من الشراء"
        )

    if (
        snapshot.liquidity > 0
        and snapshot.volume_5m
        > snapshot.liquidity
    ):

        warnings.append(
            "حركة تداول كبيرة مقارنة بالسيولة"
        )

        score -= 10

    return (
        max(0, min(100, score)),
        evidence,
        warnings
    )


# ============================================================
# WHALE SUPPORT
# ============================================================

def whale_analysis(
    snapshot
):

    score = 0.0

    evidence = []

    if (
        snapshot.liquidity >= 100_000
    ):

        score += 25

        evidence.append(
            "سيولة كبيرة"
        )

    if (
        snapshot.volume_5m >= 50_000
    ):

        score += 25

        evidence.append(
            "حجم تداول كبير"
        )

    if (
        snapshot.buys_5m >= 30
        and snapshot.buys_5m
        > snapshot.sells_5m
    ):

        score += 30

        evidence.append(
            "نشاط شراء كبير ومتكرر"
        )

    if (
        snapshot.price_change_5m > 0
        and snapshot.buys_5m
        > snapshot.sells_5m
    ):

        score += 20

        evidence.append(
            "الدعم الشرائي مستمر"
        )

    return (
        min(100, score),
        evidence
    )


# ============================================================
# GOLD / DIAMOND FILTER
# ============================================================

def analyze_token(
    snapshot
):

    security_score, sec_evidence, sec_warnings = (
        security_analysis(
            snapshot
        )
    )

    market_score, market_evidence, market_warnings = (
        market_analysis(
            snapshot
        )
    )

    behavior_score, behavior_evidence, behavior_warnings = (
        behavior_analysis(
            snapshot
        )
    )

    final_score = (

        security_score * 0.45

        + market_score * 0.35

        + behavior_score * 0.20

    )

    warnings = list(
        dict.fromkeys(
            sec_warnings
            + market_warnings
            + behavior_warnings
        )
    )

    evidence = list(
        dict.fromkeys(
            sec_evidence
            + market_evidence
            + behavior_evidence
        )
    )

    if (
        security_score < 60
        or snapshot.liquidity
        < MIN_LIQUIDITY
    ):

        return None

    if final_score < MIN_GOLD_SCORE:

        return None

    whale_score, whale_evidence = (
        whale_analysis(
            snapshot
        )
    )

    diamond_score = (

        final_score * 0.70
        + whale_score * 0.30

    )

    status = "GOLD"

    if (
        diamond_score
        >= MIN_DIAMOND_SCORE
    ):

        status = "DIAMOND"

    evidence.extend(
        whale_evidence
    )

    return Candidate(

        snapshot=snapshot,

        security_score=round(
            security_score,
            2
        ),

        market_score=round(
            market_score,
            2
        ),

        behavior_score=round(
            behavior_score,
            2
        ),

        final_score=round(
            final_score,
            2
        ),

        whale_score=round(
            whale_score,
            2
        ),

        status=status,

        evidence=evidence,

        warnings=warnings

    )


# ============================================================
# SIEVE
# ============================================================

def best_candidate():

    valid = list(
        candidates.values()
    )

    if not valid:

        return None

    valid.sort(

        key=lambda x: (
            x.final_score,
            x.whale_score,
            x.snapshot.liquidity,
            x.snapshot.volume_5m
        ),

        reverse=True
    )

    return valid[0]


# ============================================================
# TELEGRAM BUTTONS
# ============================================================

def candidate_keyboard(
    mint
):

    keyboard = (
        InlineKeyboardMarkup()
    )

    keyboard.row(

        InlineKeyboardButton(
            "📋 نسخ العقد",
            callback_data=
            f"copy:{mint}"
        ),

        InlineKeyboardButton(
            "🛡️ دخلت شراء",
            callback_data=
            f"buy:{mint}"
        )

    )

    keyboard.row(

        InlineKeyboardButton(
            "🔎 التفاصيل",
            callback_data=
            f"details:{mint}"
        )

    )

    return keyboard


def guardian_keyboard():

    keyboard = (
        InlineKeyboardMarkup()
    )

    keyboard.row(

        InlineKeyboardButton(
            "⏹️ أنهيت البيع",
            callback_data=
            "finish_position"
        )

    )

    return keyboard


def radar_keyboard():

    keyboard = (
        InlineKeyboardMarkup()
    )

    keyboard.row(

        InlineKeyboardButton(
            "▶️ ابدأ",
            callback_data=
            "start_radar"
        ),

        InlineKeyboardButton(
            "⏹️ انتهاء",
            callback_data=
            "stop_display"
        )

    )

    return keyboard


# ============================================================
# SEND CANDIDATE
# ============================================================

async def send_candidate(
    candidate
):

    token = candidate.snapshot

    if candidate.status == "DIAMOND":

        title = (
            "💎 **عملة ماسية — دعم قوي محتمل**"
        )

    else:

        title = (
            "🥇 **عملة ذهبية — مرشح قوي**"
        )

    evidence_text = "\n".join(

        "• " + item

        for item
        in candidate.evidence[:6]

    )

    warning_text = "\n".join(

        "• " + item

        for item
        in candidate.warnings[:4]

    )

    text = (

        f"{title}\n\n"

        f"🪙 **الرمز:** "
        f"`{token.symbol}`\n"

        f"🔑 **العقد:**\n"
        f"`{token.mint}`\n\n"

        f"🛡️ **درجة الأمان:** "
        f"`{candidate.security_score}/100`\n"

        f"🏆 **الدرجة النهائية:** "
        f"`{candidate.final_score}/100`\n"

        f"🐋 **مؤشر الدعم الكبير:** "
        f"`{candidate.whale_score}/100`\n\n"

        f"💰 **السعر الحي:** "
        f"`{money(token.price)}`\n"

        f"💧 **السيولة:** "
        f"`{money(token.liquidity)}`\n"

        f"📊 **حجم 5 دقائق:** "
        f"`{money(token.volume_5m)}`\n"

        f"📈 **تغير 5 دقائق:** "
        f"`{percent(token.price_change_5m)}`\n"

        f"🟢 **شراء:** `{token.buys_5m}`\n"

        f"🔴 **بيع:** `{token.sells_5m}`\n\n"

        f"🔎 **الأدلة:**\n"
        f"{evidence_text or 'لا توجد أدلة إضافية'}\n\n"

        f"⚠️ **التحذيرات:**\n"
        f"{warning_text or 'لا يوجد تحذير رئيسي'}\n\n"

        "⚠️ هذه مراقبة آلية وليست ضمانًا "
        "للربح أو للأمان المطلق."

    )

    await send_message(

        text,

        reply_markup=
        candidate_keyboard(
            token.mint
        )

    )


# ============================================================
# START POSITION
# ============================================================

async def start_position(
    mint
):

    global position_active
    global position_mint
    global position_entry_price
    global position_message_id
    global radar_active

    snapshot = await fetch_market_data(
        mint
    )

    if not snapshot:

        await send_message(

            "⚠️ **تعذر بدء المراقبة.**\n"
            "لم تصل بيانات سوق حية للعقد الآن."

        )

        return

    if snapshot.price <= 0:

        await send_message(

            "⚠️ **تعذر بدء المراقبة.**\n"
            "السعر الحالي غير صالح."

        )

        return

    position_active = True

    position_mint = mint

    position_entry_price = (
        snapshot.price
    )

    radar_active = False

    message = await send_message(

        "🛡️ **بدأت المراقبة اللاحقة**\n\n"

        f"🔑 العقد:\n`{mint}`\n\n"

        f"💰 سعر بداية المراقبة:\n"
        f"`{money(snapshot.price)}`\n\n"

        "📡 الحارس يراقب السعر والسيولة "
        "والشراء والبيع باستمرار.\n\n"

        "⏸️ تم إيقاف عرض العملات الجديدة "
        "حتى تنهي هذه المراقبة.",

        reply_markup=
        guardian_keyboard()

    )

    if message:

        position_message_id = (
            message.message_id
        )


# ============================================================
# FINISH POSITION
# ============================================================

async def finish_position():

    global position_active
    global position_mint
    global position_entry_price
    global position_message_id
    global radar_active

    old_mint = position_mint

    position_active = False

    position_mint = None

    position_entry_price = None

    position_message_id = None

    radar_active = True

    await send_message(

        "🟢 **انتهت المراقبة.**\n\n"

        f"العقد السابق: "
        f"`{short_address(old_mint)}`\n\n"

        "▶️
