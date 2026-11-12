"""Telegram'ga yuborish va alertlar (takrorlanmaslik nazorati bilan)."""
import html
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import db, settings

log = logging.getLogger("notify")
_bot: Bot | None = None
_bot_token: str | None = None


def make_bot(token: str) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def get_bot() -> Bot | None:
    """Token adminkada o'zgarsa, yangi Bot obyekti yaratiladi."""
    global _bot, _bot_token
    token = await settings.bot_token()
    if not token:
        return None
    if token != _bot_token:
        if _bot is not None:
            await _bot.session.close()
        _bot, _bot_token = make_bot(token), token
    return _bot


async def admin_chat() -> int:
    return await settings.admin_chat_id()


def e(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=False)


async def send(chat_id: int, text: str) -> bool:
    if not chat_id:
        log.warning("chat_id yo'q, xabar yuborilmadi")
        return False
    b = await get_bot()
    if b is None:
        log.warning("Bot tokeni adminkada kiritilmagan, xabar yuborilmadi")
        return False
    try:
        for i in range(0, len(text), 4000):  # Telegram 4096 belgi chegarasi
            await b.send_message(chat_id, text[i : i + 4000], disable_web_page_preview=True)
        return True
    except Exception as ex:  # noqa: BLE001
        log.error("Telegram yuborishda xato (%s): %s", chat_id, ex)
        return False


async def get_rule(client_id: int, rule_type: str) -> dict:
    row = await db.fetchrow(
        """SELECT COALESCE(c.enabled, g.enabled) AS enabled,
                  COALESCE(c.threshold, g.threshold) AS threshold,
                  COALESCE(c.notify_client, g.notify_client) AS notify_client
           FROM alert_rules g
           LEFT JOIN alert_rules c ON c.type = g.type AND c.client_id = $1 AND $1 <> 0
           WHERE g.client_id = 0 AND g.type = $2""",
        client_id or 0,
        rule_type,
    )
    if not row:
        return {"enabled": True, "threshold": None, "notify_client": False}
    return {"enabled": row["enabled"], "threshold": row["threshold"], "notify_client": row["notify_client"]}


async def clients_of_account(ad_account_id: int) -> list:
    return await db.fetch(
        """SELECT c.id, c.name, g.chat_id
           FROM client_sources s JOIN clients c ON c.id = s.client_id
           LEFT JOIN tg_groups g ON g.id = c.group_id AND g.active
           WHERE s.ad_account_id = $1""",
        ad_account_id,
    )


async def alert(rule_type: str, dedupe_key: str, text: str, ad_account_id: int | None = None,
                client_id: int | None = None) -> None:
    """Alertni bir marta yuboradi: sizga, qoida ruxsat bersa mijoz guruhiga ham."""
    targets: list[tuple[int, str]] = []
    clients = []
    if ad_account_id:
        clients = await clients_of_account(ad_account_id)
    elif client_id:
        clients = await db.fetch(
            """SELECT c.id, c.name, g.chat_id FROM clients c
               LEFT JOIN tg_groups g ON g.id = c.group_id AND g.active WHERE c.id = $1""", client_id)

    # Qoida: mijozga xos bo'lsa o'shani, bo'lmasa standartni olamiz
    rule = await get_rule(clients[0]["id"] if clients else 0, rule_type)
    if not rule["enabled"]:
        return

    inserted = await db.fetchval(
        """INSERT INTO alerts_log (dedupe_key, type, ad_account_id, client_id, message)
           VALUES ($1, $2, $3, $4, $5) ON CONFLICT (dedupe_key) DO NOTHING RETURNING id""",
        dedupe_key, rule_type, ad_account_id, clients[0]["id"] if clients else client_id, text,
    )
    if not inserted:
        return  # allaqachon yuborilgan

    names = ", ".join(c["name"] for c in clients)
    header = f"🔔 <b>{e(names)}</b>\n" if names else "🔔 "
    targets.append((await admin_chat(), "admin"))
    for c in clients:
        c_rule = await get_rule(c["id"], rule_type)
        if c_rule["notify_client"] and c["chat_id"]:
            targets.append((c["chat_id"], f"group:{c['chat_id']}"))

    sent = []
    for chat_id, label in targets:
        if await send(chat_id, header + text):
            sent.append(label)
    await db.execute("UPDATE alerts_log SET sent_to = $1 WHERE id = $2", ",".join(sent), inserted)
