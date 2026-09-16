import asyncio
import json
import os
import re
import time
import io
import datetime
import uuid
import base64
import hashlib
import hmac
import secrets
from urllib.parse import urlencode

import requests
import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
from aiohttp import web

from gen import (
    generer_tous_prononcables_batch,
    preparer_combinaisons_classiques_batch,
    generer_toutes_possibilites_batch,
    ADMIN_MAX_GENS
)

# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

OFFICIAL_GUILD_ID = 1320431531386208386

# ============================================================
# DISCORD OAUTH2 / SCRIPT ACCESS
# ============================================================

DISCORD_CLIENT_ID = os.getenv(
    "DISCORD_CLIENT_ID",
    ""
)

DISCORD_CLIENT_SECRET = os.getenv(
    "DISCORD_CLIENT_SECRET",
    ""
)

DISCORD_REDIRECT_URI = os.getenv(
    "DISCORD_REDIRECT_URI",
    "https://raykoserver.duckdns.org/auth/discord/callback"
)

DISCORD_REQUIRED_ROLE_ID = os.getenv(
    "DISCORD_REQUIRED_ROLE_ID",
    "1529910646135586988"
)

RAYKO_AUTH_SECRET = os.getenv(
    "RAYKO_AUTH_SECRET",
    ""
)

AUTH_BIND_HOST = os.getenv(
    "AUTH_BIND_HOST",
    "0.0.0.0"
)

AUTH_PORT = int(
    os.getenv(
        "AUTH_PORT",
        "8080"
    )
)

AUTH_PUBLIC_BASE_URL = os.getenv(
    "AUTH_PUBLIC_BASE_URL",
    "https://raykoserver.duckdns.org"
).rstrip("/")

AUTH_SESSION_TTL = 3600

AUTH_PENDING_TTL = 3600

USAGE_REPORT_CHANNEL_ID = 1544716859608269011

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

USAGE_REPORTED_USERS_FILE = os.path.join(
    BASE_DIR,
    "usage_reported_users.json"
)

USAGE_COUNTS_FILE = os.path.join(
    BASE_DIR,
    "usage_counts.json"
)

# ============================================================
# USERS KNOWN FILE
# ============================================================

USERS_KNOWN_FILE = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    "users_known.json"
)

OWNER_IDS = {
    792692623075704832,
    1524824906527805441,
    1457337019020742806,
}

RESULTS_FILE = "user_results.json"
BLACKLIST_FILE = "blacklist.json"
PROXIES_FILE = "proxy.txt"

BATCH_SIZE = 100

TARGET_STATUS_TEXT = "Rayko's Sniper #1"

REQUIRED_ROLE_ID = 1529910646135586988
FREE_ACCESS_ROLE_ID = 1529910646135586988

# ============================================================
# RATE LIMIT / STATUS CONFIG
# ============================================================

STATUS_UPDATE_INTERVAL = 2.0

MAX_DISPLAYED_FOUND = 10

# ============================================================
# LOCKS
# ============================================================

results_lock = asyncio.Lock()
blacklist_lock = asyncio.Lock()
users_known_lock = asyncio.Lock()

# ============================================================
# ETAT
# ============================================================

# {user_id: {platform: bool}}
active_checks = {}

# {user_id: timestamp}
cooldowns = {}

# ============================================================
# PLATEFORMES
# ============================================================

PLATFORMS_CONFIG = {
    "discord": ("Discord", "💬"),
    "minecraft": ("Minecraft", "🌿"),
    "roblox": ("Roblox", "🔴")
}

# ============================================================
# COMMAND TREE / PERMISSIONS
# ============================================================


class OwnerOnlyCommandTree(app_commands.CommandTree):

    # ========================================================
    # COMMANDES PUBLIQUES
    # ========================================================

    PUBLIC_COMMANDS = {
        "bots",
        "leaderboard",
        "help",
        "about",
        "stats",
        "cleardm",
    }

    # ========================================================
    # COMMANDES FREE ACCESS & OWNER / USER
    # ========================================================

    USER_COMMANDS = {
        "startcheck",
        "stopcheck",
        "usernames",
        "clearusernames",
    }

    # ========================================================
    # COMMANDES ADMIN
    # ========================================================

    ADMIN_COMMANDS = {
        "blacklist",
        "unblacklist",
        "adminclear",
        "grantvip",
        "revokevip",
        "grant",
    }

    # ========================================================
    # GLOBAL PERMISSION CHECK
    # ========================================================

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:

        command_name = (
            interaction.command.name
            if interaction.command is not None
            else None
        )

        user_id = interaction.user.id

        # ====================================================
        # BLACKLIST
        # ====================================================

        if await is_blacklisted(user_id):

            await self._deny(
                interaction,
                "🚫 You are blacklisted and cannot use this bot."
            )

            return False

        # ====================================================
        # COMMANDES PUBLIQUES
        # ====================================================

        if command_name in self.PUBLIC_COMMANDS:
            return True

        # ====================================================
        # COMMANDES ADMIN
        # ====================================================

        if command_name in self.ADMIN_COMMANDS:

            if is_admin(interaction):
                return True

            await self._deny(
                interaction,
                "❌ This command is restricted to administrators."
            )

            return False

        # ====================================================
        # COMMANDES USER / STARTCHECK (FreeAccess or Owner required)
        # ====================================================

        if command_name in self.USER_COMMANDS:

            if user_id in OWNER_IDS or has_free_access(interaction):
                return True

            await self._deny(
                interaction,
                "❌ You need the FreeAccess role to use this command."
            )

            return False

        # ====================================================
        # PAR DEFAUT = BLOQUE
        # ====================================================

        await self._deny(
            interaction,
            "❌ You do not have permission to use this command."
        )

        return False

    # ========================================================
    # DENY HELPER
    # ========================================================

    async def _deny(
        self,
        interaction,
        message
    ):

        try:

            if not interaction.response.is_done():

                await interaction.response.send_message(
                    message,
                    ephemeral=True
                )

            else:

                await interaction.followup.send(
                    message,
                    ephemeral=True
                )

        except discord.NotFound:

            print(
                "[ERROR] Permission response failed: "
                "interaction expired"
            )

        except discord.HTTPException as e:

            print(
                f"[ERROR] Permission response: {e}"
            )


# ============================================================
# DISCORD
# ============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.message_content = True
intents.dm_messages = True
intents.members = True
intents.presences = True

bot = commands.Bot(
    command_prefix="/",
    intents=intents,
    tree_cls=OwnerOnlyCommandTree,

    allowed_installs=app_commands.AppInstallationType(
        guild=True,
        user=True
    ),

    allowed_contexts=app_commands.AppCommandContext(
        guild=True,
        dm_channel=True,
        private_channel=True
    )
)

# ============================================================
# OAUTH2 ACCESS API
# ============================================================

auth_pending = {}
auth_runner = None


def load_users_known():
    try:
        if not os.path.exists(USERS_KNOWN_FILE):
            save_users_known({})
            return {}
        with open(USERS_KNOWN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"[ERROR] load_users_known: {e}")
    return {}


def save_users_known(data):
    try:
        temp_file = USERS_KNOWN_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(temp_file, USERS_KNOWN_FILE)
    except Exception as e:
        print(f"[ERROR] save_users_known: {e}")


async def async_load_users_known():
    async with users_known_lock:
        return await asyncio.to_thread(load_users_known)


async def async_save_users_known(data):
    async with users_known_lock:
        await asyncio.to_thread(save_users_known, data)


async def register_known_user(user_id):
    user_id_str = str(user_id)
    async with users_known_lock:
        data = await asyncio.to_thread(load_users_known)
        if user_id_str not in data:
            data[user_id_str] = {
                "first_authenticated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            await asyncio.to_thread(save_users_known, data)


def load_usage_reported_users():

    try:

        with open(
            USAGE_REPORTED_USERS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):

            return {
                str(user_id)
                for user_id in data
                if str(user_id).isdigit()
            }

    except Exception:
        pass

    return set()


usage_reported_users = load_usage_reported_users()


def save_usage_reported_users():

    temp_file = (
        USAGE_REPORTED_USERS_FILE +
        ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            sorted(usage_reported_users),
            f,
            indent=2
        )

    os.replace(
        temp_file,
        USAGE_REPORTED_USERS_FILE
    )


def get_total_bots_used(user_id):

    try:

        with open(
            USAGE_COUNTS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return max(
            0,
            int(
                data.get(
                    str(user_id),
                    0
                )
            )
        )

    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError
    ):

        return 0


def format_total_bots_used(total_bots_used):

    return (
        str(total_bots_used)
        if total_bots_used > 0
        else "None"
    )


async def send_first_verification_report(user_id):

    user_id = str(user_id).strip()

    if (
        not user_id.isdigit()
        or user_id in usage_reported_users
    ):

        return

    total_bots_used = get_total_bots_used(
        user_id
    )

    total_bots_text = format_total_bots_used(
        total_bots_used
    )

    try:

        channel = bot.get_channel(
            USAGE_REPORT_CHANNEL_ID
        )

        if channel is None:

            channel = await bot.fetch_channel(
                USAGE_REPORT_CHANNEL_ID
            )

        await channel.send(
            (
                f"<@{user_id}> connected and received access "
                f"to the script — Total bots used: "
                f"{total_bots_text}"
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True
            )
        )

        usage_reported_users.add(
            user_id
        )

        save_usage_reported_users()

        print(
            f"[AUTH] First verification report sent for "
            f"{user_id}: {total_bots_used} bots"
        )

    except Exception as error:

        print(
            f"[ERROR] First verification report: {error}"
        )


def _auth_response(
    data,
    status=200
):

    response = web.json_response(
        data,
        status=status
    )

    response.headers[
        "Access-Control-Allow-Origin"
    ] = "*"

    response.headers[
        "Cache-Control"
    ] = "no-store"

    return response


def _auth_configured():

    return all((
        DISCORD_CLIENT_ID,
        DISCORD_CLIENT_SECRET,
        DISCORD_REQUIRED_ROLE_ID.isdigit(),
        RAYKO_AUTH_SECRET
    ))


def _b64url_encode(value):

    return base64.urlsafe_b64encode(
        value
    ).rstrip(
        b"="
    ).decode(
        "ascii"
    )


def _b64url_decode(value):

    padding = "=" * (
        -len(value) % 4
    )

    return base64.urlsafe_b64decode(
        value + padding
    )


def create_access_token(user_id):

    payload = json.dumps(
        {
            "sub": str(user_id),
            "jti": secrets.token_hex(16),
            "exp": (
                int(time.time())
                + AUTH_SESSION_TTL
            ),
            "guild_id": str(
                OFFICIAL_GUILD_ID
            ),
            "role_id": DISCORD_REQUIRED_ROLE_ID
        },
        separators=(
            ",",
            ":"
        ),
        sort_keys=True
    ).encode(
        "utf-8"
    )

    payload_part = _b64url_encode(
        payload
    )

    signature = hmac.new(
        RAYKO_AUTH_SECRET.encode(
            "utf-8"
        ),
        payload_part.encode(
            "ascii"
        ),
        hashlib.sha256
    ).hexdigest()

    return (
        f"rayko-v1."
        f"{payload_part}."
        f"{signature}"
    )


def validate_access_token(token):

    if (
        not token
        or not RAYKO_AUTH_SECRET
    ):

        return None

    try:

        version, payload_part, signature = (
            token.split(
                ".",
                2
            )
        )

        if version != "rayko-v1":
            return None

        expected = hmac.new(
            RAYKO_AUTH_SECRET.encode(
                "utf-8"
            ),
            payload_part.encode(
                "ascii"
            ),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            signature,
            expected
        ):

            return None

        payload = json.loads(
            _b64url_decode(
                payload_part
            ).decode(
                "utf-8"
            )
        )

        if int(
            payload.get(
                "exp",
                0
            )
        ) <= int(
            time.time()
        ):

            return None

        if payload.get(
            "guild_id"
        ) != str(
            OFFICIAL_GUILD_ID
        ):

            return None

        if payload.get(
            "role_id"
        ) != DISCORD_REQUIRED_ROLE_ID:

            return None

        return payload

    except (
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        base64.binascii.Error
    ):

        return None


def _remove_expired_auth_requests():

    now = time.time()

    for ticket, entry in list(
        auth_pending.items()
    ):

        if (
            entry["created_at"]
            + AUTH_PENDING_TTL
            < now
        ):

            auth_pending.pop(
                ticket,
                None
            )


async def oauth_start(request):

    _remove_expired_auth_requests()

    if not _auth_configured():

        return _auth_response(
            {
                "error": (
                    "OAuth is not configured. Set "
                    "DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, "
                    "DISCORD_REQUIRED_ROLE_ID and RAYKO_AUTH_SECRET."
                )
            },
            status=503
        )

    ticket = secrets.token_urlsafe(
        32
    )

    state = secrets.token_urlsafe(
        32
    )

    auth_pending[ticket] = {
        "state": state,
        "created_at": time.time(),
        "result": None
    }

    query = urlencode(
        {
            "client_id": DISCORD_CLIENT_ID,
            "redirect_uri": DISCORD_REDIRECT_URI,
            "response_type": "code",
            "scope": "identify",
            "state": state
        }
    )

    return _auth_response(
        {
            "ticket": ticket,
            "auth_url": (
                "https://discord.com/oauth2/authorize?"
                f"{query}"
            )
        }
    )


def _oauth_window_page(message):

    safe_message = (
        message.replace(
            "&",
            "&amp;"
        )
        .replace(
            "<",
            "&lt;"
        )
        .replace(
            ">",
            "&gt;"
        )
    )

    return web.Response(
        text=(
            "<!doctype html><meta charset='utf-8'>"
            "<title>Rayko access</title>"
            "<style>body{background:#090511;color:#fff;font:16px"
            " system-ui;text-align:center;padding:48px}</style>"
            f"<p>{safe_message}</p>"
            "<p>You can close this window and return to the game.</p>"
        ),
        content_type="text/html"
    )


async def oauth_callback(request):

    _remove_expired_auth_requests()

    state = request.query.get(
        "state",
        ""
    )

    ticket = next(
        (
            current_ticket
            for current_ticket, entry
            in auth_pending.items()
            if entry["state"] == state
        ),
        None
    )

    if not ticket:

        return _oauth_window_page(
            "This authentication request has expired. Start again."
        )

    entry = auth_pending[ticket]

    error = request.query.get(
        "error"
    )

    if error:

        entry["result"] = {
            "status": "denied",
            "message": (
                "Discord authentication was cancelled."
            )
        }

        return _oauth_window_page(
            "Authentication cancelled."
        )

    code = request.query.get(
        "code"
    )

    if not code:

        entry["result"] = {
            "status": "denied",
            "message": (
                "Discord did not return an authorization code."
            )
        }

        return _oauth_window_page(
            "Authentication failed."
        )

    try:

        async with aiohttp.ClientSession() as session:

            async with session.post(
                "https://discord.com/api/v10/oauth2/token",
                data={
                    "client_id": DISCORD_CLIENT_ID,
                    "client_secret": DISCORD_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": DISCORD_REDIRECT_URI
                },
                timeout=aiohttp.ClientTimeout(
                    total=10
                )
            ) as token_response:

                if token_response.status != 200:

                    raise RuntimeError(
                        "Discord token exchange failed"
                    )

                token_data = await (
                    token_response.json()
                )

            oauth_token = token_data.get(
                "access_token"
            )

            if not oauth_token:

                raise RuntimeError(
                    "Discord returned no access token"
                )

            async with session.get(
                "https://discord.com/api/v10/users/@me",
                headers={
                    "Authorization":
                    f"Bearer {oauth_token}"
                },
                timeout=aiohttp.ClientTimeout(
                    total=10
                )
            ) as user_response:

                if user_response.status != 200:

                    raise RuntimeError(
                        "Discord identity lookup failed"
                    )

                user_data = await (
                    user_response.json()
                )

        guild = bot.get_guild(
            OFFICIAL_GUILD_ID
        )

        if guild is None:

            guild = await bot.fetch_guild(
                OFFICIAL_GUILD_ID
            )

        member = await guild.fetch_member(
            int(
                user_data["id"]
            )
        )

        role_ids = {
            str(role.id)
            for role in member.roles
        }

        if DISCORD_REQUIRED_ROLE_ID not in role_ids:

            entry["result"] = {
                "status": "denied",
                "message": (
                    "Your Discord account does not "
                    "have the required role."
                )
            }

            return _oauth_window_page(
                "Access denied: the required Discord role is missing."
            )

        await register_known_user(user_data["id"])

        entry["result"] = {
            "status": "approved",
            "token": create_access_token(
                user_data["id"]
            ),
            "username": (
                user_data.get("global_name")
                or user_data.get(
                    "username",
                    "Discord user"
                )
            )
        }

        return _oauth_window_page(
            "Access granted. Return to the game."
        )

    except discord.NotFound:

        entry["result"] = {
            "status": "denied",
            "message": (
                "Your Discord account is not "
                "in the official server."
            )
        }

        return _oauth_window_page(
            "Access denied: join the official Discord server first."
        )

    except Exception as error:

        print(
            f"[ERROR] Discord OAuth callback: {error}"
        )

        entry["result"] = {
            "status": "denied",
            "message": (
                "Unable to verify your Discord account right now."
            )
        }

        return _oauth_window_page(
            "Authentication failed. Try again in a moment."
        )


async def oauth_poll(request):

    _remove_expired_auth_requests()

    ticket = request.query.get(
        "ticket",
        ""
    )

    entry = auth_pending.get(
        ticket
    )

    if not entry:

        return _auth_response(
            {
                "status": "expired"
            },
            status=404
        )

    if entry["result"] is None:

        return _auth_response(
            {
                "status": "pending"
            }
        )

    result = entry["result"]

    auth_pending.pop(
        ticket,
        None
    )

    return _auth_response(
        result
    )


async def has_live_required_role(user_id):

    try:

        guild = bot.get_guild(
            OFFICIAL_GUILD_ID
        )

        if guild is None:

            guild = await bot.fetch_guild(
                OFFICIAL_GUILD_ID
            )

        member = await guild.fetch_member(
            int(user_id)
        )

        return DISCORD_REQUIRED_ROLE_ID in {
            str(role.id)
            for role in member.roles
        }

    except (
        discord.NotFound,
        discord.Forbidden,
        discord.HTTPException,
        ValueError,
        TypeError
    ):

        return False


async def oauth_validate(request):

    token = request.headers.get(
        "Authorization",
        ""
    )

    if token.lower().startswith(
        "bearer "
    ):

        token = token[7:].strip()

    if not token:

        try:

            body = await request.json()

            token = body.get(
                "token",
                ""
            )

        except Exception:

            token = ""

    payload = validate_access_token(
        token
    )

    if not payload:

        return _auth_response(
            {
                "valid": False
            },
            status=401
        )

    if not await has_live_required_role(
        payload["sub"]
    ):

        print(
            f"[AUTH] Live role check failed for "
            f"{payload['sub']}"
        )

        return _auth_response(
            {
                "valid": False,
                "reason": "missing_role"
            },
            status=403
        )

    await send_first_verification_report(
        payload["sub"]
    )

    return _auth_response(
        {
            "valid": True,
            "user_id": payload["sub"],
            "expires_at": payload["exp"]
        }
    )


async def usage_report(request):

    provided_secret = request.headers.get(
        "X-Rayko-Auth-Secret",
        ""
    )

    if (
        not RAYKO_AUTH_SECRET
        or not provided_secret
        or not hmac.compare_digest(
            provided_secret,
            RAYKO_AUTH_SECRET
        )
    ):

        return _auth_response(
            {
                "error": "Unauthorized"
            },
            status=401
        )

    try:

        data = await request.json()

        user_id = str(
            data.get(
                "user_id",
                ""
            )
        ).strip()

        total_bots_used = int(
            data.get(
                "total_bots_used",
                0
            )
        )

        if (
            not user_id.isdigit()
            or total_bots_used < 0
        ):

            raise ValueError(
                "Invalid usage report"
            )

        if user_id in usage_reported_users:

            return _auth_response(
                {
                    "ok": True,
                    "already_reported": True
                }
            )

        channel = bot.get_channel(
            USAGE_REPORT_CHANNEL_ID
        )

        if channel is None:

            channel = await bot.fetch_channel(
                USAGE_REPORT_CHANNEL_ID
            )

        await channel.send(
            (
                f"<@{user_id}> connected and received access "
                f"to the script — Total bots used: "
                f"{total_bots_used}"
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True
            )
        )

        usage_reported_users.add(
            user_id
        )

        save_usage_reported_users()

        print(
            f"[AUTH] Usage report sent for {user_id}: "
            f"{total_bots_used} bots"
        )

        return _auth_response(
            {
                "ok": True
            }
        )

    except Exception as error:

        print(
            f"[ERROR] Usage report: {error}"
        )

        return _auth_response(
            {
                "error": "Unable to send usage report"
            },
            status=500
        )


async def auth_health(request):

    return _auth_response(
        {
            "ok": True,
            "oauth_configured": _auth_configured(),
            "required_role_configured": (
                DISCORD_REQUIRED_ROLE_ID.isdigit()
            )
        }
    )


async def start_auth_api():

    global auth_runner

    if auth_runner is not None:
        return

    app = web.Application()

    app.add_routes(
        [
            web.get(
                "/auth/discord/start",
                oauth_start
            ),
            web.get(
                "/auth/discord/callback",
                oauth_callback
            ),
            web.get(
                "/auth/poll",
                oauth_poll
            ),
            web.post(
                "/auth/validate",
                oauth_validate
            ),
            web.post(
                "/auth/usage-report",
                usage_report
            ),
            web.get(
                "/auth/health",
                auth_health
            )
        ]
    )

    auth_runner = web.AppRunner(
        app
    )

    await auth_runner.setup()

    site = web.TCPSite(
        auth_runner,
        AUTH_BIND_HOST,
        AUTH_PORT
    )

    await site.start()

    print(
        f"[AUTH] OAuth API listening on "
        f"{AUTH_BIND_HOST}:{AUTH_PORT}"
    )


# ============================================================
# LOG
# ============================================================


def log_command(
    user,
    command_name
):

    now = datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    discriminator = ""

    if (
        hasattr(
            user,
            "discriminator"
        )
        and user.discriminator != "0"
    ):

        discriminator = (
            f"#{user.discriminator}"
        )

    print(
        f"[{now}] [COMMAND] "
        f"{user.name}{discriminator} "
        f"(ID: {user.id}) "
        f"executed command: /{command_name}"
    )


# ============================================================
# JSON
# ============================================================


def load_results():

    if not os.path.exists(
        RESULTS_FILE
    ):

        return {}

    try:

        with open(
            RESULTS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(
                data,
                dict
            ):

                return data

            return {}

    except Exception as e:

        print(
            f"[ERROR] load_results: {e}"
        )

        return {}


def save_results(data):

    try:

        temp_file = (
            RESULTS_FILE +
            ".tmp"
        )

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=4
            )

        os.replace(
            temp_file,
            RESULTS_FILE
        )

    except Exception as e:

        print(
            f"[ERROR] save_results: {e}"
        )


def load_blacklist():

    if not os.path.exists(
        BLACKLIST_FILE
    ):

        return []

    try:

        with open(
            BLACKLIST_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(
                data,
                list
            ):

                return data

            return []

    except Exception as e:

        print(
            f"[ERROR] load_blacklist: {e}"
        )

        return []


def save_blacklist(data):

    try:

        temp_file = (
            BLACKLIST_FILE +
            ".tmp"
        )

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=4
            )

        os.replace(
            temp_file,
            BLACKLIST_FILE
        )

    except Exception as e:

        print(
            f"[ERROR] save_blacklist: {e}"
        )


def load_proxies():

    if not os.path.exists(
        PROXIES_FILE
    ):

        return []

    try:

        with open(
            PROXIES_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return [
                line.strip()
                for line in f
                if line.strip()
                and not line.startswith("#")
            ]

    except Exception as e:

        print(
            f"[ERROR] load_proxies: {e}"
        )

        return []


# ============================================================
# ASYNC FILE HELPERS
# ============================================================


async def async_load_results():

    async with results_lock:

        return await asyncio.to_thread(
            load_results
        )


async def async_save_results(data):

    async with results_lock:

        await asyncio.to_thread(
            save_results,
            data
        )


async def async_load_blacklist():

    async with blacklist_lock:

        return await asyncio.to_thread(
            load_blacklist
        )


async def async_save_blacklist(data):

    async with blacklist_lock:

        await asyncio.to_thread(
            save_blacklist,
            data
        )


async def is_blacklisted(user_id):

    blacklist = await async_load_blacklist()

    return str(user_id) in blacklist


# ============================================================
# PROXY
# ============================================================


def formater_proxy_requests(
    proxy_str
):

    if not proxy_str:
        return None

    proxy_str = proxy_str.strip()

    parts = proxy_str.split(":")

    if len(parts) == 4:

        ip, port, user, pwd = parts

        return {
            "http": (
                f"http://{user}:{pwd}@{ip}:{port}"
            ),
            "https": (
                f"http://{user}:{pwd}@{ip}:{port}"
            )
        }

    if len(parts) == 2:

        return {
            "http": f"http://{proxy_str}",
            "https": f"http://{proxy_str}"
        }

    if (
        proxy_str.startswith("http://")
        or proxy_str.startswith("https://")
        or proxy_str.startswith("socks")
    ):

        return {
            "http": proxy_str,
            "https": proxy_str
        }

    return {
        "http": f"http://{proxy_str}",
        "https": f"http://{proxy_str}"
    }


def get_random_proxy(
    proxies_list
):

    if not proxies_list:
        return None

    import random

    return formater_proxy_requests(
        random.choice(
            proxies_list
        )
    )


# ============================================================
# DISCORD CHECK
# ============================================================


def check_discord_custom_sync(
    pseudo,
    use_proxies,
    proxies_list
):

    url = (
        "https://discord.com/api/v9/"
        "unique-username/username-attempt-unauthed"
    )

    reqheaders = {
        "Accept": "*/*",
        "Accept-Language": (
            "fr,fr-FR;q=0.8,"
            "en-US;q=0.5,en;q=0.3"
        ),
        "Content-Type": "application/json",
        "Origin": "https://discord.com",
        "Referer": "https://discord.com/register",
        "Cookie": (
            f"__dcfduid={str(uuid.uuid4())}"
        )
    }

    body = json.dumps({
        "username": pseudo
    })

    for attempt in range(3):

        try:

            proxies = (
                get_random_proxy(
                    proxies_list
                )
                if use_proxies
                else None
            )

            response = requests.post(
                url,
                headers=reqheaders,
                data=body,
                proxies=proxies,
                timeout=2
            )

            if response.status_code == 429:

                time.sleep(
                    min(
                        2 ** attempt,
                        5
                    )
                )

                continue

            if response.status_code == 400:

                return "pris"

            data = response.json()

            if "taken" in data:

                return (
                    "libre"
                    if not data["taken"]
                    else "pris"
                )

            return "pris"

        except requests.RequestException:

            if use_proxies:
                continue

            return "erreur"

        except Exception:

            return "erreur"

    return "erreur"


# ============================================================
# MINECRAFT
# ============================================================


async def check_minecraft_api(
    session,
    pseudo: str,
    proxy_str=None
):

    try:

        url = (
            "https://api.mojang.com/users/profiles/minecraft/"
            f"{pseudo}"
        )

        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(
                total=2
            )
        ) as response:

            if response.status in (
                204,
                404
            ):

                return "libre"

            if response.status == 200:

                return "pris"

        return "erreur"

    except Exception:

        return "erreur"


# ============================================================
# ROBLOX
# ============================================================


async def check_roblox_api(
    session,
    pseudo: str,
    proxy_str=None
):

    try:

        url = (
            "https://auth.roblox.com/v1/usernames/validate"
            f"?request.username={pseudo}"
            "&request.birthday=2000-01-01"
        )

        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(
                total=2
            )
        ) as response:

            if response.status != 200:

                return "erreur"

            data = await response.json()

            if data.get(
                "code"
            ) == 0:

                return "libre"

            return "pris"

    except Exception:

        return "erreur"


# ============================================================
# PERMISSIONS
# ============================================================


def is_admin(interaction):

    if not interaction.guild:

        return False

    member = interaction.user

    if getattr(
        member.guild_permissions,
        "administrator",
        False
    ):

        return True

    return any(
        "admin" in role.name.lower()
        for role in getattr(
            member,
            "roles",
            []
        )
    )


def has_free_access(interaction):
    if not interaction.guild:
        return False

    member = interaction.user
    if interaction.user.id in OWNER_IDS:
        return True

    if getattr(member.guild_permissions, "administrator", False):
        return True

    role_ids = {str(role.id) for role in getattr(member, "roles", [])}
    role_names = {role.name.lower() for role in getattr(member, "roles", [])}

    if str(FREE_ACCESS_ROLE_ID) in role_ids:
        return True

    return any("freeaccess" in r or "free access" in r for r in role_names)


def get_user_role_info(
    interaction
):

    if not interaction.guild:

        return (
            "Member",
            False,
            False
        )

    roles = [
        role.name.lower()
        for role in getattr(
            interaction.user,
            "roles",
            []
        )
    ]

    admin = (
        "administrator"
        if getattr(
            interaction.user.guild_permissions,
            "administrator",
            False
        )
        else any(
            "admin" in role
            for role in roles
        )
    )

    is_vip_user = any(
        "vip" in role
        for role in roles
    )

    if admin:

        return (
            "Admin",
            True,
            is_vip_user
        )

    if is_vip_user:

        return (
            "VIP",
            False,
            True
        )

    return (
        "Member",
        False,
        False
    )


# ============================================================
# SAFE DISCORD SEND
# ============================================================


async def safe_followup_send(
    interaction,
    *args,
    **kwargs
):

    try:

        return await interaction.followup.send(
            *args,
            **kwargs
        )

    except discord.HTTPException as e:

        if e.status == 429:

            retry_after = getattr(
                e,
                "retry_after",
                None
            )

            if retry_after is None:

                retry_after = 2

            retry_after = min(
                float(retry_after),
                10
            )

            print(
                "[RATE LIMIT] Discord webhook. "
                f"Waiting {retry_after:.2f}s"
            )

            await asyncio.sleep(
                retry_after
            )

            try:

                return await interaction.followup.send(
                    *args,
                    **kwargs
                )

            except discord.HTTPException as retry_error:

                print(
                    "[ERROR] Followup retry failed: "
                    f"{retry_error}"
                )

                return None

        print(
            f"[ERROR] Followup send: {e}"
        )

        return None


# ============================================================
# VIEWS
# ============================================================


class ConfirmClearView(
    discord.ui.View
):

    def __init__(
        self,
        user_id
    ):

        super().__init__(
            timeout=60
        )

        self.user_id = str(
            user_id
        )

    async def check_user(
        self,
        interaction
    ):

        if str(
            interaction.user.id
        ) != self.user_id:

            await interaction.response.send_message(
                "❌ Unauthorized action.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.danger,
        emoji="🗑️"
    )
    async def confirm(
        self,
        interaction,
        button
    ):

        if not await self.check_user(
            interaction
        ):

            return

        uid = str(
            interaction.user.id
        )

        async with results_lock:

            all_data = await asyncio.to_thread(
                load_results
            )

            if uid in all_data:

                all_data[uid] = {
                    key: []
                    for key in PLATFORMS_CONFIG
                }

                await asyncio.to_thread(
                    save_results,
                    all_data
                )

        for child in self.children:

            child.disabled = True

        await interaction.response.edit_message(
            content=(
                "🗑️ **History successfully cleared.**"
            ),
            view=self
        )

        self.stop()

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="❌"
    )
    async def cancel(
        self,
        interaction,
        button
    ):

        if not await self.check_user(
            interaction
        ):

            return

        for child in self.children:

            child.disabled = True

        await interaction.response.edit_message(
            content="❌ **Deletion cancelled.**",
            view=self
        )

        self.stop()


# ============================================================


class ConfirmStopAllView(
    discord.ui.View
):

    def __init__(
        self,
        user_id
    ):

        super().__init__(
            timeout=60
        )

        self.user_id = str(
            user_id
        )

    async def check_user(
        self,
        interaction
    ):

        if str(
            interaction.user.id
        ) != self.user_id:

            await interaction.response.send_message(
                "❌ Unauthorized action.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="Confirm Stop All",
        style=discord.ButtonStyle.danger,
        emoji="🛑"
    )
    async def confirm(
        self,
        interaction,
        button
    ):

        if not await self.check_user(
            interaction
        ):

            return

        uid = interaction.user.id

        if uid in active_checks:

            for platform in active_checks[uid]:

                active_checks[uid][platform] = False

        for child in self.children:

            child.disabled = True

        await interaction.response.edit_message(
            content=(
                "🛑 **All ongoing scans have been "
                "successfully stopped.**"
            ),
            view=self
        )

        self.stop()

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="❌"
    )
    async def cancel(
        self,
        interaction,
        button
    ):

        if not await self.check_user(
            interaction
        ):

            return

        for child in self.children:

            child.disabled = True

        await interaction.response.edit_message(
            content="❌ **Stop action cancelled.**",
            view=self
        )

        self.stop()


# ============================================================


class ResultsSelect(
    discord.ui.Select
):

    def __init__(
        self,
        results_dict
    ):

        options = []

        for key, (
            name,
            emoji
        ) in PLATFORMS_CONFIG.items():

            options.append(
                discord.SelectOption(
                    label=name,
                    description=(
                        f"{len(results_dict.get(key, []))} "
                        "available usernames"
                    ),
                    emoji=emoji,
                    value=key
                )
            )

        super().__init__(
            placeholder="📂 Select a platform...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        plat_key = self.values[0]

        all_data = await async_load_results()

        user_data = all_data.get(
            str(interaction.user.id),
            {
                key: []
                for key in PLATFORMS_CONFIG
            }
        )

        pseudos = user_data.get(
            plat_key,
            []
        )

        platform_name = (
            PLATFORMS_CONFIG[
                plat_key
            ][0]
        )

        if not pseudos:

            await safe_followup_send(
                interaction,
                f"❌ No usernames found for "
                f"**{platform_name}**.",
                ephemeral=True
            )

            return

        file_bytes = io.BytesIO(
            "\n".join(
                pseudos
            ).encode(
                "utf-8"
            )
        )

        discord_file = discord.File(
            file_bytes,
            filename=(
                f"{platform_name.lower()}_usernames.txt"
            )
        )

        try:

            await interaction.user.send(
                f"📂 **{platform_name}** usernames file:",
                file=discord_file
            )

            await safe_followup_send(
                interaction,
                "✅ File sent via Direct Message.",
                ephemeral=True
            )

        except Exception as e:

            print(
                f"[ERROR] ResultsSelect DM: {e}"
            )

            await safe_followup_send(
                interaction,
                "⚠️ Unable to send DM.",
                ephemeral=True
            )


class ResultsView(
    discord.ui.View
):

    def __init__(
        self,
        results_dict
    ):

        super().__init__(
            timeout=180
        )

        self.add_item(
            ResultsSelect(
                results_dict
            )
        )


# ============================================================


class PlatformSelect(
    discord.ui.Select
):

    def __init__(self):

        options = [

            discord.SelectOption(
                label="Minecraft",
                description="Scan Minecraft usernames",
                emoji="🌿",
                value="Minecraft"
            ),

            discord.SelectOption(
                label="Roblox",
                description="Scan Roblox usernames",
                emoji="🔴",
                value="Roblox"
            ),

            discord.SelectOption(
                label="Discord",
                description="Scan Discord usernames",
                emoji="💬",
                value="Discord"
            )

        ]

        super().__init__(
            placeholder="⚡ Choose a platform...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction
    ):

        await interaction.response.send_modal(
            CheckModal(
                self.values[0]
            )
        )


class PlatformView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=180
        )

        self.add_item(
            PlatformSelect()
        )


# ============================================================
# CHECK MODAL
# ============================================================


class CheckModal(
    discord.ui.Modal
):

    def __init__(
        self,
        chosen_platform
    ):

        super().__init__(
            title="Rayko's Sniper — Configuration"
        )

        self.chosen_platform = (
            chosen_platform
        )

        self.mode_gen = discord.ui.TextInput(
            label="1: Prono | 2: Random | 3: Bruteforce",
            placeholder="1, 2 or 3",
            default="2",
            max_length=1
        )

        self.length = discord.ui.TextInput(
            label="Length",
            placeholder="Ex: 4",
            default="4",
            max_length=2
        )

        self.numbers_mode = discord.ui.TextInput(
            label="Numbers? (1: Yes | 2: No)",
            placeholder="1 or 2",
            default="1",
            max_length=1
        )

        self.prefix = discord.ui.TextInput(
            label="Prefix (Optional)",
            placeholder="Ex: bo",
            required=False,
            max_length=10
        )

        self.proxy_mode = discord.ui.TextInput(
            label="Proxies? (1: Yes | 2: No)",
            placeholder="1 or 2",
            default="1",
            max_length=1
        )

        self.add_item(
            self.mode_gen
        )

        self.add_item(
            self.length
        )

        self.add_item(
            self.numbers_mode
        )

        self.add_item(
            self.prefix
        )

        self.add_item(
            self.proxy_mode
        )

    async def on_submit(
        self,
        interaction
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        log_command(
            interaction.user,
            "check"
        )

        # =====================================================
        # BLACKLIST
        # =====================================================

        if await is_blacklisted(
            interaction.user.id
        ):

            await safe_followup_send(
                interaction,
                "❌ You are banned from using this bot.",
                ephemeral=True
            )

            return

        # =====================================================
        # ROLE & LIMITS (FreeAccess = 1000 check limit per platform, 60s cooldown)
        # =====================================================

        role_name, is_admin_user, is_vip_user = (
            get_user_role_info(
                interaction
            )
        )

        if is_admin_user or interaction.user.id in OWNER_IDS:

            cooldown_time = 0
            max_gens = 999999

        elif is_vip_user:

            cooldown_time = 60
            max_gens = 999999

        elif has_free_access(interaction):

            cooldown_time = 60
            max_gens = 1000

        else:

            cooldown_time = 120
            max_gens = 1000

        # =====================================================
        # EMPÊCHER PLUSIEURS SCANS IDENTIQUES
        # =====================================================

        uid_int = interaction.user.id

        if (
            uid_int in active_checks
            and any(
                active_checks[
                    uid_int
                ].values()
            )
        ):

            await safe_followup_send(
                interaction,
                "⚠️ You already have an active scan.",
                ephemeral=True
            )

            return

        # =====================================================
        # COOLDOWN
        # =====================================================

        if (
            cooldown_time > 0
            and uid_int in cooldowns
        ):

            elapsed = (
                time.time()
                - cooldowns[uid_int]
            )

            if elapsed < cooldown_time:

                remaining = int(
                    cooldown_time
                    - elapsed
                )

                await safe_followup_send(
                    interaction,
                    (
                        "⏳ Please wait another "
                        f"**{remaining // 60}m "
                        f"{remaining % 60}s**."
                    ),
                    ephemeral=True
                )

                return

        # =====================================================
        # INPUT
        # =====================================================

        try:

            mode = int(
                self.mode_gen.value.strip()
            )

        except Exception:

            mode = 1

        if mode not in (
            1,
            2,
            3
        ):

            mode = 2

        try:

            length_val = int(
                self.length.value.strip()
            )

        except Exception:

            length_val = 4

        if length_val < 1:

            length_val = 1

        try:

            use_nums = (
                int(
                    self.numbers_mode.value.strip()
                ) == 1
            )

        except Exception:

            use_nums = False

        pref = (
            self.prefix.value.strip()
            if self.prefix.value
            else ""
        )

        try:

            use_prox = (
                int(
                    self.proxy_mode.value.strip()
                ) == 1
            )

        except Exception:

            use_prox = False

        # =====================================================
        # PLATEFORME
        # =====================================================

        plat_mapping = {
            "Minecraft": "minecraft",
            "Roblox": "roblox",
            "Discord": "discord"
        }

        plat = plat_mapping.get(
            self.chosen_platform,
            "discord"
        )

        platform_display_name = (
            PLATFORMS_CONFIG[
                plat
            ][0]
        )

        game_id = {
            "minecraft": 1,
            "roblox": 2,
            "discord": 3
        }[plat]

        # =====================================================
        # MESSAGE DE STATUS
        # =====================================================

        status_message = await safe_followup_send(
            interaction,
            (
                f"🚀 **Scan in progress "
                f"[{platform_display_name}]** "
                f"[{interaction.user}]\n"
                f"• Checked: `0`\n"
                f"• Found: `0`"
            ),
            wait=True
        )

        if status_message is None:

            print(
                "[ERROR] Unable to create status message."
            )

            return

        # =====================================================
        # ETAT DU SCAN
        # =====================================================

        if cooldown_time > 0:

            cooldowns[
                uid_int
            ] = time.time()

        if uid_int not in active_checks:

            active_checks[
                uid_int
            ] = {}

        active_checks[
            uid_int
        ][plat] = True

        found_count = 0
        total_checked = 0
        state_index = 0

        found_usernames = []

        user_id = str(
            interaction.user.id
        )

        empty_user_dict = {
            key: []
            for key in PLATFORMS_CONFIG
        }

        proxies_list = await asyncio.to_thread(
            load_proxies
        )

        # =====================================================
        # HTTP SESSION
        # =====================================================

        connector = aiohttp.TCPConnector(
            limit=100,
            ssl=False
        )

        timeout = aiohttp.ClientTimeout(
            total=10
        )

        # =====================================================
        # STATUS UPDATE HELPER
        # =====================================================

        last_status_update = 0.0

        async def update_status(
            force=False,
            finished=False
        ):

            nonlocal last_status_update

            now = time.monotonic()

            if (
                not force
                and now - last_status_update
                < STATUS_UPDATE_INTERVAL
            ):

                return

            last_status_update = now

            if finished:

                title = (
                    f"✅ **Verification completed "
                    f"[{platform_display_name}]**"
                )

            else:

                title = (
                    f"🚀 **Scan in progress "
                    f"[{platform_display_name}]** "
                    f"[{interaction.user}]"
                )

            content = (
                f"{title}\n"
                f"• Checked: `{total_checked}`\n"
                f"• Found: `{found_count}`"
            )

            if found_usernames:

                display_names = found_usernames[
                    -MAX_DISPLAYED_FOUND:
                ]

                content += (
                    "\n\n✨ **Recently found:**\n"
                    + "\n".join(
                        f"`{name}`"
                        for name in display_names
                    )
                )

                if (
                    len(found_usernames)
                    > MAX_DISPLAYED_FOUND
                ):

                    content += (
                        f"\n`+ "
                        f"{len(found_usernames) - MAX_DISPLAYED_FOUND}"
                        f" more`"
                    )

            try:

                if finished:

                    latest_data = (
                        await async_load_results()
                    )

                    latest_data = latest_data.get(
                        user_id,
                        empty_user_dict
                    )

                    await status_message.edit(
                        content=content,
                        view=ResultsView(
                            latest_data
                        )
                    )

                else:

                    await status_message.edit(
                        content=content
                    )

            except discord.HTTPException as e:

                if e.status == 429:

                    print(
                        "[RATE LIMIT] Status edit rate limited."
                    )

                elif e.status == 404:

                    print(
                        "[ERROR] Status message no longer exists."
                    )

                else:

                    print(
                        f"[ERROR] Status edit: {e}"
                    )

            except Exception as e:

                print(
                    f"[ERROR] Status update: {e}"
                )

        # =====================================================
        # SCAN
        # =====================================================

        try:

            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            ) as session:

                while active_checks.get(
                    uid_int,
                    {}
                ).get(
                    plat,
                    False
                ):

                    # -----------------------------------------
                    # GENERATION
                    # -----------------------------------------

                    try:

                        if mode == 1:

                            batch = await asyncio.to_thread(
                                generer_tous_prononcables_batch,
                                length_val,
                                game_id,
                                state_index,
                                BATCH_SIZE,
                                use_nums
                            )

                        elif mode == 2:

                            batch = await asyncio.to_thread(
                                preparer_combinaisons_classiques_batch,
                                length_val,
                                True,
                                use_nums,
                                game_id,
                                state_index,
                                BATCH_SIZE,
                                prefixe=pref
                            )

                        else:

                            batch = await asyncio.to_thread(
                                generer_toutes_possibilites_batch,
                                length_val,
                                game_id,
                                state_index,
                                BATCH_SIZE,
                                prefixe=pref
                            )

                    except Exception as e:

                        print(
                            f"[ERROR] Generation: {e}"
                        )

                        break

                    if not batch:

                        break

                    if not active_checks.get(
                        uid_int,
                        {}
                    ).get(
                        plat,
                        False
                    ):

                        break

                    state_index += len(
                        batch
                    )

                    # -----------------------------------------
                    # CHECKS
                    # -----------------------------------------

                    tasks_list = []

                    for final_pseudo in batch:

                        if plat == "discord":

                            tasks_list.append(
                                asyncio.to_thread(
                                    check_discord_custom_sync,
                                    final_pseudo,
                                    use_prox,
                                    proxies_list
                                )
                            )

                        elif plat == "minecraft":

                            tasks_list.append(
                                check_minecraft_api(
                                    session,
                                    final_pseudo
                                )
                            )

                        else:

                            tasks_list.append(
                                check_roblox_api(
                                    session,
                                    final_pseudo
                                )
                            )

                    try:

                        results = await asyncio.gather(
                            *tasks_list,
                            return_exceptions=True
                        )

                    except Exception as e:

                        print(
                            f"[ERROR] gather: {e}"
                        )

                        results = [
                            "erreur"
                            for _ in batch
                        ]

                    # -----------------------------------------
                    # RESULTS
                    # -----------------------------------------

                    for final_pseudo, result in zip(
                        batch,
                        results
                    ):

                        if not active_checks.get(
                            uid_int,
                            {}
                        ).get(
                            plat,
                            False
                        ):

                            break

                        total_checked += 1

                        if total_checked >= max_gens:

                            active_checks[
                                uid_int
                            ][plat] = False

                            break

                        if isinstance(
                            result,
                            Exception
                        ):

                            continue

                        if result != "libre":

                            continue

                        found_count += 1

                        found_usernames.append(
                            final_pseudo
                        )

                        print(
                            f"[FOUND] "
                            f"User: {interaction.user.name} | "
                            f"Platform: {platform_display_name} | "
                            f"Username: {final_pseudo}"
                        )

                        # -------------------------------------
                        # SAVE RESULT
                        # -------------------------------------

                        async with results_lock:

                            all_data = await asyncio.to_thread(
                                load_results
                            )

                            if user_id not in all_data:

                                all_data[user_id] = {
                                    key: []
                                    for key in PLATFORMS_CONFIG
                                }

                            if plat not in all_data[user_id]:

                                all_data[user_id][plat] = []

                            if (
                                final_pseudo
                                not in all_data[user_id][plat]
                            ):

                                all_data[
                                    user_id
                                ][plat].append(
                                    final_pseudo
                                )

                                await asyncio.to_thread(
                                    save_results,
                                    all_data
                                )

                    # -----------------------------------------
                    # UPDATE STATUS
                    # -----------------------------------------

                    await update_status()

                    await asyncio.sleep(0)

        except asyncio.CancelledError:

            raise

        except Exception as e:

            print(
                f"[ERROR] Scan: {e}"
            )

        finally:

            if uid_int in active_checks:

                active_checks[
                    uid_int
                ][plat] = False

        # =====================================================
        # FIN
        # =====================================================

        await update_status(
            force=True,
            finished=True
        )


# ============================================================
# COMMANDES
# ============================================================


@bot.tree.command(
    name="bots",
    description="Show your total spawned bots"
)
async def bots_command(
    interaction: discord.Interaction
):

    total_bots_used = get_total_bots_used(
        interaction.user.id
    )

    total_text = format_total_bots_used(
        total_bots_used
    )

    await interaction.response.send_message(
        f"Total bots spawned: {total_text}",
        ephemeral=False
    )

    log_command(
        interaction.user,
        "bots"
    )


# ============================================================


@bot.tree.command(
    name="leaderboard",
    description="Show the top users who spawned the most bots"
)
async def leaderboard_command(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=False
    )

    log_command(
        interaction.user,
        "leaderboard"
    )

    try:

        with open(
            USAGE_COUNTS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(
            data,
            dict
        ):

            data = {}

    except (
        OSError,
        json.JSONDecodeError
    ) as e:

        print(
            f"[ERROR] Leaderboard load: {e}"
        )

        await interaction.followup.send(
            "❌ Unable to load leaderboard data."
        )

        return

    leaderboard_data = []

    for user_id, count in data.items():

        try:

            user_id_int = int(
                user_id
            )

            count_int = max(
                0,
                int(count)
            )

            if count_int <= 0:

                continue

            leaderboard_data.append(
                (
                    user_id_int,
                    count_int
                )
            )

        except (
            ValueError,
            TypeError
        ):

            continue

    leaderboard_data.sort(
        key=lambda x: x[1],
        reverse=True
    )

    leaderboard_data = leaderboard_data[
        :10
    ]

    if not leaderboard_data:

        await interaction.followup.send(
            "🏆 **Bot Spawn Leaderboard**\n\n"
            "No bot spawn statistics available yet."
        )

        return

    embed = discord.Embed(
        title="🏆 Bot Spawn Leaderboard",
        description=(
            "Users who spawned the most bots in total."
        ),
        color=discord.Color.blurple()
    )

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    lines = []

    for position, (
        user_id,
        total_bots
    ) in enumerate(
        leaderboard_data,
        start=1
    ):

        member = None

        guild = interaction.guild

        if guild is not None:

            member = guild.get_member(
                user_id
            )

        user = member

        if user is None:

            try:

                user = await bot.fetch_user(
                    user_id
                )

            except (
                discord.NotFound,
                discord.HTTPException
            ):

                user = None

        if user is not None:

            display_name = (
                getattr(
                    user,
                    "global_name",
                    None
                )
                or getattr(
                    user,
                    "display_name",
                    None
                )
                or getattr(
                    user,
                    "name",
                    None
                )
                or f"User {user_id}"
            )

        else:

            display_name = (
                f"User {user_id}"
            )

        medal = (
            medals[position - 1]
            if position <= 3
            else f"`#{position}`"
        )

        lines.append(
            f"{medal} **{display_name}** — "
            f"Spawned **{total_bots:,}** bots in total"
        )

    embed.description = (
        "Users who spawned the most bots in total.\n\n"
        + "\n".join(lines)
    )

    await interaction.followup.send(
        embed=embed
    )


# ============================================================


@bot.tree.command(
    name="startcheck",
    description="Start a username scan"
)
async def startcheck(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        "⚡ **Rayko's Sniper** — Select a platform:",
        view=PlatformView(),
        ephemeral=True
    )

    log_command(
        interaction.user,
        "startcheck"
    )


# ============================================================


@bot.tree.command(
    name="blacklist",
    description="[Admin] Ban a user from using the bot"
)
async def blacklist_command(
    interaction: discord.Interaction,
    member: discord.Member
):

    await interaction.response.defer(
        ephemeral=True
    )

    log_command(
        interaction.user,
        f"blacklist {member.name}"
    )

    if not is_admin(
        interaction
    ):

        await safe_followup_send(
            interaction,
            "❌ Permission denied.",
            ephemeral=True
        )

        return

    async with blacklist_lock:

        b_list = await asyncio.to_thread(
            load_blacklist
        )

        uid = str(
            member.id
        )

        if uid in b_list:

            await safe_followup_send(
                interaction,
                f"⚠️ **{member.display_name}** "
                "is already blacklisted.",
                ephemeral=True
            )

            return

        b_list.append(
            uid
        )

        await asyncio.to_thread(
            save_blacklist,
            b_list
        )

    await safe_followup_send(
        interaction,
        f"✅ **{member.display_name}** "
        "has been added to the blacklist.",
        ephemeral=True
    )


# ============================================================


@bot.tree.command(
    name="unblacklist",
    description="[Admin] Remove a user from the blacklist"
)
async def unblacklist(
    interaction: discord.Interaction,
    member: discord.Member
):

    await interaction.response.defer(
        ephemeral=True
    )

    log_command(
        interaction.user,
        f"unblacklist {member.name}"
    )

    if not is_admin(
        interaction
    ):

        await safe_followup_send(
            interaction,
            "❌ Permission denied.",
            ephemeral=True
        )

        return

    async with blacklist_lock:

        b_list = await asyncio.to_thread(
            load_blacklist
        )

        uid = str(
            member.id
        )

        if uid not in b_list:

            await safe_followup_send(
                interaction,
                f"⚠️ **{member.display_name}** "
                "is not blacklisted.",
                ephemeral=True
            )

            return

        b_list.remove(
            uid
        )

        await asyncio.to_thread(
            save_blacklist,
            b_list
        )

    await safe_followup_send(
        interaction,
        f"✅ **{member.display_name}** "
        "has been removed from the blacklist.",
        ephemeral=True
    )


# ============================================================


@bot.tree.command(
    name="usernames",
    description="Display your saved usernames"
)
async def usernames(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    log_command(
        interaction.user,
        "usernames"
    )

    if await is_blacklisted(
        interaction.user.id
    ):

        await safe_followup_send(
            interaction,
            "❌ You are banned from using this bot.",
            ephemeral=True
        )

        return

    all_data = await async_load_results()

    user_data = all_data.get(
        str(
            interaction.user.id
        ),
        {
            key: []
            for key in PLATFORMS_CONFIG
        }
    )

    if not any(
        user_data.get(key)
        for key in PLATFORMS_CONFIG
    ):

        await safe_followup_send(
            interaction,
            "❌ No usernames saved.",
            ephemeral=True
        )

        return

    await safe_followup_send(
        interaction,
        "📂 **Your saved usernames:**",
        view=ResultsView(
            user_data
        ),
        ephemeral=True
    )


# ============================================================


@bot.tree.command(
    name="clearusernames",
    description="Delete all your saved usernames"
)
async def clearusernames(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    log_command(
        interaction.user,
        "clearusernames"
    )

    if await is_blacklisted(
        interaction.user.id
    ):

        await safe_followup_send(
            interaction,
            "❌ You are banned from using this bot.",
            ephemeral=True
        )

        return

    all_data = await async_load_results()

    user_data = all_data.get(
        str(
            interaction.user.id
        ),
        {
            key: []
            for key in PLATFORMS_CONFIG
        }
    )

    if not any(
        user_data.get(key)
        for key in PLATFORMS_CONFIG
    ):

        await safe_followup_send(
            interaction,
            "❌ No usernames to delete.",
            ephemeral=True
        )

        return

    await safe_followup_send(
        interaction,
        "⚠️ **Confirm deletion of your usernames?**",
        view=ConfirmClearView(
            interaction.user.id
        ),
        ephemeral=True
    )


# ============================================================


@bot.tree.command(
    name="adminclear",
    description="[Admin] Delete a member's usernames"
)
async def adminclear(
    interaction: discord.Interaction,
    member: discord.Member
):

    await interaction.response.defer(
        ephemeral=True
    )

    log_command(
        interaction.user,
        f"adminclear {member.name}"
    )

    if not is_admin(
        interaction
    ):

        await safe_followup_send(
            interaction,
            "❌ Permission denied.",
            ephemeral=True
        )

        return

    async with results_lock:

        all_data = await asyncio.to_thread(
            load_results
        )

        uid = str(
            member.id
        )

        if uid not in all_data:

            await safe_followup_send(
                interaction,
                "⚠️ No usernames found for this user.",
                ephemeral=True
            )

            return

        del all_data[uid]

        await asyncio.to_thread(
            save_results,
            all_data
        )

    await safe_followup_send(
        interaction,
        f"✅ Usernames for "
        f"**{member.display_name}** deleted.",
        ephemeral=True
    )


# ============================================================


def parse_grant_duration(duration_text):
    """
    Parse durations such as:
    10m, 2h, 7d, 1w
    Also accepts plain numbers as minutes.
    """
    value = duration_text.strip().lower()

    match = re.fullmatch(r"(\d+(?:\.\d+)?)([mhdw])?", value)
    if not match:
        return None

    amount = float(match.group(1))
    unit = match.group(2) or "m"

    multipliers = {
        "m": 60,
        "h": 60 * 60,
        "d": 24 * 60 * 60,
        "w": 7 * 24 * 60 * 60,
    }

    seconds = int(amount * multipliers[unit])

    if seconds <= 0:
        return None

    # Keep accidental huge grants under 1 year.
    if seconds > 365 * 24 * 60 * 60:
        return None

    return seconds


def format_grant_duration(duration_text):
    value = duration_text.strip().lower()

    match = re.fullmatch(r"(\d+(?:\.\d+)?)([mhdw])?", value)
    if not match:
        return duration_text

    amount = match.group(1)
    unit = match.group(2) or "m"

    names = {
        "m": "minute",
        "h": "hour",
        "d": "day",
        "w": "week",
    }

    singular = names[unit]
    plural = singular + "s" if amount != "1" else singular

    return f"{amount} {plural}"


@bot.tree.command(
    name="grant",
    description="[Admin] Give the FreeAccess role temporarily"
)
@app_commands.describe(
    member="The user who will receive the role",
    duration="Duration: 10m, 2h, 7d, 1w (or a number of minutes)"
)
async def grant(
    interaction: discord.Interaction,
    member: discord.Member,
    duration: str
):
    await interaction.response.defer(ephemeral=True)

    log_command(
        interaction.user,
        f"grant {member.name} {duration}"
    )

    if not interaction.guild:
        await safe_followup_send(
            interaction,
            "❌ This command must be used in a server.",
            ephemeral=True
        )
        return

    if not is_admin(interaction):
        await safe_followup_send(
            interaction,
            "❌ Permission denied.",
            ephemeral=True
        )
        return

    duration_seconds = parse_grant_duration(duration)

    if duration_seconds is None:
        await safe_followup_send(
            interaction,
            "❌ Invalid duration. Use formats like `10m`, `2h`, `7d` or `1w`.",
            ephemeral=True
        )
        return

    role = interaction.guild.get_role(REQUIRED_ROLE_ID)

    if role is None:
        await safe_followup_send(
            interaction,
            f"❌ Role `{REQUIRED_ROLE_ID}` was not found.",
            ephemeral=True
        )
        return

    if role >= interaction.guild.me.top_role:
        await safe_followup_send(
            interaction,
            "❌ I cannot manage this role because it is higher than or equal to my highest role.",
            ephemeral=True
        )
        return

    try:
        await member.add_roles(
            role,
            reason=(
                f"Temporary grant by {interaction.user} "
                f"for {format_grant_duration(duration)}"
            )
        )

        duration_display = format_grant_duration(duration)

        try:
            await member.send(
                f"**Rayko gave you {role.name} for {duration_display}.**"
            )
            dm_status = " DM sent."
        except (discord.Forbidden, discord.HTTPException):
            dm_status = " ⚠️ I couldn't send them a DM."

        await safe_followup_send(
            interaction,
            (
                f"✅ Gave **{role.name}** to **{member.display_name}** "
                f"for **{duration_display}**.{dm_status}"
            ),
            ephemeral=True
        )

        async def remove_granted_role():
            await asyncio.sleep(duration_seconds)

            try:
                guild = bot.get_guild(interaction.guild.id)
                if guild is None:
                    return

                current_member = guild.get_member(member.id)

                if current_member is None:
                    try:
                        current_member = await guild.fetch_member(member.id)
                    except discord.NotFound:
                        return

                # Only remove the role if it is still present.
                # This avoids an unnecessary Discord API call.
                if role in current_member.roles:
                    await current_member.remove_roles(
                        role,
                        reason=(
                            f"Temporary /grant expired "
                            f"after {duration_display}"
                        )
                    )

                    try:
                        await current_member.send(
                            f"**Your {role.name} role from Rayko has expired.**"
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            except Exception as e:
                print(
                    f"[ERROR] Temporary grant removal for "
                    f"{member.id}: {e}"
                )

        asyncio.create_task(remove_granted_role())

    except discord.Forbidden:
        await safe_followup_send(
            interaction,
            "❌ I don't have permission to assign this role.",
            ephemeral=True
        )

    except discord.HTTPException as e:
        print(f"[ERROR] grant Discord API: {e}")

        await safe_followup_send(
            interaction,
            "❌ Discord returned an error while assigning the role.",
            ephemeral=True
        )

    except Exception as e:
        print(f"[ERROR] grant: {e}")

        await safe_followup_send(
            interaction,
            "❌ Error while assigning the role.",
            ephemeral=True
        )


# ============================================================
# EXISTING GRANTVIP
# ============================================================


@bot.tree.command(
    name="grantvip",
    description="[Admin] Grant the VIP role"
)
async def grantvip(
    interaction: discord.Interaction,
    member: discord.Member
):

    await interaction.response.defer(
        ephemeral=True
    )

    log_command(
        interaction.user,
        f"grantvip {member.name}"
    )

    if not interaction.guild:

        await safe_followup_send(
            interaction,
            "❌ This command must be used in a server.",
            ephemeral=True
        )

        return

    if not is_admin(
        interaction
    ):

        await safe_followup_send(
            interaction,
            "❌ Permission denied.",
            ephemeral=True
        )

        return

    role_vip = discord.utils.get(
        interaction.guild.roles,
        name="vip"
    )

    if not role_vip:

        await safe_followup_send(
            interaction,
            "❌ `vip` role not found.",
            ephemeral=True
        )

        return

    try:

        await member.add_roles(
            role_vip
        )

        await safe_followup_send(
            interaction,
            f"✅ VIP role assigned to "
            f"**{member.display_name}**.",
            ephemeral=True
        )

    except Exception as e:

        print(
            f"[ERROR] grantvip: {e}"
        )

        await safe_followup_send(
            interaction,
            "❌ Error while assigning role.",
            ephemeral=True
        )


# ============================================================


@bot.tree.command(
    name="revokevip",
    description="[Admin] Remove the VIP role"
)
async def revokevip(
    interaction: discord.Interaction,
    member: discord.Member
):

    await interaction.response.defer(
        ephemeral=True
    )

    log_command(
        interaction.user,
        f"revokevip {member.name}"
    )

    if not interaction.guild:

        await safe_followup_send(
            interaction,
            "❌ This command must be used in a server.",
            ephemeral=True
        )

        return

    if not is_admin(
        interaction
    ):

        await safe_followup_send(
            interaction,
            "❌ Permission denied.",
            ephemeral=True
        )

        return

    role_vip = discord.utils.get(
        interaction.guild.roles,
        name="vip"
    )

    if not role_vip:

        await safe_followup_send(
            interaction,
            "❌ `vip` role not found.",
            ephemeral=True
        )

        return

    try:

        await member.remove_roles(
            role_vip
        )

        await safe_followup_send(
            interaction,
            f"✅ VIP role removed from "
            f"**{member.display_name}**.",
            ephemeral=True
        )

    except Exception as e:

        print(
            f"[ERROR] revokevip: {e}"
        )

        await safe_followup_send(
            interaction,
            "❌ Error while removing role.",
            ephemeral=True
        )


# ============================================================


@bot.tree.command(
    name="stopcheck",
    description="Stop an ongoing scan"
)
@app_commands.describe(
    platform="minecraft, roblox, discord or leave empty for all"
)
async def stopcheck(
    interaction: discord.Interaction,
    platform: str = None
):

    await interaction.response.defer(
        ephemeral=True
    )

    log_command(
        interaction.user,
        (
            f"stopcheck "
            f"{platform if platform else 'all'}"
        )
    )

    uid = interaction.user.id

    user_active = active_checks.get(
        uid,
        {}
    )

    if platform:

        plat_clean = (
            platform.lower()
            .strip()
        )

        if plat_clean not in PLATFORMS_CONFIG:

            await safe_followup_send(
                interaction,
                (
                    "❌ Invalid platform. "
                    "Use `minecraft`, `roblox` "
                    "or `discord`."
                ),
                ephemeral=True
            )

            return

        if user_active.get(
            plat_clean,
            False
        ):

            user_active[
                plat_clean
            ] = False

            await safe_followup_send(
                interaction,
                (
                    f"🛑 **Scan for "
                    f"{PLATFORMS_CONFIG[plat_clean][0]} "
                    "stopped.**"
                ),
                ephemeral=True
            )

        else:

            await safe_followup_send(
                interaction,
                (
                    f"⚠️ No ongoing scan found for "
                    f"**{PLATFORMS_CONFIG[plat_clean][0]}**."
                ),
                ephemeral=True
            )

        return

    if not any(
        user_active.values()
    ):

        await safe_followup_send(
            interaction,
            "⚠️ No ongoing scan.",
            ephemeral=True
        )

        return

    await safe_followup_send(
        interaction,
        (
            "⚠️ **Are you sure you want "
            "to stop all ongoing scans?**"
        ),
        view=ConfirmStopAllView(
            uid
        ),
        ephemeral=True
    )


# ============================================================


@bot.tree.command(
    name="cleardm",
    description="[DM] Clean DM history"
)
async def cleardm(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        "🧹 **DM cleanup started...**",
        ephemeral=True
    )

    log_command(
        interaction.user,
        "cleardm"
    )

    if interaction.guild is not None:

        await interaction.edit_original_response(
            content=(
                "❌ Only available in Direct Messages."
            )
        )

        return

    asyncio.create_task(
        cleanup_dm_history(
            interaction
        )
    )


async def cleanup_dm_history(
    interaction
):

    count = 0

    try:

        async for message in interaction.channel.history(
            limit=None
        ):

            try:

                await message.delete()

                count += 1

                if count % 10 == 0:

                    await asyncio.sleep(0)

            except Exception:

                pass

        try:

            await interaction.edit_original_response(
                content=(
                    f"🧹 Cleanup complete "
                    f"({count} messages deleted)."
                )
            )

        except Exception:

            pass

    except Exception as e:

        print(
            f"[ERROR] cleanup_dm_history: {e}"
        )


# ============================================================


@bot.tree.command(
    name="about",
    description="Information about the bot"
)
async def about(
    interaction: discord.Interaction
):

    embed = discord.Embed(
        title="Rayko's Sniper",
        description=(
            "High-performance username "
            "scanning and generation tool."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Platforms",
        value=(
            "Minecraft, Roblox, Discord"
        ),
        inline=False
    )

    embed.add_field(
        name="Installation",
        value="User Install enabled",
        inline=False
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )

    log_command(
        interaction.user,
        "about"
    )


# ============================================================


@bot.tree.command(
    name="stats",
    description="Global statistics"
)
async def stats(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    log_command(
        interaction.user,
        "stats"
    )

    all_data = await async_load_results()

    total_users = len(
        all_data
    )

    total_pseudos = 0

    for user_data in all_data.values():

        if not isinstance(
            user_data,
            dict
        ):

            continue

        for pseudos in user_data.values():

            if isinstance(
                pseudos,
                list
            ):

                total_pseudos += len(
                    pseudos
                )

    embed = discord.Embed(
        title="Global Statistics",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Registered users",
        value=str(
            total_users
        ),
        inline=True
    )

    embed.add_field(
        name="Usernames found",
        value=str(
            total_pseudos
        ),
        inline=True
    )

    await safe_followup_send(
        interaction,
        embed=embed,
        ephemeral=True
    )


# ============================================================


@bot.tree.command(
    name="help",
    description="List of commands"
)
async def help_cmd(
    interaction: discord.Interaction
):

    embed = discord.Embed(
        title="Help — Rayko's Sniper",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Public",
        value=(
            "`/bots` • "
            "`/leaderboard` • "
            "`/about` • "
            "`/stats` • "
            "`/help` • "
            "`/cleardm`"
        ),
        inline=False
    )

    embed.add_field(
        name="FreeAccess / User",
        value=(
            "`/startcheck` • "
            "`/stopcheck [platform]` • "
            "`/usernames` • "
            "`/clearusernames`"
        ),
        inline=False
    )

    embed.add_field(
        name="Admin",
        value=(
            "`/blacklist` • "
            "`/unblacklist` • "
            "`/adminclear` • "
            "`/grant` • "
            "`/grantvip` • "
            "`/revokevip`"
        ),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )

    log_command(
        interaction.user,
        "help"
    )


# ============================================================
# STATUS LOOP
# ============================================================


@tasks.loop(
    seconds=15.0
)
async def check_user_statuses():

    guild = bot.get_guild(
        OFFICIAL_GUILD_ID
    )

    if not guild:

        return

    role_id = (
        int(
            DISCORD_REQUIRED_ROLE_ID
        )
        if DISCORD_REQUIRED_ROLE_ID.isdigit()
        else REQUIRED_ROLE_ID
    )

    role = guild.get_role(
        role_id
    )

    if not role:

        return

    for member in guild.members:

        if member.bot:

            continue

        has_status = False

        for activity in member.activities:

            if isinstance(
                activity,
                discord.CustomActivity
            ):

                status_text = (
                    getattr(
                        activity,
                        "state",
                        None
                    )
                    or getattr(
                        activity,
                        "name",
                        None
                    )
                    or ""
                )

                if status_text == TARGET_STATUS_TEXT:

                    has_status = True

                    break

        try:

            if (
                has_status
                and role not in member.roles
            ):

                await member.add_roles(
                    role,
                    reason=(
                        "Auto add: "
                        "Discord status detected"
                    )
                )

                print(
                    f"[STATUS] Added role {role.id} to "
                    f"{member} for exact status "
                    f"'{TARGET_STATUS_TEXT}'"
                )

            elif (
                not has_status
                and role in member.roles
            ):

                await member.remove_roles(
                    role,
                    reason=(
                        "Auto remove: "
                        "Discord status removed"
                    )
                )

                print(
                    f"[STATUS] Removed role {role.id} from "
                    f"{member}; exact status no longer detected"
                )

        except Exception as e:

            print(
                f"[ERROR] status role: {e}"
            )


check_user_sessions_cleanup = tasks.loop(minutes=10)
async def before_status_loop():

    await bot.wait_until_ready()


# ============================================================
# READY
# ============================================================


@bot.event
async def setup_hook():

    if auth_runner is None:

        try:

            await start_auth_api()

        except Exception as e:

            print(
                f"[ERROR] OAuth API startup: {e}"
            )


@bot.event
async def on_ready():

    print(
        f"[READY] Bot connected: {bot.user}"
    )

    try:

        synced = await bot.tree.sync()

        print(
            f"[READY] Synced commands: "
            f"{len(synced)}"
        )

    except Exception as e:

        print(
            f"[ERROR] Command sync: {e}"
        )

    if not check_user_statuses.is_running():

        try:

            check_user_statuses.start()

        except Exception as e:

            print(
                f"[ERROR] Status loop: {e}"
            )


# ============================================================
# MESSAGE EVENT
# ============================================================


@bot.event
async def on_message(
    message
):

    if message.author.bot:

        return

    await bot.process_commands(
        message
    )


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================


@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    print(
        f"[COMMAND ERROR] "
        f"{type(error).__name__}: {error}"
    )

    try:

        message = (
            "❌ An error occurred while executing the command."
        )

        if interaction.response.is_done():

            await safe_followup_send(
                interaction,
                message,
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                message,
                ephemeral=True
            )

    except Exception as e:

        print(
            f"[ERROR] Error handler: {e}"
        )


# ============================================================
# START
# ============================================================


if __name__ == "__main__":

    if not TOKEN:

        raise RuntimeError(
            "DISCORD_TOKEN is not set. "
            "Configure it as an environment variable."
        )

    bot.run(
        TOKEN
    )
