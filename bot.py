import asyncio
import json
import os
import time
import io
import datetime
import uuid
import requests
import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp

from gen import (
    generer_tous_prononcables_batch,
    preparer_combinaisons_classiques_batch,
    generer_toutes_possibilites_batch,
    ADMIN_MAX_GENS
)

# ============================================================
# CONFIGURATION
# ============================================================

# IMPORTANT :
# NE METS PAS TON TOKEN DIRECTEMENT ICI.
#
# Windows CMD :
# set DISCORD_TOKEN=TON_NOUVEAU_TOKEN
#
# PowerShell :
# $env:DISCORD_TOKEN="TON_NOUVEAU_TOKEN"
#
# Linux :
# export DISCORD_TOKEN="TON_NOUVEAU_TOKEN"

TOKEN = os.getenv("DISCORD_TOKEN")


OFFICIAL_GUILD_ID = 1320431531386208386

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
ROLE_FREEACCESS_NAME = "FreeAccess"

# ============================================================
# RATE LIMIT / STATUS CONFIG
# ============================================================

# Ne pas envoyer un webhook pour chaque résultat.
# Les résultats sont regroupés dans le message de statut.
STATUS_UPDATE_INTERVAL = 2.0

# Nombre maximum de pseudos affichés dans le message de statut.
MAX_DISPLAYED_FOUND = 10

# ============================================================
# LOCKS
# ============================================================

results_lock = asyncio.Lock()
blacklist_lock = asyncio.Lock()

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
# COMMAND TREE
# ============================================================


class OwnerOnlyCommandTree(app_commands.CommandTree):

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:

        if interaction.user.id in OWNER_IDS:
            return True

        try:

            if not interaction.response.is_done():

                await interaction.response.send_message(
                    "❌ You do not have permission to use this bot.",
                    ephemeral=True
                )

            else:

                await interaction.followup.send(
                    "❌ You do not have permission to use this bot.",
                    ephemeral=True
                )

        except discord.NotFound:

            print(
                "[ERROR] interaction_check: "
                "interaction expired before response"
            )

        except discord.HTTPException as e:

            print(
                f"[ERROR] interaction_check: {e}"
            )

        return False


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
# LOG
# ============================================================


def log_command(user, command_name):

    now = datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    discriminator = ""

    if (
        hasattr(user, "discriminator")
        and user.discriminator != "0"
    ):
        discriminator = f"#{user.discriminator}"

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

    if not os.path.exists(RESULTS_FILE):
        return {}

    try:

        with open(
            RESULTS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(data, dict):
                return data

            return {}

    except Exception as e:

        print(
            f"[ERROR] load_results: {e}"
        )

        return {}


def save_results(data):

    try:

        temp_file = RESULTS_FILE + ".tmp"

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

    if not os.path.exists(BLACKLIST_FILE):
        return []

    try:

        with open(
            BLACKLIST_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(data, list):
                return data

            return []

    except Exception as e:

        print(
            f"[ERROR] load_blacklist: {e}"
        )

        return []


def save_blacklist(data):

    try:

        temp_file = BLACKLIST_FILE + ".tmp"

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

    if not os.path.exists(PROXIES_FILE):
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


def formater_proxy_requests(proxy_str):

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


def get_random_proxy(proxies_list):

    if not proxies_list:
        return None

    import random

    return formater_proxy_requests(
        random.choice(proxies_list)
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
                get_random_proxy(proxies_list)
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
                    min(2 ** attempt, 5)
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
            timeout=aiohttp.ClientTimeout(total=2)
        ) as response:

            if response.status in (204, 404):
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
            timeout=aiohttp.ClientTimeout(total=2)
        ) as response:

            if response.status != 200:
                return "erreur"

            data = await response.json()

            if data.get("code") == 0:
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
        for role in getattr(member, "roles", [])
    )


def get_user_role_info(interaction):

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
        return "Admin", True, is_vip_user

    if is_vip_user:
        return "VIP", False, True

    return "Member", False, False


# ============================================================
# SAFE DISCORD SEND
# ============================================================


async def safe_followup_send(
    interaction,
    *args,
    **kwargs
):

    """
    Envoie un followup en gérant proprement les 429.
    """

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


class ConfirmClearView(discord.ui.View):

    def __init__(self, user_id):

        super().__init__(
            timeout=60
        )

        self.user_id = str(user_id)

    async def check_user(
        self,
        interaction
    ):

        if str(interaction.user.id) != self.user_id:

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

        if not await self.check_user(interaction):
            return

        uid = str(interaction.user.id)

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

        if not await self.check_user(interaction):
            return

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="❌ **Deletion cancelled.**",
            view=self
        )

        self.stop()


# ============================================================


class ConfirmStopAllView(discord.ui.View):

    def __init__(self, user_id):

        super().__init__(
            timeout=60
        )

        self.user_id = str(user_id)

    async def check_user(
        self,
        interaction
    ):

        if str(interaction.user.id) != self.user_id:

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

        if not await self.check_user(interaction):
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

        if not await self.check_user(interaction):
            return

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="❌ **Stop action cancelled.**",
            view=self
        )

        self.stop()


# ============================================================


class ResultsSelect(discord.ui.Select):

    def __init__(self, results_dict):

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
            PLATFORMS_CONFIG[plat_key][0]
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
            "\n".join(pseudos).encode("utf-8")
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


class ResultsView(discord.ui.View):

    def __init__(self, results_dict):

        super().__init__(
            timeout=180
        )

        self.add_item(
            ResultsSelect(results_dict)
        )


# ============================================================


class PlatformSelect(discord.ui.Select):

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


class PlatformView(discord.ui.View):

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


class CheckModal(discord.ui.Modal):

    def __init__(
        self,
        chosen_platform
    ):

        super().__init__(
            title="Rayko's Sniper — Configuration"
        )

        self.chosen_platform = chosen_platform

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

        self.add_item(self.mode_gen)
        self.add_item(self.length)
        self.add_item(self.numbers_mode)
        self.add_item(self.prefix)
        self.add_item(self.proxy_mode)

    async def on_submit(
        self,
        interaction
    ):

        # =====================================================
        # ACK IMMÉDIAT
        # =====================================================

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
        # ROLE
        # =====================================================

        role_name, is_admin_user, is_vip_user = (
            get_user_role_info(interaction)
        )

        if is_admin_user:

            cooldown_time = 0
            max_gens = 999999

        elif is_vip_user:

            cooldown_time = 60
            max_gens = 999999

        else:

            cooldown_time = 120
            max_gens = 999999

        # =====================================================
        # EMPÊCHER PLUSIEURS SCANS IDENTIQUES
        # =====================================================

        uid_int = interaction.user.id

        if (
            uid_int in active_checks
            and any(
                active_checks[uid_int].values()
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
                    cooldown_time - elapsed
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

        if mode not in (1, 2, 3):
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
            PLATFORMS_CONFIG[plat][0]
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
            cooldowns[uid_int] = time.time()

        if uid_int not in active_checks:
            active_checks[uid_int] = {}

        active_checks[uid_int][plat] = True

        found_count = 0
        total_checked = 0
        state_index = 0

        # Résultats trouvés pendant CE scan.
        # On les affiche dans le message de statut.
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

                if len(found_usernames) > MAX_DISPLAYED_FOUND:

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
                ).get(plat, False):

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
                    ).get(plat, False):

                        break

                    state_index += len(batch)

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
                        ).get(plat, False):

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

    if not is_admin(interaction):

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

        uid = str(member.id)

        if uid in b_list:

            await safe_followup_send(
                interaction,
                f"⚠️ **{member.display_name}** "
                "is already blacklisted.",
                ephemeral=True
            )

            return

        b_list.append(uid)

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

    if not is_admin(interaction):

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

        uid = str(member.id)

        if uid not in b_list:

            await safe_followup_send(
                interaction,
                f"⚠️ **{member.display_name}** "
                "is not blacklisted.",
                ephemeral=True
            )

            return

        b_list.remove(uid)

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
        str(interaction.user.id),
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
        view=ResultsView(user_data),
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
        str(interaction.user.id),
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

    if not is_admin(interaction):

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

        uid = str(member.id)

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

    if not is_admin(interaction):

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

    if not is_admin(interaction):

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

            user_active[plat_clean] = False

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
        view=ConfirmStopAllView(uid),
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
        value=str(total_users),
        inline=True
    )

    embed.add_field(
        name="Usernames found",
        value=str(total_pseudos),
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
        name="Scan",
        value=(
            "`/startcheck` • "
            "`/stopcheck [platform]`"
        ),
        inline=False
    )

    embed.add_field(
        name="Panel",
        value=(
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
            "`/grantvip` • "
            "`/revokevip`"
        ),
        inline=False
    )

    embed.add_field(
        name="Misc",
        value=(
            "`/about` • "
            "`/stats` • "
            "`/help` • "
            "`/cleardm`"
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

    role = discord.utils.get(
        guild.roles,
        name=ROLE_FREEACCESS_NAME
    )

    if not role:
        return

    for member in guild.members:

        if member.bot:
            continue

        has_status = False

        for activity in member.activities:

            if (
                isinstance(
                    activity,
                    discord.CustomActivity
                )
                and activity.name
            ):

                if (
                    TARGET_STATUS_TEXT.lower()
                    in activity.name.lower()
                ):

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

        except Exception as e:

            print(
                f"[ERROR] status role: {e}"
            )


@check_user_statuses.before_loop
async def before_status_loop():

    await bot.wait_until_ready()


# ============================================================
# READY
# ============================================================


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

    bot.run(
        TOKEN
    )
