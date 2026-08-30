import aiohttp

def formater_proxy(proxy_str):
    if not proxy_str:
        return None
    proxy_str = proxy_str.strip()
    parts = proxy_str.split(":")
    if len(parts) == 4:
        ip, port, user, pwd = parts
        return f"http://{user}:{pwd}@{ip}:{port}"
    elif len(parts) == 2:
        return f"http://{proxy_str}"
    elif proxy_str.startswith("http://") or proxy_str.startswith("socks"):
        return proxy_str
    return f"http://{proxy_str}"


async def check_discord_custom(session, pseudo: str, proxy_str=None):
    try:
        proxy = formater_proxy(proxy_str)
        url = "https://discord.com/api/v9/users/@me/pomelo-attempt"
        headers = {"Authorization": "Bearer fake_token", "Content-Type": "application/json"}
        async with session.post(url, json={"username": pseudo}, headers=headers, proxy=proxy, timeout=2) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("taken") is False:
                    return "libre"
        return "pris"
    except:
        return "erreur"


async def check_minecraft_api(session, pseudo: str, proxy_str=None):
    try:
        proxy = formater_proxy(proxy_str)
        url = f"https://api.mojang.com/users/profiles/minecraft/{pseudo}"
        async with session.get(url, proxy=proxy, timeout=2) as response:
            if response.status in [204, 404]:
                return "libre"
        return "pris"
    except:
        return "erreur"


async def check_roblox_api(session, pseudo: str, proxy_str=None):
    try:
        proxy = formater_proxy(proxy_str)
        url = f"https://auth.roblox.com/v1/usernames/validate?request.username={pseudo}&request.birthday=2000-01-01"
        async with session.get(url, proxy=proxy, timeout=2) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("code") == 0:
                    return "libre"
        return "pris"
    except:
        return "erreur"