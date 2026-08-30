# checker.py
import asyncio
import os
import random
import aiohttp

PROXIES_FILE = "proxy.txt"

def load_proxies():
    """Loads and converts proxies from proxy.txt into standard URL format."""
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
    """Returns a random proxy URL from the preloaded list."""
    if not proxies:
        return None
    return random.choice(proxies)


class GlobalRateLimiter:
    """True asyncio-safe rate limiter implementing fixed request pacing and Retry-After backing off."""
    def __init__(self, max_rate: float = 30.0):
        self.max_rate = max_rate
        self.interval = 1.0 / max_rate if max_rate > 0 else 0.0333
        self.lock = asyncio.Lock()
        self.next_available_time = 0.0

    async def acquire(self):
        async with self.lock:
            now = asyncio.get_running_loop().time()
            if now < self.next_available_time:
                wait_time = self.next_available_time - now
                self.next_available_time += self.interval
                await asyncio.sleep(wait_time)
            else:
                self.next_available_time = now + self.interval

    async def penalize(self, retry_after: float):
        async with self.lock:
            now = asyncio.get_running_loop().time()
            target = now + max(retry_after, 0.5)
            if target > self.next_available_time:
                self.next_available_time = target


async def check_discord_api(session: aiohttp.ClientSession, username: str, proxies: list[str], rate_limiter: GlobalRateLimiter) -> str:
    proxy = get_random_proxy(proxies)
    url = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"
    headers = {
        "Accept": "*/*",
        "Accept-Language": "fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3",
        "Content-Type": "application/json",
        "Origin": "https://discord.com",
        "Referer": "https://discord.com/register",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    payload = {"username": username}

    while True:
        await rate_limiter.acquire()
        try:
            async with session.post(url, json=payload, headers=headers, proxy=proxy) as response:
                if response.status == 429:
                    retry_after_header = response.headers.get("Retry-After")
                    try:
                        retry_val = float(retry_after_header) if retry_after_header else 1.5
                    except ValueError:
                        retry_val = 1.5
                    await rate_limiter.penalize(retry_val)
                    return "rate_limit"

                if response.status == 400:
                    return "pris"

                if response.status != 200:
                    return "erreur"

                data = await response.json(content_type=None)
                if "taken" not in data:
                    return "erreur"
                return "pris" if data["taken"] else "libre"

        except (asyncio.TimeoutError, aiohttp.ClientError):
            return "erreur"
        except Exception:
            return "erreur"


async def check_minecraft_api(session: aiohttp.ClientSession, username: str, proxies: list[str], rate_limiter: GlobalRateLimiter) -> str:
    proxy = get_random_proxy(proxies)
    url = f"https://api.mojang.com/users/profiles/minecraft/{username}"

    await rate_limiter.acquire()
    try:
        async with session.get(url, proxy=proxy) as response:
            if response.status in (204, 404):
                return "libre"
            if response.status == 200:
                return "pris"
            if response.status == 429:
                retry_header = response.headers.get("Retry-After", "2.0")
                try:
                    retry_val = float(retry_header)
                except ValueError:
                    retry_val = 2.0
                await rate_limiter.penalize(retry_val)
                return "rate_limit"
            return "erreur"
    except (asyncio.TimeoutError, aiohttp.ClientError):
        return "erreur"
    except Exception:
        return "erreur"


async def check_roblox_api(session: aiohttp.ClientSession, username: str, proxies: list[str], rate_limiter: GlobalRateLimiter) -> str:
    proxy = get_random_proxy(proxies)
    url = f"https://auth.roblox.com/v1/usernames/validate?request.username={username}&request.birthday=2000-01-01"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    await rate_limiter.acquire()
    try:
        async with session.get(url, headers=headers, proxy=proxy) as response:
            if response.status == 429:
                retry_header = response.headers.get("Retry-After", "2.0")
                try:
                    retry_val = float(retry_header)
                except ValueError:
                    retry_val = 2.0
                await rate_limiter.penalize(retry_val)
                return "rate_limit"

            if response.status != 200:
                return "erreur"

            data = await response.json()
            if data.get("code") == 0:
                return "libre"
            return "pris"
    except (asyncio.TimeoutError, aiohttp.ClientError):
        return "erreur"
    except Exception:
        return "erreur"


async def local_test():
    print("[TEST LOCAL] Démarrage du test local des checkers...")
    proxies = load_proxies()
    rate_limiter = GlobalRateLimiter(max_rate=5.0)
    connector = aiohttp.TCPConnector(limit=5)
    async with aiohttp.ClientSession(connector=connector) as session:
        test_users = ["notch", "roblox", "testuser123456789"]
        for user in test_users:
            res_mc = await check_minecraft_api(session, user, proxies, rate_limiter)
            print(f"Minecraft test [{user}]: {res_mc}")
            res_rb = await check_roblox_api(session, user, proxies, rate_limiter)
            print(f"Roblox test [{user}]: {res_rb}")


if __name__ == "__main__":
    asyncio.run(local_test())
