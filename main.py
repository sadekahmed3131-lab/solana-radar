import os
import json
import time
import asyncio
import logging
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web
import websockets
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton


# ============================================================
# SOLANA RADAR V2 — UNIFIED CONTINUOUS ENGINE
# ============================================================
#
# Monitoring / research only
# NO automatic trading.
#
# CORE:
#
#   DISCOVER
#       ↓
#   NORMALIZE
#       ↓
#   SECURITY GATE
#       ↓
#   MARKET ANALYSIS
#       ↓
#   BEHAVIOR ANALYSIS
#       ↓
#   WHALE SUPPORT
#       ↓
#   GOLD / DIAMOND
#       ↓
#   TELEGRAM ALERT
#       ↓
#   MANUAL BUY BUTTON
#       ↓
#   GUARDIAN
#       ↓
#   CONTINUOUS RE-EVALUATION
#       ↓
#   ARCHIVE / MEMORY
#       ↓
#   DAILY INTELLIGENCE
#       ↓
#   DISCOVER AGAIN
#
# The engine is designed to run continuously.
#
# ============================================================


APP_NAME = "SOLANA_RADAR_V2"
VERSION = "2.0-UNIFIED-CONTINUOUS"


# ============================================================
# ENVIRONMENT
# ============================================================

BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

CHAT_ID = os.getenv(
    "CHAT_ID",
    ""
).strip()


SOLANA_HTTP_URL = os.getenv(
    "SOLANA_HTTP_URL",
    "https://api.mainnet-beta.solana.com"
).strip()


SOLANA_WS_URL = os.getenv(
    "SOLANA_WS_URL",
    "wss://api.mainnet-beta.solana.com"
).strip()


LOCAL_TIMEZONE = os.getenv(
    "LOCAL_TIMEZONE",
    "Africa/Algiers"
).strip()


DASHBOARD_HOST = os.getenv(
    "DASHBOARD_HOST",
    "0.0.0.0"
).strip()


DASHBOARD_PORT = int(
    os.getenv(
        "DASHBOARD_PORT",
        "8080"
    )
)


MIN_LIQUIDITY = float(
    os.getenv(
        "MIN_LIQUIDITY_USD",
        "15000"
    )
)


MIN_VOLUME_5M = float(
    os.getenv(
        "MIN_VOLUME_5M_USD",
        "2500"
    )
)


MIN_GOLD_SCORE = float(
    os.getenv(
        "MIN_GOLD_SCORE",
        "72"
    )
)


MIN_DIAMOND_SCORE = float(
    os.getenv(
        "MIN_DIAMOND_SCORE",
        "88"
    )
)


GUARDIAN_INTERVAL = max(
    2,
    int(
        os.getenv(
            "GUARDIAN_INTERVAL",
            "5"
        )
    )
)


DEX_INTERVAL = max(
    3,
    int(
        os.getenv(
            "DEX_INTERVAL",
            "5"
        )
    )
)


SOURCE_REFRESH_INTERVAL = max(
    30,
    int(
        os.getenv(
            "SOURCE_REFRESH_INTERVAL",
            "120"
        )
    )
)


MAX_CANDIDATES = max(
    100,
    int(
        os.getenv(
            "MAX_CANDIDATES",
            "5000"
        )
    )
)


MAX_ARCHIVE = max(
    1000,
    int(
        os.getenv(
            "MAX_ARCHIVE",
            "20000"
        )
    )
)


# Optional PumpPortal real-time discovery.
# This is ONLY used for monitoring.
# No trading endpoint is used anywhere in this program.

PUMPPORTAL_API_KEY = os.getenv(
    "PUMPPORTAL_API_KEY",
    ""
).strip()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(
    APP_NAME
)


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
# TELEGRAM
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="Markdown"
)


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class TokenSnapshot:

    mint: str

    symbol: str = "UNKNOWN"

    name: str = "Unknown"

    price: float = 0.0

    liquidity: float = 0.0

    volume_5m: float = 0.0

    volume_1h: float = 0.0

    buys_5m: int = 0

    sells_5m: int = 0

    buys_1h: int = 0

    sells_1h: int = 0

    price_change_5m: float = 0.0

    price_change_1h: float = 0.0

    pair_address: str = ""

    dex_id: str = ""

    source: str = ""

    url: str = ""

    fdv: float = 0.0

    market_cap: float = 0.0

    mint_authority: str = ""

    freeze_authority: str = ""

    creator: str = ""

    created_at: float = 0.0

    observed_at: float = field(
        default_factory=time.time
    )

    raw: dict = field(
        default_factory=dict
    )


@dataclass
class Candidate:

    snapshot: TokenSnapshot

    security_score: float

    market_score: float

    behavior_score: float

    whale_score: float

    final_score: float

    diamond_score: float

    status: str

    evidence: list = field(
        default_factory=list
    )

    warnings: list = field(
        default_factory=list
    )

    first_seen: float = field(
        default_factory=time.time
    )

    last_seen: float = field(
        default_factory=time.time
    )

    updates: int = 0


@dataclass
class FlowEvent:

    mint: str

    kind: str

    value_usd: float

    source: str

    timestamp: float = field(
        default_factory=time.time
    )

    details: str = ""


# ============================================================
# GLOBAL ENGINE STATE
# ============================================================

radar_active = True

position_active = False

position_mint = None

position_entry_price = None

position_message_id = None

position_started_at = None

event_loop = None

http_session = None

dashboard_runner = None


# ------------------------------------------------------------
# MEMORY
# ------------------------------------------------------------

seen_mints = set()

seen_signatures = set()

candidates = {}

archive = deque(
    maxlen=MAX_ARCHIVE
)

flow_history = deque(
    maxlen=MAX_ARCHIVE
)

activity_history = deque(
    maxlen=MAX_ARCHIVE
)


# ------------------------------------------------------------
# HEARTBEAT
# ------------------------------------------------------------

last_heartbeat = 0.0

last_source_refresh = 0.0

last_daily_report = None


# ============================================================
# SOURCE REGISTRY
# ============================================================

source_registry = {}

source_state = {}


# ============================================================
# DAILY STATE
# ============================================================

daily_stats = {

    "date": None,

    "events": 0,

    "gold": 0,

    "diamond": 0,

    "danger": 0,

    "new_mints": 0,

    "guardian_alerts": 0,
}


hourly_stats = [

    {

        "events": 0,

        "gold": 0,

        "diamond": 0,

        "danger": 0,

        "volume": 0.0,

        "flow_in": 0.0,

        "flow_out": 0.0,

    }

    for _ in range(24)

]


# ============================================================
# GUARDIAN DASHBOARD STATE
# ============================================================

dashboard_guardian_cache = {

    "mint": None,

    "price": 0.0,

    "liquidity": 0.0,

    "change": 0.0,

    "buys_5m": 0,

    "sells_5m": 0,

    "status": "idle",

    "elapsed": "",

    "updated": 0.0,
}


# ============================================================
# TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    )


def local_now():

    try:

        return utc_now().astimezone(
            ZoneInfo(
                LOCAL_TIMEZONE
            )
        )

    except Exception:

        return utc_now()


def local_time_text(
    timestamp=None
):

    if timestamp is None:

        dt = local_now()

    else:

        dt = datetime.fromtimestamp(
            timestamp,
            timezone.utc
        )

        try:

            dt = dt.astimezone(
                ZoneInfo(
                    LOCAL_TIMEZONE
                )
            )

        except Exception:

            pass

    return dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def current_hour():

    return local_now().hour


def reset_daily_stats_if_needed():

    global last_daily_report

    today = local_now().date().isoformat()

    if daily_stats["date"] != today:

        daily_stats.update(
            {

                "date": today,

                "events": 0,

                "gold": 0,

                "diamond": 0,

                "danger": 0,

                "new_mints": 0,

                "guardian_alerts": 0,

            }
        )

        for row in hourly_stats:

            for key in row:

                row[key] = 0

        last_daily_report = None


# ============================================================
# FORMATTERS
# ============================================================

def safe_float(
    value,
    default=0.0
):

    try:

        return float(value)

    except Exception:

        return default


def safe_int(
    value,
    default=0
):

    try:

        return int(value)

    except Exception:

        return default


def money(value):

    value = safe_float(
        value
    )

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


def pct(value):

    try:

        return (
            f"{float(value):+.2f}%"
        )

    except Exception:

        return "0.00%"


def short_address(
    address
):

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
# HTTP SESSION
# ============================================================

async def get_session():

    global http_session

    if (
        http_session is None
        or http_session.closed
    ):

        http_session = aiohttp.ClientSession(

            timeout=aiohttp.ClientTimeout(
                total=15
            ),

            headers={
                "User-Agent":
                    f"{APP_NAME}/{VERSION}"
            }

        )

    return http_session


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

    session = await get_session()

    payload = {

        "jsonrpc": "2.0",

        "id": int(
            time.time() * 1000
        ),

        "method": method,

        "params": params,

    }


    for attempt in range(3):

        try:

            async with session.post(
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
                        str(
                            data["error"]
                        )
                    )

                return data.get(
                    "result"
                )

        except Exception as exc:

            if attempt == 2:

                logger.warning(
                    "RPC %s failed: %s",
                    method,
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

                "encoding":
                    "jsonParsed",

                "commitment":
                    "confirmed",

                "maxSupportedTransactionVersion":
                    0,

            }

        ]

    )


async def get_account_info(
    address
):

    return await rpc_request(

        "getAccountInfo",

        [

            address,

            {

                "encoding":
                    "jsonParsed",

                "commitment":
                    "confirmed",

            }

        ]

    )


# ============================================================
# MINT AUTHORITY ANALYSIS
# ============================================================

async def inspect_mint_authorities(
    mint
):

    result = await get_account_info(
        mint
    )

    if result is None:

        return (
            "__UNKNOWN__",
            "__UNKNOWN__"
        )


    value = result.get(
        "value"
    )


    if not value:

        return (
            "__UNKNOWN__",
            "__UNKNOWN__"
        )


    data = value.get(
        "data"
    )


    if not isinstance(
        data,
        dict
    ):

        return (
            "__UNKNOWN__",
            "__UNKNOWN__"
        )


    parsed = (
        data.get("parsed")
        or {}
    )


    info = (
        parsed.get("info")
        or {}
    )


    mint_authority = (
        info.get(
            "mintAuthority"
        )
    )


    freeze_authority = (
        info.get(
            "freezeAuthority"
        )
    )


    # None means authority revoked.
    # UNKNOWN is kept separate from revoked.

    return (

        str(mint_authority)
        if mint_authority
        else None,

        str(freeze_authority)
        if freeze_authority
        else None,

    )


# ============================================================
# DEXSCREENER MARKET DATA
# ============================================================

async def fetch_market_data(
    mint
):

    session = await get_session()

    try:

        url = (
            "https://api.dexscreener.com/"
            f"latest/dex/tokens/{mint}"
        )


        async with session.get(
            url
        ) as response:

            if response.status != 200:

                return None

            data = await response.json()


        pairs = (
            data.get("pairs")
            or []
        )


        pairs = [

            pair

            for pair in pairs

            if pair.get(
                "chainId"
            ) == "solana"

        ]


        if not pairs:

            return None


        pair = max(

            pairs,

            key=lambda p:
                safe_float(
                    (
                        p.get(
                            "liquidity"
                        )
                        or {}
                    ).get(
                        "usd"
                    )
                )

        )


        base = (
            pair.get(
                "baseToken"
            )
            or {}
        )


        liquidity = (
            pair.get(
                "liquidity"
            )
            or {}
        )


        volume = (
            pair.get(
                "volume"
            )
            or {}
        )


        txns = (
            pair.get(
                "txns"
            )
            or {}
        )


        m5 = (
            txns.get(
                "m5"
            )
            or {}
        )


        h1 = (
            txns.get(
                "h1"
            )
            or {}
        )


        changes = (
            pair.get(
                "priceChange"
            )
            or {}
        )


        try:

            mint_authority, freeze_authority = (
                await inspect_mint_authorities(
                    mint
                )
            )

        except Exception:

            mint_authority = "__UNKNOWN__"
            freeze_authority = "__UNKNOWN__"


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

            price=safe_float(
                pair.get(
                    "priceUsd"
                )
            ),

            liquidity=safe_float(
                liquidity.get(
                    "usd"
                )
            ),

            volume_5m=safe_float(
                volume.get(
                    "m5"
                )
            ),

            volume_1h=safe_float(
                volume.get(
                    "h1"
                )
            ),

            buys_5m=safe_int(
                m5.get(
                    "buys"
                )
            ),

            sells_5m=safe_int(
                m5.get(
                    "sells"
                )
            ),

            buys_1h=safe_int(
                h1.get(
                    "buys"
                )
            ),

            sells_1h=safe_int(
                h1.get(
                    "sells"
                )
            ),

            price_change_5m=safe_float(
                changes.get(
                    "m5"
                )
            ),

            price_change_1h=safe_float(
                changes.get(
                    "h1"
                )
            ),

            pair_address=str(
                pair.get(
                    "pairAddress"
                )
                or ""
            ),

            dex_id=str(
                pair.get(
                    "dexId"
                )
                or ""
            ),

            source="dexscreener",

            url=str(
                pair.get(
                    "url"
                )
                or ""
            ),

            fdv=safe_float(
                pair.get(
                    "fdv"
                )
            ),

            market_cap=safe_float(
                pair.get(
                    "marketCap"
                )
            ),

            mint_authority=(
                mint_authority
            ),

            freeze_authority=(
                freeze_authority
            ),

            observed_at=time.time(),

            raw=pair

        )


    except Exception as exc:

        logger.debug(

            "DEX lookup failed for %s: %s",

            short_address(
                mint
            ),

            exc

        )

        return None


# ============================================================
# SOURCE REGISTRY
# ============================================================

def register_sources():

    global source_registry

    source_registry = {

        "solana_rpc": {

            "type": "onchain",

            "enabled": True,

            "description":
                "Solana RPC log stream",

        },

        "dexscreener": {

            "type": "market",

            "enabled": True,

            "description":
                "Solana market enrichment",

        },

        "pumpfun": {

            "type": "launchpad",

            "enabled": True,

            "description":
                "Pump.fun discovery",

        },

        "raydium": {

            "type": "launchpad_dex",

            "enabled": True,

            "description":
                "Raydium discovery",

        },

        "meteora": {

            "type": "launchpad_dex",

            "enabled": True,

            "description":
                "Meteora discovery adapter",

        },

        "moonshot": {

            "type": "launchpad",

            "enabled": True,

            "description":
                "Moonshot discovery adapter",

        },

        "bonkfun": {

            "type": "launchpad",

            "enabled": True,

            "description":
                "Bonk.fun discovery adapter",

        },

        "bags": {

            "type": "launchpad",

            "enabled": True,

            "description":
                "Bags discovery adapter",

        },

        "jupiter_lfg": {

            "type": "launchpad",

            "enabled": True,

            "description":
                "Jupiter LFG discovery adapter",

        },

    }


# ============================================================
# GENERIC SOURCE HELPERS
# ============================================================

def extract_mint_from_object(
    obj
):

    if not isinstance(
        obj,
        dict
    ):

        return ""


    keys = (

        "mint",

        "tokenMint",

        "tokenAddress",

        "baseMint",

        "address",

        "contract",

        "token",

    )


    for key in keys:

        value = obj.get(
            key
        )

        if (
            isinstance(
                value,
                str
            )
            and 30 <= len(value) <= 50
        ):

            return value


    nested = obj.get(
        "token"
    )


    if isinstance(
        nested,
        dict
    ):

        return extract_mint_from_object(
            nested
        )


    return ""


async def fetch_json_url(
    url
):

    if not url:

        return None


    session = await get_session()


    try:

        async with session.get(
            url
        ) as response:

            if response.status != 200:

                return None

            return await response.json(
                content_type=None
            )


    except Exception as exc:

        logger.debug(
            "Source request failed %s: %s",
            url,
            exc
        )

        return None


# ============================================================
# CONFIGURABLE LAUNCHPAD DISCOVERY
# ============================================================

async def discover_configured_http_sources():

    env_map = {

        "pumpfun":
            "PUMPFUN_DISCOVERY_URL",

        "moonshot":
            "MOONSHOT_DISCOVERY_URL",

        "meteora":
            "METEORA_DISCOVERY_URL",

        "bonkfun":
            "BONKFUN_DISCOVERY_URL",

        "bags":
            "BAGS_DISCOVERY_URL",

        "jupiter_lfg":
            "JUPITER_LFG_DISCOVERY_URL",

    }


    discoveries = []


    for source, env_name in env_map.items():

        url = os.getenv(
            env_name,
            ""
        ).strip()


        if not url:

            continue


        data = await fetch_json_url(
            url
        )


        if not data:

            continue


        if isinstance(
            data,
            list
        ):

            items = data

        else:

            items = data.get(
                "data",
                []
            )


        if isinstance(
            items,
            dict
        ):

            items = items.get(
                "tokens",
                items.get(
                    "results",
                    []
                )
            )


        if not isinstance(
            items,
            list
        ):

            continue


        for item in items[:500]:

            mint = extract_mint_from_object(
                item
            )


            if mint:

                discoveries.append(
                    (
                        mint,
                        source
                    )
                )


    return discoveries


# ============================================================
# PUMPFUN / PUMPPORTAL REAL-TIME DISCOVERY
# ============================================================

async def pumpportal_stream():

    if not PUMPPORTAL_API_KEY:

        logger.info(
            "PumpPortal disabled: "
            "PUMPPORTAL_API_KEY is not set."
        )


        while True:

            await asyncio.sleep(
                300
            )


    backoff = 2


    while True:

        try:

            uri = (
                "wss://pumpportal.fun/api/data"
                f"?api-key={PUMPPORTAL_API_KEY}"
            )


            async with websockets.connect(

                uri,

                ping_interval=20,

                ping_timeout=20,

                close_timeout=5,

                max_size=
                    8 * 1024 * 1024,

            ) as ws:


                await ws.send(
                    json.dumps(
                        {
                            "method":
                                "subscribeNewToken"
                        }
                    )
                )


                await ws.send(
                    json.dumps(
                        {
                            "method":
                                "subscribeMigration"
                        }
                    )
                )


                backoff = 2


                logger.info(
                    "PumpPortal discovery stream connected."
                )


                async for raw in ws:

                    try:

                        event = json.loads(
                            raw
                        )

                    except json.JSONDecodeError:

                        continue


                    mint = extract_mint_from_object(
                        event
                    )


                    if not mint:

                        continue


                    source = "pumpfun"


                    if (
                        str(
                            event.get(
                                "txType"
                            )
                            or ""
                        ).lower()
                        == "migrate"
                    ):

                        source = (
                            "pumpswap_migration"
                        )


                    await discover_mint(
                        mint,
                        source
                    )


        except asyncio.CancelledError:

            raise


        except Exception as exc:

            logger.warning(
                "PumpPortal disconnected: %s",
                exc
            )


            await asyncio.sleep(
                backoff
            )


            backoff = min(
                backoff * 2,
                60
            )


# ============================================================
# SOLANA ON-CHAIN DISCOVERY
# ============================================================

RAYDIUM_PROGRAM_ID = os.getenv(
    "RAYDIUM_PROGRAM_ID",
    "675k1v2wPyEaAC6fGgFiTMvU5khRfw731gCxnhcnKC7m"
).strip()


async def solana_log_stream():

    global last_heartbeat


    backoff = 2


    while True:

        try:

            async with websockets.connect(

                SOLANA_WS_URL,

                ping_interval=20,

                ping_timeout=20,

                close_timeout=5,

                max_size=
                    8 * 1024 * 1024,

            ) as ws:


                request = {

                    "jsonrpc":
                        "2.0",

                    "id":
                        1,

                    "method":
                        "logsSubscribe",

                    "params": [

                        {
                            "mentions":
                                [
                                    RAYDIUM_PROGRAM_ID
                                ]
                        },

                        {
                            "commitment":
                                "confirmed"
                        },

                    ],

                }


                await ws.send(
                    json.dumps(
                        request
                    )
                )


                backoff = 2


                async for raw in ws:

                    last_heartbeat = time.time()


                    try:

                        message = json.loads(
                            raw
                        )

                    except json.JSONDecodeError:

                        continue


                    params = (
                        message.get(
                            "params"
                        )
                        or {}
                    )


                    result = (
                        params.get(
                            "result"
                        )
                        or {}
                    )


                    value = (
                        result.get(
                            "value"
                        )
                        or {}
                    )


                    signature = value.get(
                        "signature"
                    )


                    if not signature:

                        continue


                    if signature in seen_signatures:

                        continue


                    seen_signatures.add(
                        signature
                    )


                    if len(
                        seen_signatures
                    ) > 50000:

                        seen_signatures.clear()


                    asyncio.create_task(

                        process_transaction_signature(

                            signature,

                            "raydium"

                        )

                    )


        except asyncio.CancelledError:

            raise


        except Exception as exc:

            logger.warning(
                "Solana WS disconnected: %s",
                exc
            )


            await asyncio.sleep(
                backoff
            )


            backoff = min(
                backoff * 2,
                60
            )


async def process_transaction_signature(
    signature,
    source
):

    tx = await get_transaction(
        signature
    )


    if not tx:

        return


    mints = extract_mints_from_transaction(
        tx
    )


    for mint in mints:

        await discover_mint(
            mint,
            source
        )


def extract_mints_from_transaction(
    tx
):

    found = set()


    meta = (
        tx.get(
            "meta"
        )
        or {}
    )


    # Primary path:
    # token balances are safer than scanning every account.

    for balance_group in (

        meta.get(
            "preTokenBalances"
        )
        or [],

        meta.get(
            "postTokenBalances"
        )
        or [],

    ):

        for item in balance_group:

            mint = item.get(
                "mint"
            )


            if mint:

                found.add(
                    mint
                )


    # Secondary path:
    # parsed initializeMint instructions.

    message = (

        tx.get(
            "transaction"
        )

        or {}

    ).get(
        "message",
        {}
    )


    instructions = (
        message.get(
            "instructions"
        )
        or []
    )


    for instruction in instructions:

        parsed = instruction.get(
            "parsed"
        )


        if not isinstance(
            parsed,
            dict
        ):

            continue


        if parsed.get(
            "type"
        ) in {

            "initializeMint",

            "initializeMint2",

        }:

            info = (
                parsed.get(
                    "info"
                )
                or {}
            )


            mint = info.get(
                "mint"
            )


            if mint:

                found.add(
                    mint
                )


    return list(
        found
    )


# ============================================================
# DISCOVERY / ENRICHMENT
# ============================================================

async def discover_mint(
    mint,
    source
):

    if not mint:

        return


    if len(mint) < 32:

        return


    if mint in seen_mints:

        return


    seen_mints.add(
        mint
    )


    if len(
        seen_mints
    ) > 100000:

        seen_mints.clear()


    reset_daily_stats_if_needed()


    daily_stats[
        "new_mints"
    ] += 1


    snapshot = await fetch_market_data(
        mint
    )


    if not snapshot:

        return


    snapshot.source = source

    snapshot.created_at = time.time()


    await evaluate_and_store(
        snapshot
    )


async def configured_source_loop():

    global last_source_refresh


    while True:

        try:

            discoveries = (
                await discover_configured_http_sources()
            )


            for mint, source in discoveries:

                if mint not in seen_mints:

                    await discover_mint(
                        mint,
                        source
                    )


            last_source_refresh = time.time()


        except asyncio.CancelledError:

            raise


        except Exception as exc:

            logger.warning(
                "Configured source loop error: %s",
                exc
            )


        await asyncio.sleep(
            SOURCE_REFRESH_INTERVAL
        )


async def market_refresh_loop():

    while True:

        try:

            mints = list(
                candidates.keys()
            )


            for mint in mints[:300]:

                snapshot = (
                    await fetch_market_data(
                        mint
                    )
                )


                if snapshot:

                    await evaluate_and_store(

                        snapshot,

                        send_alert=False

                    )


                await asyncio.sleep(
                    0.05
                )


        except asyncio.CancelledError:

            raise


        except Exception as exc:

            logger.warning(
                "Market refresh error: %s",
                exc
            )


        await asyncio.sleep(
            DEX_INTERVAL
        )


# ============================================================
# SECURITY ANALYSIS
# ============================================================

def security_analysis(
    snapshot
):

    score = 50.0

    evidence = []

    warnings = []


    # --------------------------------------------------------
    # LIQUIDITY
    # --------------------------------------------------------

    if snapshot.liquidity >= 100_000:

        score += 30

        evidence.append(
            "سيولة قوية جدًا"
        )

    elif snapshot.liquidity >= 50_000:

        score += 22

        evidence.append(
            "سيولة قوية"
        )

    elif snapshot.liquidity >= MIN_LIQUIDITY:

        score += 12

        evidence.append(
            "السيولة فوق الحد الأدنى"
        )

    else:

        score -= 35

        warnings.append(
            "السيولة ضعيفة"
        )


    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    if snapshot.volume_5m >= 50_000:

        score += 15

        evidence.append(
            "حجم 5 دقائق قوي"
        )

    elif snapshot.volume_5m >= MIN_VOLUME_5M:

        score += 8

        evidence.append(
            "حجم 5 دقائق مقبول"
        )

    else:

        score -= 15

        warnings.append(
            "حجم التداول ضعيف"
        )


    # --------------------------------------------------------
    # ACTIVITY
    # --------------------------------------------------------

    total = (
        snapshot.buys_5m
        + snapshot.sells_5m
    )


    if total >= 20:

        score += 10

        evidence.append(
            "نشاط تداول واضح"
        )

    elif total >= 10:

        score += 5

        evidence.append(
            "نشاط تداول موجود"
        )

    else:

        score -= 10

        warnings.append(
            "نشاط التداول منخفض"
        )


    # --------------------------------------------------------
    # MINT AUTHORITY
    # --------------------------------------------------------

    if snapshot.mint_authority == "__UNKNOWN__":

        warnings.append(
            "حالة Mint Authority غير مؤكدة"
        )

    elif snapshot.mint_authority:

        score -= 12

        warnings.append(
            "Mint Authority ما زالت موجودة"
        )

    else:

        score += 6

        evidence.append(
            "Mint Authority غير موجودة"
        )


    # --------------------------------------------------------
    # FREEZE AUTHORITY
    # --------------------------------------------------------

    if snapshot.freeze_authority == "__UNKNOWN__":

        warnings.append(
            "حالة Freeze Authority غير مؤكدة"
        )

    elif snapshot.freeze_authority:

        score -= 18

        warnings.append(
            "Freeze Authority ما زالت موجودة"
        )

    else:

        score += 8

        evidence.append(
            "Freeze Authority غير موجودة"
        )


    # --------------------------------------------------------
    # TURNOVER RISK
    # --------------------------------------------------------

    if snapshot.liquidity > 0:

        turnover = (
            snapshot.volume_5m
            / snapshot.liquidity
        )


        if turnover >= 2:

            score -= 8

            warnings.append(
                "حجم ضخم مقارنة بالسيولة"
            )


    return (

        max(
            0,
            min(
                100,
                score
            )
        ),

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


        if buy_ratio >= 0.70:

            score += 28

            evidence.append(
                "ضغط شراء قوي جدًا"
            )

        elif buy_ratio >= 0.60:

            score += 18

            evidence.append(
                "ضغط شراء إيجابي"
            )

        elif buy_ratio <= 0.30:

            score -= 28

            warnings.append(
                "ضغط بيع مرتفع"
            )

        elif buy_ratio <= 0.40:

            score -= 15

            warnings.append(
                "الشراء ضعيف"
            )


    if snapshot.price_change_5m > 0:

        score += min(
            15,
            snapshot.price_change_5m / 4
        )

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
            "ارتفاع شديد يحتاج حذرًا"
        )


    if snapshot.price_change_1h > 0:

        score += 5


    return (

        max(
            0,
            min(
                100,
                score
            )
        ),

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

        score += 18

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


    if snapshot.liquidity > 0:

        turnover = (
            snapshot.volume_5m
            / snapshot.liquidity
        )


        if turnover >= 2:

            score -= 15

            warnings.append(
                "دوران تداول مرتفع جدًا مقابل السيولة"
            )

        elif turnover >= 1:

            score -= 5

            warnings.append(
                "دوران تداول مرتفع مقابل السيولة"
            )


    if (

        snapshot.price_change_5m > 0

        and

        snapshot.buys_5m
        > snapshot.sells_5m

    ):

        score += 12

        evidence.append(
            "السعر والشراء متوافقان"
        )


    if (

        snapshot.price_change_5m < 0

        and

        snapshot.sells_5m
        > snapshot.buys_5m

    ):

        score -= 15

        warnings.append(
            "السعر والبيع متوافقان في اتجاه سلبي"
        )


    return (

        max(
            0,
            min(
                100,
                score
            )
        ),

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


    if snapshot.liquidity >= 100_000:

        score += 20

        evidence.append(
            "سيولة تسمح بنشاط كبير"
        )


    if snapshot.volume_5m >= 50_000:

        score += 20

        evidence.append(
            "حجم تداول كبير"
        )


    if (

        snapshot.buys_5m >= 30

        and

        snapshot.buys_5m
        > snapshot.sells_5m

    ):

        score += 30

        evidence.append(
            "نشاط شراء كبير ومتكرر"
        )


    if (

        snapshot.sells_5m >= 30

        and

        snapshot.sells_5m
        > snapshot.buys_5m

    ):

        score += 10

        evidence.append(
            "نشاط بيع كبير"
        )


    if (

        snapshot.price_change_5m > 0

        and

        snapshot.buys_5m
        > snapshot.sells_5m

    ):

        score += 20

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


# ============================================================
# UNIFIED ANALYZER
# ============================================================

def analyze_snapshot(
    snapshot
):

    security, sec_ev, sec_warn = (
        security_analysis(
            snapshot
        )
    )


    market, market_ev, market_warn = (
        market_analysis(
            snapshot
        )
    )


    behavior, behavior_ev, behavior_warn = (
        behavior_analysis(
            snapshot
        )
    )


    whale, whale_ev = (
        whale_analysis(
            snapshot
        )
    )


    final_score = (

        security * 0.45

        + market * 0.35

        + behavior * 0.20

    )


    diamond_score = (

        final_score * 0.70

        + whale * 0.30

    )


    evidence = list(
        dict.fromkeys(
            sec_ev
            + market_ev
            + behavior_ev
            + whale_ev
        )
    )


    warnings = list(
        dict.fromkeys(
            sec_warn
            + market_warn
            + behavior_warn
        )
    )


    # --------------------------------------------------------
    # STRICT GOLD GATE
    # --------------------------------------------------------

    if snapshot.liquidity < MIN_LIQUIDITY:

        return None


    if security < 60:

        return None


    if final_score < MIN_GOLD_SCORE:

        return None


    status = "GOLD"


    if (
        diamond_score
        >= MIN_DIAMOND_SCORE
    ):

        status = "DIAMOND"


    return Candidate(

        snapshot=snapshot,

        security_score=round(
            security,
            2
        ),

        market_score=round(
            market,
            2
        ),

        behavior_score=round(
            behavior,
            2
        ),

        whale_score=round(
            whale,
            2
        ),

        final_score=round(
            final_score,
            2
        ),

        diamond_score=round(
            diamond_score,
            2
        ),

        status=status,

        evidence=evidence,

        warnings=warnings

    )


# ============================================================
# CANDIDATE STATE
# ============================================================

def candidate_changed(
    old,
    new
):

    if old is None:

        return True


    if old.status != new.status:

        return True


    if abs(
        old.final_score
        - new.final_score
    ) >= 5:

        return True


    if abs(
        old.diamond_score
        - new.diamond_score
    ) >= 5:

        return True


    return False


async def evaluate_and_store(
    snapshot,
    send_alert=True
):

    reset_daily_stats_if_needed()


    old = candidates.get(
        snapshot.mint
    )


    new_candidate = analyze_snapshot(
        snapshot
    )


    # If a previously good candidate temporarily
    # loses the strict gate, keep the historical object.
    if new_candidate is None:

        if old:

            old.snapshot = snapshot

            old.last_seen = time.time()

            old.updates += 1

        return None


    if old:

        new_candidate.first_seen = (
            old.first_seen
        )

        new_candidate.updates = (
            old.updates + 1
        )


    new_candidate.last_seen = time.time()


    candidates[
        snapshot.mint
    ] = new_candidate


    if len(candidates) > MAX_CANDIDATES:

        oldest = sorted(

            candidates.items(),

            key=lambda item:
                item[1].last_seen

        )[
            :len(candidates)
            - MAX_CANDIDATES
        ]


        for mint, _ in oldest:

            candidates.pop(
                mint,
                None
            )


    daily_stats[
        "events"
    ] += 1


    hourly_stats[
        current_hour()
    ][
        "events"
    ] += 1


    if new_candidate.status == "GOLD":

        daily_stats[
            "gold"
        ] += 1

        hourly_stats[
            current_hour()
        ][
            "gold"
        ] += 1


    elif new_candidate.status == "DIAMOND":

        daily_stats[
            "diamond"
        ] += 1

        hourly_stats[
            current_hour()
        ][
            "diamond"
        ] += 1


    archive.append(

        {

            "type":
                "candidate",

            "timestamp":
                time.time(),

            "status":
                new_candidate.status,

            "mint":
                snapshot.mint,

            "score":
                new_candidate.final_score,

            "diamond_score":
                new_candidate.diamond_score,

            "source":
                snapshot.source,

        }

    )


    # --------------------------------------------------------
    # TELEGRAM FOCUS LOCK
    # --------------------------------------------------------

    if (

        send_alert

        and

        radar_active

        and

        not position_active

    ):

        if (

            old is None

            or

            candidate_changed(
                old,
                new_candidate
            )

        ):

            await send_candidate(
                new_candidate
            )


    return new_candidate


# ============================================================
# BEST CANDIDATE
# ============================================================

def best_candidate():

    valid = list(
        candidates.values()
    )


    if not valid:

        return None


    valid.sort(

        key=lambda candidate: (

            candidate.diamond_score,

            candidate.final_score,

            candidate.whale_score,

            candidate.snapshot.liquidity,

            candidate.snapshot.volume_5m,

        ),

        reverse=True

    )


    return valid[0]


# ============================================================
# FLOW ENGINE
# ============================================================

def record_flow(

    mint,

    kind,

    value_usd,

    source,

    details=""

):

    event = FlowEvent(

        mint=mint,

        kind=kind,

        value_usd=max(
            0.0,
            safe_float(
                value_usd
            )
        ),

        source=source,

        details=details,

    )


    flow_history.append(
        asdict(
            event
        )
    )


    hour = current_hour()


    if kind == "in":

        hourly_stats[
            hour
        ][
            "flow_in"
        ] += event.value_usd


    elif kind == "out":

        hourly_stats[
            hour
        ][
            "flow_out"
        ] += event.value_usd


    if event.value_usd > 0:

        hourly_stats[
            hour
        ][
            "volume"
        ] += event.value_usd


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

            "⏹️ انتهاء الجلسة",

            callback_data=
                "finish_position"

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
            "💎 **DIAMOND — تطور قوي في الأدلة**"
        )

    else:

        title = (
            "🥇 **GOLD — مرشح مبكر**"
        )


    evidence_text = "\n".join(

        "• " + item

        for item
        in candidate.evidence[:8]

    )


    warning_text = "\n".join(

        "• " + item

        for item
        in candidate.warnings[:6]

    )


    text = (

        f"{title}\n\n"

        f"🪙 **الرمز:** "
        f"`{token.symbol}`\n"

        f"🔑 **العقد:**\n"
        f"`{token.mint}`\n\n"

        f"🛡️ **الأمان:** "
        f"`{candidate.security_score}/100`\n"

        f"🏆 **Final:** "
        f"`{candidate.final_score}/100`\n"

        f"💎 **Diamond:** "
        f"`{candidate.diamond_score}/100`\n"

        f"🐋 **Whale:** "
        f"`{candidate.whale_score}/100`\n\n"

        f"💰 **السعر:** "
        f"`{money(token.price)}`\n"

        f"💧 **السيولة:** "
        f"`{money(token.liquidity)}`\n"

        f"📊 **Volume 5m:** "
        f"`{money(token.volume_5m)}`\n"

        f"📈 **Change 5m:** "
        f"`{pct(token.price_change_5m)}`\n"

        f"🟢 **Buy:** "
        f"`{token.buys_5m}`\n"

        f"🔴 **Sell:** "
        f"`{token.sells_5m}`\n"

        f"🏦 **DEX:** "
        f"`{token.dex_id or 'غير معروف'}`\n"

        f"🔭 **Source:** "
        f"`{token.source}`\n\n"

        f"🔎 **الأدلة:**\n"
        f"{evidence_text or 'لا توجد أدلة إضافية'}\n\n"

        f"⚠️ **التحذيرات:**\n"
        f"{warning_text or 'لا يوجد تحذير رئيسي'}\n\n"

        "⚠️ رصد آلي وليس ضمانًا للربح "
        "أو الأمان المطلق."

    )


    await send_message(

        text,

        reply_markup=
            candidate_keyboard(
                token.mint
            )

    )


# ============================================================
# GUARDIAN START
# ============================================================

async def start_position(
    mint
):

    global position_active
    global position_mint
    global position_entry_price
    global position_message_id
    global position_started_at
    global radar_active


    if position_active:

        await send_message(

            "⚠️ توجد جلسة Guardian "
            "نشطة بالفعل."

        )

        return


    snapshot = await fetch_market_data(
        mint
    )


    if (
        not snapshot
        or snapshot.price <= 0
    ):

        await send_message(

            "⚠️ **تعذر بدء Guardian.**\n"
            "لم تصل بيانات سوق حية صالحة للعقد."

        )

        return


    position_active = True

    position_mint = mint

    position_entry_price = (
        snapshot.price
    )

    position_started_at = (
        time.time()
    )


    # --------------------------------------------------------
    # FOCUS LOCK
    # --------------------------------------------------------
    #
    # During Guardian:
    # new candidate alerts are paused.
    #
    radar_active = False


    message = await send_message(

        "🛡️ **GUARDIAN بدأ**\n\n"

        f"🔑 العقد:\n"
        f"`{mint}`\n\n"

        f"💰 سعر بداية المراقبة:\n"
        f"`{money(snapshot.price)}`\n\n"

        "📡 الآن تتم مراقبة السعر "
        "والسيولة والشراء والبيع "
        "والتغيرات السريعة باستمرار.\n\n"

        "🔕 تم تعليق تنبيهات العملات الجديدة "
        "حتى تضغط «انتهاء الجلسة».\n\n"

        "⚠️ Guardian لا ينفذ شراء "
        "أو بيع تلقائيًا.",

        reply_markup=
            guardian_keyboard()

    )


    if message:

        position_message_id = (
            message.message_id
        )


# ============================================================
# GUARDIAN FINISH
# ============================================================

async def finish_position():

    global position_active
    global position_mint
    global position_entry_price
    global position_message_id
    global position_started_at
    global radar_active


    old_mint = position_mint


    position_active = False

    position_mint = None

    position_entry_price = None

    position_message_id = None

    position_started_at = None


    radar_active = True


    await send_message(

        "🟢 **انتهت جلسة Guardian.**\n\n"

        f"العقد السابق:\n"
        f"`{short_address(old_mint)}`\n\n"

        "▶️ عاد الرادار لإرسال "
        "الاكتشافات الجديدة فقط."

    )


# ============================================================
# GUARDIAN ENGINE
# ============================================================

async def guardian_loop():

    previous = None

    last_alert_time = 0.0


    while True:

        try:

            if (
                not position_active
                or not position_mint
            ):

                previous = None

                await asyncio.sleep(
                    GUARDIAN_INTERVAL
                )

                continue


            snapshot = await fetch_market_data(
                position_mint
            )


            if not snapshot:

                await asyncio.sleep(
                    GUARDIAN_INTERVAL
                )

                continue


            candidate = analyze_snapshot(
                snapshot
            )


            if candidate:

                old_candidate = candidates.get(
                    position_mint
                )


                if old_candidate:

                    candidate.first_seen = (
                        old_candidate.first_seen
                    )

                    candidate.updates = (
                        old_candidate.updates + 1
                    )


                candidates[
                    position_mint
                ] = candidate


            change = 0.0


            if (
                position_entry_price
                and position_entry_price > 0
            ):

                change = (

                    (
                        snapshot.price
                        - position_entry_price
                    )

                    / position_entry_price

                    * 100

                )


            danger = False

            danger_reasons = []


            # ------------------------------------------------
            # LIQUIDITY COLLAPSE
            # ------------------------------------------------

            if (
                snapshot.liquidity
                < MIN_LIQUIDITY * 0.60
            ):

                danger = True

                danger_reasons.append(
                    "انخفاض حاد في السيولة"
                )


            # ------------------------------------------------
            # FAST PRICE COLLAPSE
            # ------------------------------------------------

            if (
                snapshot.price_change_5m
                <= -15
            ):

                danger = True

                danger_reasons.append(
                    "هبوط سريع في 5 دقائق"
                )


            # ------------------------------------------------
            # SELL DOMINANCE
            # ------------------------------------------------

            if (

                snapshot.sells_5m
                > snapshot.buys_5m * 2

                and

                snapshot.sells_5m >= 10

            ):

                danger = True

                danger_reasons.append(
                    "تفوق بيع قوي"
                )


            if danger:

                daily_stats[
                    "danger"
                ] += 1


                daily_stats[
                    "guardian_alerts"
                ] += 1


                now = time.time()


                if (
                    now
                    - last_alert_time
                    >= 20
                ):

                    await send_message(

                        "🚨 **GUARDIAN ALERT**\n\n"

                        f"🔑 `{position_mint}`\n"

                        f"💰 السعر: "
                        f"`{money(snapshot.price)}`\n"

                        f"📉 من بداية الجلسة: "
                        f"`{pct(change)}`\n"

                        f"💧 السيولة: "
                        f"`{money(snapshot.liquidity)}`\n\n"

                        + "\n".join(

                            f"• {reason}"

                            for reason
                            in danger_reasons

                        )

                    )


                    last_alert_time = now


            # ------------------------------------------------
            # ESTIMATED FLOW
            # ------------------------------------------------

            if (

                previous

                and

                previous.liquidity > 0

                and

                snapshot.liquidity
                < previous.liquidity * 0.80

            ):

                record_flow(

                    position_mint,

                    "out",

                    max(

                        0,

                        previous.liquidity
                        - snapshot.liquidity

                    ),

                    "guardian",

                    "انخفاض تقديري في السيولة"

                )


            if (

                previous

                and

                snapshot.liquidity
                > previous.liquidity * 1.15

            ):

                record_flow(

                    position_mint,

                    "in",

                    (
                        snapshot.liquidity
                        - previous.liquidity
                    ),

                    "guardian",

                    "ارتفاع تقديري في السيولة"

                )


            previous = snapshot


            # ------------------------------------------------
            # DASHBOARD
            # ------------------------------------------------

            if position_started_at:

                elapsed_seconds = int(

                    time.time()
                    - position_started_at

                )

            else:

                elapsed_seconds = 0


            elapsed = (

                f"{elapsed_seconds // 60}m "
                f"{elapsed_seconds % 60}s"

            )


            status = (
                "🟢 مستقر/إيجابي"
            )


            if danger:

                status = "🔴 خطر"

            elif (

                candidate

                and

                candidate.status
                == "DIAMOND"

            ):

                status = "💎 Diamond"


            dashboard_guardian_cache.update(

                {

                    "mint":
                        position_mint,

                    "price":
                        snapshot.price,

                    "liquidity":
                        snapshot.liquidity,

                    "change":
                        change,

                    "buys_5m":
                        snapshot.buys_5m,

                    "sells_5m":
                        snapshot.sells_5m,

                    "status":
                        status,

                    "elapsed":
                        elapsed,

                    "updated":
                        time.time(),

                }

            )


            await asyncio.sleep(
                GUARDIAN_INTERVAL
            )


        except asyncio.CancelledError:

            raise


        except Exception as exc:

            logger.warning(
                "Guardian error: %s",
                exc
            )


            await asyncio.sleep(
                GUARDIAN_INTERVAL
            )


# ============================================================
# DAILY INTELLIGENCE REPORT
# ============================================================

def build_daily_report():

    reset_daily_stats_if_needed()


    peak_event_hour = max(

        range(24),

        key=lambda hour:
            hourly_stats[
                hour
            ][
                "events"
            ]

    )


    peak_flow_hour = max(

        range(24),

        key=lambda hour:

            (

                hourly_stats[
                    hour
                ][
                    "flow_in"
                ]

                +

                hourly_stats[
                    hour
                ][
                    "flow_out"
                ]

            )

    )


    peak_buy_hour = max(

        range(24),

        key=lambda hour:

            hourly_stats[
                hour
            ][
                "flow_in"
            ]

    )


    peak_sell_hour = max(

        range(24),

        key=lambda hour:

            hourly_stats[
                hour
            ][
                "flow_out"
            ]

    )


    best = best_candidate()


    rows = []


    rows.append(

        "📊 **SOLANA RADAR — التقرير اليومي**"

    )


    rows.append(

        f"🕐 التوقيت المحلي: `{LOCAL_TIMEZONE}`"

    )


    rows.append(

        f"🔭 اكتشافات جديدة: "
        f"`{daily_stats['new_mints']}`"

    )


    rows.append(

        f"🥇 Gold: `{daily_stats['gold']}` "
        f"| 💎 Diamond: "
        f"`{daily_stats['diamond']}`"

    )


    rows.append(

        f"⏰ أعلى نشاط: "
        f"`{peak_event_hour:02d}:00`"
        f"–"
        f"`{(peak_event_hour + 1) % 24:02d}:00`"

    )


    rows.append(

        f"💰 أقوى تدفق إجمالي: "
        f"`{peak_flow_hour:02d}:00`"
        f"–"
        f"`{(peak_flow_hour + 1) % 24:02d}:00`"

    )


    rows.append(

        f"🟢 أقوى دخول تقديري: "
        f"`{peak_buy_hour:02d}:00`"
        f"–"
        f"`{(peak_buy_hour + 1) % 24:02d}:00`"

    )


    rows.append(

        f"🔴 أقوى خروج تقديري: "
        f"`{peak_sell_hour:02d}:00`"
        f"–"
        f"`{(peak_sell_hour + 1) % 24:02d}:00`"

    )


    rows.append(

        f"🚨 Guardian Alerts: "
        f"`{daily_stats['guardian_alerts']}`"

    )


    if best:

        rows.append(

            f"🏆 أفضل مرشح: "
            f"`{best.snapshot.symbol}` "
            f"— `{best.status}` "
            f"— Final `{best.final_score}/100`"

        )

    else:

        rows.append(
            "🏆 لم يوجد مرشح مؤهل محفوظ."
        )


    rows.append(

        f"🕐 آخر تحديث: "
        f"`{local_time_text()}`"

    )


    return "\n".join(
        rows
    )


async def daily_report_loop():

    global last_daily_report


    while True:

        try:

            reset_daily_stats_if_needed()


            now = local_now()


            target = now.replace(

                hour=23,

                minute=59,

                second=50,

                microsecond=0

            )


            if (

                now >= target

                and

                last_daily_report
                != daily_stats["date"]

            ):

                report = (
                    build_daily_report()
                )


                await send_message(
                    report
                )


                last_daily_report = (
                    daily_stats["date"]
                )


        except asyncio.CancelledError:

            raise


        except Exception as exc:

            logger.warning(
                "Daily report error: %s",
                exc
            )


        await asyncio.sleep(
            20
        )


# ============================================================
# WATCHDOG
# ============================================================

async def watchdog_loop():

    global last_heartbeat


    while True:

        try:

            now = time.time()


            if (

                last_heartbeat

                and

                now - last_heartbeat > 90

            ):

                logger.warning(

                    "Watchdog: "
                    "Solana WebSocket heartbeat "
                    "is stale."

                )


            logger.info(

                "ENGINE ALIVE | "
                "radar=%s | "
                "guardian=%s | "
                "candidates=%d | "
                "seen=%d | "
                "local=%s",

                radar_active,

                position_active,

                len(candidates),

                len(seen_mints),

                local_time_text()

            )


        except asyncio.CancelledError:

            raise


        except Exception as exc:

            logger.warning(
                "Watchdog error: %s",
                exc
            )


        await asyncio.sleep(
            30
        )


# ============================================================
# TELEGRAM CALLBACKS
# ============================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def telegram_callback(
    call
):

    try:

        data = call.data or ""


        # ----------------------------------------------------
        # COPY
        # ----------------------------------------------------

        if data.startswith(
            "copy:"
        ):

            mint = data.split(
                ":",
                1
            )[1]


            bot.answer_callback_query(

                call.id,

                "العقد ظاهر في الرسالة. "
                "اضغط مطولًا لنسخه.",

                show_alert=False

            )


            return


        # ----------------------------------------------------
        # DETAILS
        # ----------------------------------------------------

        if data.startswith(
            "details:"
        ):

            mint = data.split(
                ":",
                1
            )[1]


            candidate = candidates.get(
                mint
            )


            if not candidate:

                bot.answer_callback_query(

                    call.id,

                    "لا توجد بيانات حديثة.",

                    show_alert=True

                )

                return


            token = (
                candidate.snapshot
            )


            mint_auth = (

                "غير مؤكدة"

                if token.mint_authority
                == "__UNKNOWN__"

                else (

                    "موجودة"

                    if token.mint_authority

                    else

                    "غير موجودة"

                )

            )


            freeze_auth = (

                "غير مؤكدة"

                if token.freeze_authority
                == "__UNKNOWN__"

                else (

                    "موجودة"

                    if token.freeze_authority

                    else

                    "غير موجودة"

                )

            )


            text = (

                "🔎 **تفاصيل المرشح**\n\n"

                f"الرمز: `{token.symbol}`\n"

                f"العقد: `{token.mint}`\n"

                f"Security: "
                f"`{candidate.security_score}`\n"

                f"Market: "
                f"`{candidate.market_score}`\n"

                f"Behavior: "
                f"`{candidate.behavior_score}`\n"

                f"Whale: "
                f"`{candidate.whale_score}`\n"

                f"Final: "
                f"`{candidate.final_score}`\n"

                f"Diamond: "
                f"`{candidate.diamond_score}`\n"

                f"Source: "
                f"`{token.source}`\n"

                f"DEX: "
                f"`{token.dex_id}`\n"

                f"Mint Authority: "
                f"`{mint_auth}`\n"

                f"Freeze Authority: "
                f"`{freeze_auth}`"

            )


            bot.send_message(

                CHAT_ID,

                text,

                disable_web_page_preview=True

            )


            bot.answer_callback_query(
                call.id
            )


            return


        # ----------------------------------------------------
        # BUY / GUARDIAN
        # ----------------------------------------------------

        if data.startswith(
            "buy:"
        ):

            mint = data.split(
                ":",
                1
            )[1]


            bot.answer_callback_query(

                call.id,

                "تم تفعيل Guardian.",

                show_alert=False

            )


            if event_loop:

                asyncio.run_coroutine_threadsafe(

                    start_position(
                        mint
                    ),

                    event_loop

                )


            return


        # ----------------------------------------------------
        # FINISH
        # ----------------------------------------------------

        if data == "finish_position":

            bot.answer_callback_query(

                call.id,

                "تم إنهاء الجلسة.",

                show_alert=False

            )


            if event_loop:

                asyncio.run_coroutine_threadsafe(

                    finish_position(),

                    event_loop

                )


            return


        bot.answer_callback_query(
            call.id
        )


    except Exception as exc:

        logger.warning(

            "Telegram callback error: %s",

            exc

        )


# ============================================================
# TELEGRAM POLLING THREAD
# ============================================================

def telegram_polling_thread():

    while True:

        try:

            logger.info(
                "Telegram polling started"
            )


            bot.infinity_polling(

                timeout=30,

                long_polling_timeout=30,

                skip_pending=True

            )


        except Exception as exc:

            logger.warning(

                "Telegram polling stopped: %s",

                exc

            )


            time.sleep(
                5
            )


# ============================================================
# DASHBOARD
# ============================================================

DASHBOARD_HTML = r"""
<!doctype html>

<html lang="ar" dir="rtl">

<head>

<meta charset="utf-8">

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<title>SOLANA RADAR V2</title>

<style>

body{

font-family:Arial,sans-serif;

margin:0;

padding:20px;

background:#111;

color:#eee;

}

.card{

background:#1d1d1d;

border-radius:12px;

padding:16px;

margin-bottom:12px;

}

.grid{

display:grid;

grid-template-columns:
repeat(
auto-fit,
minmax(
180px,
1fr
)
);

gap:12px;

}

.big{

font-size:28px;

font-weight:bold;

}

.good{

color:#6ee7b7;

}

.warn{

color:#fbbf24;

}

.bad{

color:#fb7185;

}

.muted{

color:#aaa;

}

table{

width:100%;

border-collapse:collapse;

}

td,th{

padding:8px;

border-bottom:
1px solid #333;

text-align:right;

}

code{

word-break:break-all;

}

</style>

</head>

<body>

<h1>
🛰️ SOLANA RADAR V2
</h1>

<div class="grid">

<div class="card">

<div class="muted">
المحرك
</div>

<div
id="engine"
class="big"
>
...
</div>

</div>


<div class="card">

<div class="muted">
Guardian
</div>

<div
id="guardian"
class="big"
>
...
</div>

</div>


<div class="card">

<div class="muted">
Candidates
</div>

<div
id="candidates"
class="big"
>
0
</div>

</div>


<div class="card">

<div class="muted">
Seen Mints
</div>

<div
id="seen"
class="big"
>
0
</div>

</div>

</div>


<div class="card">

<h2>
🛡️ Guardian Live
</h2>

<div id="guardian_box">
لا توجد جلسة
</div>

</div>


<div class="card">

<h2>
🏆 أفضل مرشح
</h2>

<div id="best">
لا يوجد
</div>

</div>


<div class="card">

<h2>
⏱️ آخر تحديث
</h2>

<div id="time">
...
</div>

</div>


<script>

async function refresh(){

try{

const r =
await fetch(
'/api/state'
);

const d =
await r.json();


document.getElementById(
'engine'
).textContent =

d.radar_active
? 'RUNNING'
: 'FOCUS';


document.getElementById(
'guardian'
).textContent =

d.position_active
? 'ACTIVE'
: 'IDLE';


document.getElementById(
'candidates'
).textContent =
d.candidates;


document.getElementById(
'seen'
).textContent =
d.seen_mints;


document.getElementById(
'time'
).textContent =
d.local_time;


const g =
d.guardian;


if(
g &&
g.mint
){

document.getElementById(
'guardian_box'
).innerHTML =

'<b>'
+ g.status
+ '</b><br>'

+

'Contract: <code>'
+ g.mint
+ '</code><br>'

+

'Price: '
+ g.price
+ '<br>'

+

'Liquidity: '
+ g.liquidity
+ '<br>'

+

'Session change: '
+ g.change
+ '<br>'

+

'Buy 5m: '
+ g.buys_5m
+ ' | Sell 5m: '
+ g.sells_5m

+

'<br>Elapsed: '
+ g.elapsed;

}

else{

document.getElementById(
'guardian_box'
).textContent =
'لا توجد جلسة';

}


const b =
d.best;


if(b){

document.getElementById(
'best'
).innerHTML =

'<b>'
+ b.status
+ ' — '
+ b.symbol
+ '</b><br>'

+

'Contract: <code>'
+ b.mint
+ '</code><br>'

+

'Final: '
+ b.final_score

+

' | Diamond: '
+ b.diamond_score

+

' | Security: '
+ b.security_score

+

'<br>Liquidity: '
+ b.liquidity

+

' | Volume 5m: '
+ b.volume_5m;

}

else{

document.getElementById(
'best'
).textContent =
'لا يوجد';

}


}

catch(e){

document.getElementById(
'engine'
).textContent =
'ERROR';

}

}


setInterval(
refresh,
2000
);

refresh();

</script>

</body>

</html>
"""


async def dashboard_index(
    request
):

    return web.Response(

        text=DASHBOARD_HTML,

        content_type="text/html"

    )


async def dashboard_state(
    request
):

    best = best_candidate()


    payload = {

        "app":
            APP_NAME,

        "version":
            VERSION,

        "radar_active":
            radar_active,

        "position_active":
            position_active,

        "candidates":
            len(candidates),

        "seen_mints":
            len(seen_mints),

        "local_time":
            local_time_text(),

        "timezone":
            LOCAL_TIMEZONE,

        "guardian": {

            **dashboard_guardian_cache,

            "price":
                money(
                    dashboard_guardian_cache[
                        "price"
                    ]
                ),

            "liquidity":
                money(
                    dashboard_guardian_cache[
                        "liquidity"
                    ]
                ),

            "change":
                pct(
                    dashboard_guardian_cache[
                        "change"
                    ]
                ),

        },

        "best":
            None,

    }


    if best:

        payload[
            "best"
        ] = {

            "status":
                best.status,

            "symbol":
                best.snapshot.symbol,

            "mint":
                best.snapshot.mint,

            "final_score":
                best.final_score,

            "diamond_score":
                best.diamond_score,

            "security_score":
                best.security_score,

            "liquidity":
                money(
                    best.snapshot.liquidity
                ),

            "volume_5m":
                money(
                    best.snapshot.volume_5m
                ),

        }


    return web.json_response(
        payload
    )


async def start_dashboard():

    global dashboard_runner


    app = web.Application()


    app.router.add_get(
        "/",
        dashboard_index
    )


    app.router.add_get(
        "/api/state",
        dashboard_state
    )


    dashboard_runner = (
        web.AppRunner(
            app
        )
    )


    await dashboard_runner.setup()


    site = web.TCPSite(

        dashboard_runner,

        DASHBOARD_HOST,

        DASHBOARD_PORT

    )


    await site.start()


    logger.info(

        "Dashboard listening on "
        "http://%s:%s",

        DASHBOARD_HOST,

        DASHBOARD_PORT

    )


# ============================================================
# STARTUP MESSAGE
# ============================================================

async def startup_message():

    pump_status = (

        "ON"

        if PUMPPORTAL_API_KEY

        else

        "OFF - API key not configured"

    )


    await send_message(

        "🛰️ **SOLANA RADAR V2 بدأ التشغيل**\n\n"

        f"⚙️ Version: `{VERSION}`\n"

        f"🌍 Local timezone: "
        f"`{LOCAL_TIMEZONE}`\n"

        f"💧 Min liquidity: "
        f"`{money(MIN_LIQUIDITY)}`\n"

        f"🏆 Gold threshold: "
        f"`{MIN_GOLD_SCORE}`\n"

        f"💎 Diamond threshold: "
        f"`{MIN_DIAMOND_SCORE}`\n\n"

        f"🚀 PumpPortal: `{pump_status}`\n"

        "🔭 Solana/Raydium discovery: ON\n"

        "🧩 Launchpad adapters: READY\n"

        "🧠 Security + Market + Behavior + Whale: ON\n"

        "🛡️ Guardian: MANUAL ACTIVATION\n"

        "🤖 Auto trading: DISABLED\n\n"

        "♻️ المحرك المستمر يعمل الآن."

    )


# ============================================================
# MAIN ENGINE
# ============================================================

async def main():

    global event_loop


    event_loop = (
        asyncio.get_running_loop()
    )


    reset_daily_stats_if_needed()


    register_sources()


    await start_dashboard()


    await startup_message()


    tasks = [

        asyncio.create_task(

            solana_log_stream(),

            name="solana_log_stream"

        ),

        asyncio.create_task(

            pumpportal_stream(),

            name="pumpportal_stream"

        ),

        asyncio.create_task(

            configured_source_loop(),

            name="configured_source_loop"

        ),

        asyncio.create_task(

            market_refresh_loop(),

            name="market_refresh_loop"

        ),

        asyncio.create_task(

            guardian_loop(),

            name="guardian_loop"

        ),

        asyncio.create_task(

            daily_report_loop(),

            name="daily_report_loop"

        ),

        asyncio.create_task(

            watchdog_loop(),

            name="watchdog_loop"

        ),

    ]


    try:

        await asyncio.gather(
            *tasks
        )


    finally:

        for task in tasks:

            task.cancel()


        await asyncio.gather(

            *tasks,

            return_exceptions=True

        )


        if dashboard_runner:

            await dashboard_runner.cleanup()


        if (
            http_session
            and
            not http_session.closed
        ):

            await http_session.close()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    logger.info(

        "%s %s starting...",

        APP_NAME,

        VERSION

    )


    threading.Thread(

        target=
            telegram_polling_thread,

        daemon=True,

        name=
            "telegram-polling"

    ).start()


    try:

        asyncio.run(
            main()
        )


    except KeyboardInterrupt:

        logger.info(
            "Stopped by user."
        )


    except Exception as exc:

        logger.exception(
            "Fatal engine error: %s",
            exc
        )

        raise
