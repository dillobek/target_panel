"""Aiogram bot: guruhlarni avtomatik ro'yxatga olish, buyruqlar, worker nazorati."""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import ChatMemberUpdated, Message

from . import db, reports
from .config import ADMIN_CHAT_ID, TZ
from .notify import bot, e, send

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")
router = Router()


@router.my_chat_member()
async def on_bot_membership(ev: ChatMemberUpdated):
    """Bot guruhga qo'shilsa/admin bo'lsa/chiqarilsa — bazani yangilaymiz."""
    if ev.chat.type not in ("group", "supergroup"):
        return
    status = ev.new_chat_member.status
    title = ev.chat.title or str(ev.chat.id)
    if status in ("member", "administrator"):
        is_new = await db.fetchval("SELECT 1 FROM tg_groups WHERE chat_id=$1", ev.chat.id) is None
        await db.execute(
            """INSERT INTO tg_groups (chat_id, title, bot_is_admin, active) VALUES ($1,$2,$3,true)
               ON CONFLICT (chat_id) DO UPDATE SET title=EXCLUDED.title, bot_is_admin=EXCLUDED.bot_is_admin, active=true""",
            ev.chat.id, title, status == "administrator",
        )
        if is_new:
            await send(ADMIN_CHAT_ID, f"➕ Bot yangi guruhga qo'shildi: <b>{e(title)}</b>\n"
                                      f"Adminka → Mijozlar bo'limida uni mijozga biriktiring.")
    elif status in ("left", "kicked"):
        await db.execute("UPDATE tg_groups SET active=false WHERE chat_id=$1", ev.chat.id)
        await send(ADMIN_CHAT_ID, f"➖ Bot guruhdan chiqarildi: <b>{e(title)}</b>")


@router.message(F.migrate_to_chat_id)
async def on_migrate(m: Message):
    """Oddiy guruh supergroup'ga aylansa, chat_id o'zgaradi."""
    await db.execute("UPDATE tg_groups SET chat_id=$1 WHERE chat_id=$2", m.migrate_to_chat_id, m.chat.id)


@router.message(CommandStart(), F.chat.type == "private")
async def start(m: Message):
    await m.answer(
        "Salom! Men reklama hisobotlari botiman.\n\n"
        f"Sizning chat ID: <code>{m.chat.id}</code>\n"
        "Uni serverdagi .env faylida ADMIN_CHAT_ID ga yozing — alertlar sizga keladi.\n\n"
        "Mijoz guruhiga meni admin qilib qo'shing, keyin adminkada guruhni mijozga biriktiring."
    )


@router.message(Command("id"))
async def chat_id(m: Message):
    await m.answer(f"Chat ID: <code>{m.chat.id}</code>")


@router.message(Command("hisobot"), F.chat.type.in_({"group", "supergroup"}))
async def report_now(m: Message):
    c = await db.fetchrow(reports.CLIENTS_SQL + " WHERE g.chat_id = $1", m.chat.id)
    if not c:
        await m.answer("Bu guruh hali mijozga biriktirilmagan.")
        return
    y = datetime.now(TZ).date() - timedelta(days=1)
    text = await reports.build_report(c, y, y, "daily")
    await m.answer(text or "Kecha uchun ma'lumot yo'q.")


async def watchdog():
    """Worker 30 daqiqa javob bermasa, sizga xabar beradi (soatiga 1 marta)."""
    last_alert = None
    while True:
        await asyncio.sleep(300)
        try:
            at = await db.fetchval("SELECT at FROM heartbeat WHERE name='worker'")
            stale = at is None or datetime.now(TZ) - at > timedelta(minutes=30)
            if stale and (last_alert is None or datetime.now(TZ) - last_alert > timedelta(hours=1)):
                await send(ADMIN_CHAT_ID, "🚨 <b>Worker to'xtadi</b> — hisobotlar yuborilmayapti.\n"
                                          "Serverda: <code>docker compose logs --tail 100 worker</code>")
                last_alert = datetime.now(TZ)
            elif not stale:
                last_alert = None
        except Exception:  # noqa: BLE001
            log.exception("Watchdog xatosi")


async def main():
    await db.init()
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(watchdog())
    log.info("Bot ishga tushdi")
    await dp.start_polling(bot(), allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
