"""Adminkada saqlanadigan sozlamalar (bot tokeni, admin chat, AI kaliti). .env — zaxira qiymat."""
import json
import os
import time

from . import db
from .crypto import decrypt

_cache: dict[str, tuple[float, str | None]] = {}
TTL = 20


async def get(key: str, env: str | None = None, default: str | None = None) -> str | None:
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < TTL:
        return hit[1]
    row = await db.fetchrow("SELECT value, is_secret FROM settings WHERE key=$1", key)
    value = None
    if row and row["value"]:
        value = decrypt(row["value"]) if row["is_secret"] else row["value"]
    if not value and env:
        value = os.environ.get(env) or None
    if not value:
        value = default
    _cache[key] = (now, value)
    return value


async def set(key: str, value: str | None) -> None:
    await db.execute(
        """INSERT INTO settings (key, value, updated_at) VALUES ($1,$2, now())
           ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()""", key, value)
    _cache.pop(key, None)


async def bot_token() -> str | None:
    return await get("bot_token", "BOT_TOKEN")


async def admin_chat_id() -> int:
    v = await get("admin_chat_id", "ADMIN_CHAT_ID")
    try:
        return int(v) if v else 0
    except ValueError:
        return 0


async def ai_config() -> dict:
    return {
        "enabled": (await get("ai_enabled", default="true")) == "true",
        "api_key": await get("anthropic_api_key", "ANTHROPIC_API_KEY"),
        "model": await get("ai_model", "AI_MODEL", "claude-sonnet-5-5"),
    }


async def diagnostics_time() -> str:
    return await get("diagnostics_time", default="08:30") or "08:30"


async def add_starter(chat_id: int, name: str, username: str | None) -> None:
    """Botga /start yozganlar ro'yxati — adminkada "admin qilib belgilash" uchun."""
    raw = await db.fetchval("SELECT value FROM settings WHERE key='bot_starters'")
    try:
        items = json.loads(raw or "[]")
    except ValueError:
        items = []
    items = [i for i in items if i.get("id") != chat_id]
    items.insert(0, {"id": chat_id, "name": name, "username": username, "at": int(time.time())})
    await set("bot_starters", json.dumps(items[:10], ensure_ascii=False))
