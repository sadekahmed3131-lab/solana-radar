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

       
