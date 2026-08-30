import asyncio
import os
import random
import aiohttp

PROXIES_FILE = "proxy.txt"

def load_proxies():
    """Loads and converts proxies from proxies.txt into standard URL format once[cite: 1]."""
    proxies_list = []
    if not os.path.exists(PROXIES_FILE):
        return proxies_list
    
    try:
        with open(PROXIES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                parts = line.split(":")
                if len(parts) == 4:
                    host, port, user, pwd = parts
                    formatted_proxy = f"http://{user}:{pwd}@{host}:{port}"
                    proxies_list.append(formatted_proxy)
                elif len(parts) == 2:
                    host, port = parts
                    proxies_list.append(f"http://{host}:{port}")
                else:
                    proxies_list.append(line)
    except Exception as e:
        print(f"Error loading proxies: {e}")
    
    return proxies_list

def get_random_proxy(proxies: list[str]) -> str | None:
    """Returns a random proxy URL from the preloaded list[cite: 1]."""
    if not proxies:
        return None
    return random.choice(proxies)

# ================= ASYNC PLATFORM CHECKERS =================

async def check_discord_custom(session: aiohttp.ClientSession, username: str, proxies: list[str], sem: asyncio.Semaphore) -> str:
    """Checks a Discord username asynchronously with proper concurrency and 429 management[cite: 1]."""
    proxy = get_random_proxy(proxies)
    url = "https://discord.com/api/v9/users/@me/pomelo-attempt"

    headers = {
        "Content-Type": "application/json",
        "Origin": "https://discord.com",
        "Referer": "https://discord.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    payload = {"username": username}

    async with sem:
        try:
            async with session.post(url, json=payload, headers=headers, proxy=proxy, timeout=15) as response:
                if response.status in (200, 201):
                    data = await response.json()
                    if "taken" in data:
                        return "pris" if data["taken"] else "libre"
                    return "erreur"
                if response.status == 429:
                    return "ratelimit"
                return "erreur"
        except Exception:
            return "erreur"


async def check_minecraft_api(session: aiohttp.ClientSession, username: str, proxies: list[str], sem: asyncio.Semaphore) -> str:
    """Checks Minecraft username availability asynchronously[cite: 1]."""
    proxy = get_random_proxy(proxies)
    url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
    
    async with sem:
        try:
            async with session.get(url, proxy=proxy, timeout=5) as response:
                if response.status in [204, 404]:
                    return "libre"
                elif response.status == 200:
                    return "pris"
                elif response.status == 429:
                    return "ratelimit"
                else:
                    return "pris"
        except Exception:
            return "erreur"


async def check_roblox_api(session: aiohttp.ClientSession, username: str, proxies: list[str], sem: asyncio.Semaphore) -> str:
    """Checks Roblox username availability asynchronously[cite: 1]."""
    proxy = get_random_proxy(proxies)
    url = f"https://auth.roblox.com/v1/usernames/validation?request.username={username}&request.birthday=2000-01-01"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }
    
    async with sem:
        try:
            async with session.get(url, headers=headers, proxy=proxy, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 0:
                        return "libre"
                    else:
                        return "pris"
                elif response.status == 429:
                    return "ratelimit"
                else:
                    return "pris"
        except Exception:
            return "erreur"


async def main():
    # 1. Chargement unique des proxies[cite: 1]
    proxies = load_proxies()
    
    # 2. Limitation de concurrence raisonnable[cite: 1]
    sem = asyncio.Semaphore(10)
    
    # 3. ClientSession unique réutilisée (connexions persistantes / keep-alive)[cite: 1]
    connector = aiohttp.TCPConnector(limit=50, keepalive_timeout=30)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Exemple d'utilisation
        usernames = ["testuser1", "testuser2", "testuser3"]
        tasks = [check_minecraft_api(session, user, proxies, sem) for user in usernames]
        results = await asyncio.gather(*tasks)
        print(results)

if __name__ == "__main__":
    asyncio.run(main())