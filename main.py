import os
import re
import json
import time
import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

import aiohttp
import websockets
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton


# ============================================================
# SOLANA RADAR — FINAL EXPERIMENTAL BUILD
# ============================================================
# Gold / Diamond / Whale Support / Live Guardian / Telegram
# 24/7 background monitoring
#
# IMPORTANT:
# This version is a monitoring/research system.
# It does NOT execute buy/sell orders.
# Start with SHADOW_MODE=true.
# ============================================================


# ============================================================
# 1. CONFIGURATION
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

RAYDIUM_PROGRAM_IDS = [
    x.strip()
    for x in os.environ.get(
        "RAYDIUM_PROGRAM_IDS",
        "675k1v2wPyEaAC6fGgFiTMvU5khRfw731gCxnhcnKC7m"
    ).split(",")
    if x.strip()
]

DEX_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"

SHADOW_MODE = os.environ.get(
    "SHADOW_MODE",
    "true"
).lower() == "true"

MAX_CANDIDATES = int(
    os.environ.get("MAX_CANDIDATES", "500")
)

SIEVE_WINDOW_SECONDS = int(
    os.environ.get("SIEVE_WINDOW_SECONDS", "120")
)

MAX_GOLD_TO_SHOW = int(
    os.environ.get("MAX_GOLD_TO_SHOW", "1")
)

GUARDIAN_SECONDS = int(
    os.environ.get("GUARDIAN_SECONDS", "5")
)

DEX_TIMEOUT = 8
RPC_TIMEOUT = 10

MIN_LIQUIDITY_USD = float(
    os.environ.get("MIN_LIQUIDITY_USD", "15000")
)

MIN_VOLUME_5M_USD = float(
    os.environ.get("MIN_VOLUME_5M_USD", "2500")
)

MIN_TXNS_5M = int(
    os.environ.get("MIN_TXNS_5M", "8")
)

MIN_GOLD_SCORE = float(
    os.environ.get("MIN_GOLD_SCORE", "72")
)

MIN_DIAMOND_SCORE = float(
    os.environ.get("MIN_DIAMOND_SCORE", "88")
)


# ============================================================
# 2. LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("solana-radar")


# ============================================================
# 3. TELEGRAM
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "Missing TELEGRAM_BOT_TOKEN"
    )

if not CHAT_ID:
    raise RuntimeError(
        "Missing CHAT_ID"
    )

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="Markdown"
)


# ============================================================
# 4. GLOBAL STATE
# ============================================================

radar_active = True

position_active = False
position_mint = None
position_entry_price = None
position_started_at = None
position_message_id = None

main_loop = None
http_session = None

seen_signatures = set()
seen_mints = set()

candidate_by_mint = {}

event_history = deque(
    maxlen=5000
)

hourly_stats = [0] * 24

daily_stats = {
    "scanned_events": 0,
    "gold": 0,
    "diamond": 0,
    "danger": 0,
    "last_reset": datetime.now(
        timezone.utc
    ).date()
}


# ============================================================
# 5. DATA STRUCTURES
# ============================================================

@dataclass
class TokenSnapshot:

    mint: str

    symbol: str = "UNKNOWN"

    name: str = "Unknown"

    price_usd: Optional[float] = None

    liquidity_usd: float = 0.0

    volume_5m_usd: float = 0.0

    buys_5m: int = 0

    sells_5m: int = 0

    txns_5m: int = 0

    price_change_5m: float = 0.0

    fdv: float = 0.0

    pair_address: str = ""

    dex_id: str = ""

    url: str = ""

    age_minutes: Optional[float] = None

    raw: dict = field(
        default_factory=dict
    )


@dataclass
class Candidate:

    snapshot: TokenSnapshot

    score: float

    security_score: float

    market_score: float

    behavior_score: float

    red_flags: list[str]

    evidence: list[str]

    status: str = "CANDIDATE"

    first_seen: datetime = field(
        default_factory=lambda:
        datetime.now(timezone.utc)
    )

    whale_score: float = 0.0

    diamond_score: float = 0.0


# ============================================================
# 6. TIME / FORMAT FUNCTIONS
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    )


def local_hour():

    return (
        utc_now()
        + timedelta(hours=1)
    ).hour


def short_mint(mint):

    if len(mint) > 14:

        return (
            f"{mint[:6]}..."
            f"{mint[-6:]}"
        )

    return mint


def fmt_money(value):

    if value is None:

        return "غير متاح"

    if value >= 1_000_000:

        return (
            f"${value / 1_000_000:.2f}M"
        )

    if value >= 1_000:

        return (
            f"${value / 1_000:.1f}K"
        )

    if value >= 1:

        return (
            f"${value:.4f}"
        )

    return (
        f"${value:.8f}"
    )


def fmt_pct(value):

    return f"{value:+.2f}%"


# ============================================================
# 7. EVENT RECORDING
# ============================================================

def record_event(
    kind,
    mint=None,
    extra=None
):

    now = utc_now()

    hour = local_hour()

    hourly_stats[hour] += 1

    event_history.append({

        "time": now.isoformat(),

        "kind": kind,

        "mint": mint,

        "extra": extra or {}

    })


def reset_daily_if_needed():

    today = utc_now().date()

    if today != daily_stats["last_reset"]:

        daily_stats[
            "scanned_events"
        ] = 0

        daily_stats[
            "gold"
        ] = 0

        daily_stats[
            "diamond"
        ] = 0

        daily_stats[
            "danger"
        ] = 0

        daily_stats[
            "last_reset"
        ] = today

        for i in range(24):

            hourly_stats[i] = 0


# ============================================================
# 8. TELEGRAM HELPERS
# ============================================================

async def tg_send(
    text,
    **kwargs
):

    try:

        return await asyncio.to_thread(
            bot.send_message,
            CHAT_ID,
            text,
            **kwargs
        )

    except Exception as exc:

        log.warning(
            "Telegram error: %s",
            exc
        )


async def tg_edit(
    message_id,
    text,
    **kwargs
):

    try:

        return await asyncio.to_thread(

            bot.edit_message_text,

            text,

            chat_id=CHAT_ID,

            message_id=message_id,

            **kwargs

        )

    except Exception as exc:

        log.debug(
            "Telegram edit error: %s",
            exc
        )


# ============================================================
# 9. SOLANA RPC
# ============================================================

async def rpc_call(
    method,
    params
):

    global http_session

    if http_session is None:

        http_session = aiohttp.ClientSession(

            timeout=aiohttp.ClientTimeout(
                total=RPC_TIMEOUT
            )

        )

    payload = {

        "jsonrpc": "2.0",

        "id":
            int(
                time.time() * 1000
            ) % 2_000_000_000,

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

                data = await response.json()

                if data.get("error"):

                    raise RuntimeError(
                        str(data["error"])
                    )

                return data.get(
                    "result"
                )

        except Exception as exc:

            if attempt == 2:

                log.warning(
                    "RPC failed %s: %s",
                    method,
                    exc
                )

            await asyncio.sleep(
                1.5 * (attempt + 1)
            )

    return None


async def get_transaction(
    signature
):

    return await rpc_call(

        "getTransaction",

        [

            signature,

            {

                "encoding":
                    "jsonParsed",

                "commitment":
                    "confirmed",

                "maxSupportedTransactionVersion":
                    0

            }

        ]

    )


def extract_pubkeys(tx):

    keys = []

    try:

        message = (
            tx["transaction"]
            ["message"]
        )

        for item in message.get(
            "accountKeys",
            []
        ):

            if isinstance(
                item,
                dict
            ):

                pubkey = item.get(
                    "pubkey"
                )

            else:

                pubkey = item

            if (
                pubkey
                and pubkey not in keys
            ):

                keys.append(pubkey)

    except Exception:

        pass

    return keys


def looks_like_solana_pubkey(
    pubkey
):

    return bool(
        re.fullmatch(
            r"[1-9A-HJ-NP-Za-km-z]{32,44}",
            pubkey
        )
    )


# ============================================================
# 10. DEX MARKET DATA
# ============================================================

async def fetch_market(
    mint
):

    global http_session

    if http_session is None:

        http_session = aiohttp.ClientSession(

            timeout=aiohttp.ClientTimeout(
                total=DEX_TIMEOUT
            )

        )

    try:

        async with http_session.get(

            DEX_TOKEN_URL.format(
                mint
            )

        ) as response:

            if response.status != 200:

                return None

            data = await response.json()

        pairs = (
            data.get("pairs")
            or []
        )

        if not pairs:

            return None

        sol_pairs = [

            pair

            for pair in pairs

            if pair.get(
                "chainId"
            ) == "solana"

        ]

        if not sol_pairs:

            sol_pairs = pairs

        main_pair = max(

            sol_pairs,

            key=lambda pair:
                float(
                    (
                        pair.get(
                            "liquidity"
                        )
                        or {}
                    ).get(
                        "usd"
                    )
                    or 0
                )

        )

        transactions = (
            main_pair.get(
                "txns"
            )
            or {}
        )

        m5 = (
            transactions.get(
                "m5"
            )
            or {}
        )

        volume = (
            main_pair.get(
                "volume"
            )
            or {}
        )

        liquidity = (
            main_pair.get(
                "liquidity"
            )
            or {}
        )

        change = (
            main_pair.get(
                "priceChange"
            )
            or {}
        )

        base = (
            main_pair.get(
                "baseToken"
            )
            or {}
        )

        price_raw = main_pair.get(
            "priceUsd"
        )

        price = None

        if price_raw not in (
            None,
            ""
        ):

            price = float(
                price_raw
            )

        buys = int(
            m5.get(
                "buys"
            )
            or 0
        )

        sells = int(
            m5.get(
                "sells"
            )
            or 0
        )

        return TokenSnapshot(

            mint=mint,

            symbol=str(
                base.get(
                    "symbol"
                )
                or "UNKNOWN"
            ),

            name=str(
                base.get(
                    "name"
                )
                or "Unknown"
            ),

            price_usd=price,

            liquidity_usd=float(
                liquidity.get(
                    "usd"
                )
                or 0
            ),

            volume_5m_usd=float(
                volume.get(
                    "m5"
                )
                or 0
            ),

            buys_5m=buys,

            sells_5m=sells,

            txns_5m=(
                buys + sells
            ),

            price_change_5m=float(
                change.get(
                    "m5"
                )
                or 0
            ),

            fdv=float(
                main_pair.get(
                    "fdv"
                )
                or 0
            ),

            pair_address=str(
                main_pair.get(
                    "pairAddress"
                )
                or ""
            ),

            dex_id=str(
                main_pair.get(
                    "dexId"
                )
                or ""
            ),

            url=str(
                main_pair.get(
                    "url"
                )
                or ""
            ),

            raw=main_pair

        )

    except Exception as exc:

        log.debug(
            "Market lookup failed %s: %s",
            short_mint(mint),
            exc
        )

        return None


# ============================================================
# 11. MARKET SCORE
# ============================================================

def score_market(
    snapshot
):

    score = 0.0

    red_flags = []

    evidence = []

    # Liquidity

    if snapshot.liquidity_usd >= 50_000:

        score += 30

        evidence.append(
            "سيولة قوية"
        )

    elif (
        snapshot.liquidity_usd
        >= MIN_LIQUIDITY_USD
    ):

        score += 22

        evidence.append(
            "سيولة مقبولة"
        )

    else:

        red_flags.append(
            "سيولة ضعيفة"
        )

    # Volume

    if snapshot.volume_5m_usd >= 25_000:

        score += 25

        evidence.append(
            "حجم تداول قوي"
        )

    elif (
        snapshot.volume_5m_usd
        >= MIN_VOLUME_5M_USD
    ):

        score += 15

        evidence.append(
            "حجم تداول مقبول"
        )

    else:

        red_flags.append(
            "حجم ضعيف"
        )

    # Transactions

    if snapshot.txns_5m >= 50:

        score += 20

        evidence.append(
            "نشاط مرتفع"
        )

    elif (
        snapshot.txns_5m
        >= MIN_TXNS_5M
    ):

        score += 12

        evidence.append(
            "نشاط مقبول"
        )

    else:

        red_flags.append(
            "نشاط ضعيف"
        )

    # Buy / Sell balance

    total = (
        snapshot.buys_5m
        + snapshot.sells_5m
    )

    if total:

        buy_ratio = (
            snapshot.buys_5m
            / total
        )

        if buy_ratio >= 0.60:

            score += 15

            evidence.append(
                "ضغط شراء إيجابي"
            )

        elif buy_ratio <= 0.35:

            score -= 15

            red_flags.append(
                "ضغط بيع مرتفع"
            )

        else:

            score += 5

    # Momentum

    if snapshot.price_change_5m >= 100:

        score -= 12

        red_flags.append(
            "ارتفاع قصير شديد"
        )

    elif snapshot.price_change_5m >= 20:

        score += 5

        evidence.append(
            "زخم إيجابي"
        )

    if snapshot.liquidity_usd <= 0:

        red_flags.append(
            "لا توجد سيولة قابلة للتحقق"
        )

    return (
        max(
            0,
            min(
                100,
                score
            )
        ),
        red_flags,
        evidence
    )


# ============================================================
# 12. SECURITY SCORE
# ============================================================

def score_security(
    snapshot
):

    score = 50.0

    red_flags = []

    evidence = []

    if (
        snapshot.liquidity_usd
        >= MIN_LIQUIDITY_USD
    ):

        score += 20

        evidence.append(
            "السيولة قابلة للتحقق"
        )

    else:

        score -= 25

        red_flags.append(
            "السيولة دون الحد"
        )

    if (
        snapshot.txns_5m
        >= MIN_TXNS_5M
    ):

        score += 10

        evidence.append(
            "نشاط سوق حقيقي ظاهر"
        )

    else:

        score -= 10

        red_flags.append(
            "نشاط غير كاف"
        )

    if (
        snapshot.volume_5m_usd
        >= MIN_VOLUME_5M_USD
    ):

        score += 10

        evidence.append(
            "حجم قابل للقياس"
        )

    else:

        score -= 10

        red_flags.append(
            "حجم غير كاف"
        )

    if (
        snapshot.sells_5m
        > snapshot.buys_5m * 2
        and snapshot.sells_5m >= 10
    ):

        score -= 20

        red_flags.append(
            "اختلال قوي لصالح البيع"
        )

    return (
        max(
            0,
            min(
                100,
                score
            )
        ),
        red_flags,
        evidence
    )


# ============================================================
# 13. GOLD FILTER
# ============================================================

def score_candidate(
    snapshot
):

    market_score, market_red, market_evidence = (
        score_market(
            snapshot
        )
    )

    security_score, security_red, security_evidence = (
        score_security(
            snapshot
        )
    )

    red_flags = list(
        dict.fromkeys(
            market_red
            + security_red
        )
    )

    evidence = list(
        dict.fromkeys(
            market_evidence
            + security_evidence
        )
    )

    critical_flags = {

        "لا توجد سيولة قابلة للتحقق",

        "سيولة ضعيفة",

        "اختلال قوي لصالح البيع"

    }

    if critical_flags.intersection(
        red_flags
    ):

        return None

    behavior_score = 50.0

    if (
        snapshot.price_change_5m
        > 0
    ):

        behavior_score += 10

    if (
        snapshot.buys_5m
        > snapshot.sells_5m
    ):

        behavior_score += 10

    if (
        snapshot.sells_5m
        > snapshot.buys_5m * 1.5
    ):

        behavior_score -= 20

    behavior_score = max(
        0,
        min(
            100,
            behavior_score
        )
    )

    total_score = (

        security_score * 0.45

        + market_score * 0.40

        + behavior_score * 0.15

    )

    if (
        total_score
        < MIN_GOLD_SCORE
    ):

        return None

    return Candidate(

        snapshot=snapshot,

        score=round(
            total_score,
            2
        ),

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

        red_flags=red_flags,

        evidence=evidence

    )


# ============================================================
# 14. RELATIVE SIEVE
# ============================================================

def rank_candidates():

    now = utc_now()

    valid = []

    for candidate in (
        candidate_by_mint.values()
    ):

        age = (
            now
            - candidate.first_seen
        ).total_seconds()

        if (
            age
            <= SIEVE_WINDOW_SECONDS
        ):

            valid.append(
                candidate
            )

    valid.sort(

        key=lambda candidate: (

            candidate.score,

            candidate.snapshot
            .liquidity_usd,

            candidate.snapshot
            .volume_5m_usd

        ),

        reverse=True

    )

    return valid


# ============================================================
# 15. WHALE / DIAMOND LAYER
# ============================================================

async def estimate_whale_support(
    candidate
):

    snapshot = (
        candidate.snapshot
    )

    score = 0.0

    evidence = []

    if (
        snapshot.volume_5m_usd
        >= 50_000
        and snapshot.liquidity_usd
        >= 50_000
    ):

        score += 30

        evidence.append(
            "رأس مال/نشاط كبير ظاهر"
        )

    if (
        snapshot.buys_5m >= 30
        and snapshot.buys_5m
        > snapshot.sells_5m
    ):

        score += 20

        evidence.append(
            "شراء متكرر خلال 5 دقائق"
        )

    if (
        snapshot.liquidity_usd
        >= 100_000
    ):

        score += 15

        evidence.append(
            "سيولة كبيرة"
        )

    if (
        snapshot.price_change_5m > 0
        and snapshot.sells_5m
        < snapshot.buys_5m
    ):

        score += 15

        evidence.append(
            "الدعم الشرائي مستمر"
        )

    return (
        min(
            100,
            score
        ),
        evidence
    )


async def enrich_diamond(
    candidate
):

    whale_score, whale_evidence = (
        await estimate_whale_support(
            candidate
        )
    )

    candidate.whale_score = (
        whale_score
    )

    candidate.diamond_score = round(

        candidate.score * 0.70

        + whale_score * 0.30,

        2

    )

    candidate.evidence.extend(
        whale_evidence
    )

    if (
        candidate.diamond_score
        >= MIN_DIAMOND_SCORE
    ):

        candidate.status = (
            "DIAMOND"
        )

    else:

        candidate.status = (
            "GOLD"
        )

    return candidate


# ============================================================
# 16. TELEGRAM KEYBOARDS
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
            "🟢 دخلت شراء",
            callback_data=
            f"buy:{mint}"
        )

    )

    keyboard.row(

        InlineKeyboardButton(
            "🔎 تفاصيل",
            callback_data=
            f"details:{mint}"
        )

    )

    return keyboard


def position_keyboard():

    keyboard = (
        InlineKeyboardMarkup()
    )

    keyboard.row(

        InlineKeyboardButton(
            "⏹️ أنهيت البيع",
            callback_data=
            "position_end"
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
            "radar_start"
        ),

        InlineKeyboardButton(
            "⏹️ انتهاء",
            callback_data=
            "radar_end"
        )

    )

    return keyboard


# ============================================================
# 17. SEND GOLD / DIAMOND
# ============================================================

async def send_candidate(
    candidate
):

    snapshot = (
        candidate.snapshot
    )

    icon = (
        "💎"
        if candidate.status
        == "DIAMOND"
        else "🥇"
    )

    text = (

        f"{icon} **{candidate.status} — "
        f"مرشح رادار**\n\n"

        f"🪙 **العملة:** "
        f"`{snapshot.symbol}`\n"

        f"🔑 **العقد:** "
        f"`{snapshot.mint}`\n"

        f"🛡️ **درجة الفحص:** "
        f"`{candidate.score}/100`\n"

        f"💧 **السيولة:** "
        f"{fmt_money(snapshot.liquidity_usd)}\n"

        f"💰 **السعر:** "
        f"{fmt_money(snapshot.price_usd)}\n"

        f"📈 **5 دقائق:** "
        f"{fmt_pct(snapshot.price_change_5m)}\n"

        f"📊 **الحجم 5د:** "
        f"{fmt_money(snapshot.volume_5m_usd)}\n"

        f"🐋 **دعم كبير محتمل:** "
        f"`{candidate.whale_score:.0f}/100`\n\n"

        f"🔎 **الخلاصة:** "

        + (
            "أدلة إضافية على دعم قوي"
            if candidate.status
            == "DIAMOND"
            else
            "مرشح Gold تحت المراقبة"
        )

        + "\n\n"

        "⚠️ هذه إشارة رصد وليست "
        "ضمانًا للربح أو الأمان."

    )

    await tg_send(

        text,

        reply_markup=
        candidate_keyboard(
            snapshot.mint
        ),

        disable_web_page_preview=True

    )


# ============================================================
# 18. POSITION GUARDIAN START
# ============================================================

async def start_position(
    mint
):

    global position_active
    global position_mint
    global position_entry_price
    global position_started_at
    global position_message_id
    global radar_active

    snapshot = await fetch_market(
        mint
    )

    if (
        not snapshot
        or snapshot.price_usd is None
    ):

        await tg_send(

            "⚠️ **تعذر بدء المراقبة:**\n"
            "لم أستطع الحصول على
