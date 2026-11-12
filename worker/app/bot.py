"""Aiogram bot. Token adminkada kiritiladi; o'zgarsa bot o'zi qayta ulanadi.

Guruhlar: bot qo'shilganda avtomatik ro'yxatga olinadi, /hisobot — kechagi hisobot.
Admin (shaxsiy chat): /tahlil — mijozni tanlab AI tahlil, /mijoz — savol beriladigan mijozni tanlash,
oddiy matn — tanlangan mijoz bo'yicha AI'ga savol.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import db, diagnostics, reports, settings
from .config import TZ
from .notify import admin_chat, e, make_bot, send

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")
router = Router()
active_client: dict[int, int] = {}  # admin chat -> savol beriladigan mijoz


async def is_admin(chat_id: int) -> bool:
    admin = await admin_chat()
    return bool(admin) and chat_id == admin


# ---------------- Guruhlar ----------------

@router.my_chat_member()
async def on_bot_membership(ev: ChatMemberUpdated):
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
            await send(await admin_chat(), f"➕ Bot yangi guruhga qo'shildi: <b>{e(title)}</b>\n"
                                           f"Adminka → Mijozlar bo'limida uni mijozga biriktiring.")
    elif status in ("left", "kicked"):
        await db.execute("UPDATE tg_groups SET active=false WHERE chat_id=$1", ev.chat.id)
        await send(await admin_chat(), f"➖ Bot guruhdan chiqarildi: <b>{e(title)}</b>")


@router.message(F.migrate_to_chat_id)
async def on_migrate(m: Message):
    await db.execute("UPDATE tg_groups SET chat_id=$1 WHERE chat_id=$2", m.migrate_to_chat_id, m.chat.id)


@router.message(Command("hisobot"), F.chat.type.in_({"group", "supergroup"}))
async def report_now(m: Message):
    c = await db.fetchrow(reports.CLIENTS_SQL + " WHERE g.chat_id = $1", m.chat.id)
    if not c:
        await m.answer("Bu guruh hali mijozga biriktirilmagan.")
        return
    y = datetime.now(TZ).date() - timedelta(days=1)
    await m.answer(await reports.build_report(c, y, y, "daily") or "Kecha uchun ma'lumot yo'q.")


@router.message(Command("id"))
async def chat_id(m: Message):
    await m.answer(f"Chat ID: <code>{m.chat.id}</code>")


# ---------------- Shaxsiy chat ----------------

HELP = ("Buyruqlar:\n"
        "/tahlil — mijozni tanlab AI tahlil\n"
        "/mijoz — savol beriladigan mijozni tanlash\n"
        "Keyin oddiy savol yozing, masalan: <i>Nega bu hafta lid qimmatlashdi?</i>")


@router.message(CommandStart(), F.chat.type == "private")
async def start(m: Message):
    name = " ".join(x for x in [m.from_user.first_name, m.from_user.last_name] if x) if m.from_user else ""
    await settings.add_starter(m.chat.id, name or str(m.chat.id), m.from_user.username if m.from_user else None)
    if await is_admin(m.chat.id):
        await m.answer("Salom! Siz adminsiz.\n\n" + HELP)
        return
    await m.answer(
        "Salom! Men reklama hisobotlari botiman.\n\n"
        f"Sizning ID: <code>{m.chat.id}</code>\n"
        "Admin bo'lish uchun: Adminka → Sozlamalar → «Botga /start yozganlar» ro'yxatidan o'zingizni "
        "«Admin qilib belgilash» tugmasi bilan tanlang."
    )


async def clients_keyboard(prefix: str) -> InlineKeyboardMarkup | None:
    rows = await db.fetch("SELECT id, name FROM clients ORDER BY name LIMIT 60")
    if not rows:
        return None
    buttons = [InlineKeyboardButton(text=r["name"][:40], callback_data=f"{prefix}:{r['id']}") for r in rows]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i : i + 2] for i in range(0, len(buttons), 2)])


@router.message(Command("tahlil"), F.chat.type == "private")
async def cmd_analysis(m: Message):
    if not await is_admin(m.chat.id):
        return
    kb = await clients_keyboard("ai")
    await m.answer("Qaysi mijozni tahlil qilay?" if kb else "Hali mijoz yo'q.", reply_markup=kb)


@router.message(Command("mijoz"), F.chat.type == "private")
async def cmd_pick(m: Message):
    if not await is_admin(m.chat.id):
        return
    kb = await clients_keyboard("ask")
    await m.answer("Qaysi mijoz haqida savol berasiz?" if kb else "Hali mijoz yo'q.", reply_markup=kb)


@router.callback_query(F.data.startswith("ai:") | F.data.startswith("ask:"))
async def on_pick(cb: CallbackQuery):
    if not cb.message or not await is_admin(cb.message.chat.id):
        await cb.answer()
        return
    kind, cid = cb.data.split(":", 1)
    c = await db.fetchrow("SELECT * FROM clients WHERE id=$1", int(cid))
    if not c:
        await cb.answer("Mijoz topilmadi", show_alert=True)
        return
    active_client[cb.message.chat.id] = c["id"]
    if kind == "ask":
        await cb.answer()
        await cb.message.answer(f"Tanlandi: <b>{e(c['name'])}</b>. Savolingizni yozing.")
        return
    await cb.answer("Tahlil boshlandi")
    await cb.message.answer(f"⏳ <b>{e(c['name'])}</b> tahlil qilinmoqda (30–60 soniya)…")
    try:
        await diagnostics.run_for_client(dict(c), kind="manual", to_chat=cb.message.chat.id)
        await cb.message.answer("Shu mijoz bo'yicha savolingiz bo'lsa, yozing.")
    except Exception as ex:  # noqa: BLE001
        log.exception("Bot tahlil xatosi")
        await cb.message.answer(f"Xato: {e(ex)}")


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def on_question(m: Message):
    if not await is_admin(m.chat.id):
        return
    cid = active_client.get(m.chat.id)
    if not cid:
        kb = await clients_keyboard("ask")
        await m.answer("Avval mijozni tanlang:", reply_markup=kb)
        return
    c = await db.fetchrow("SELECT * FROM clients WHERE id=$1", cid)
    if not c:
        active_client.pop(m.chat.id, None)
        return
    wait = await m.answer("🤔 O'ylayapman…")
    try:
        _, text = await diagnostics.ask(dict(c), m.text[:1000])
        await wait.edit_text(f"🤖 <b>{e(c['name'])}</b>\n\n{e(text)}")
    except Exception as ex:  # noqa: BLE001
        log.exception("AI savol xatosi")
        await wait.edit_text(f"Xato: {e(ex)}")


# ---------------- Ishga tushirish ----------------

async def watchdog():
    last_alert = None
    while True:
        await asyncio.sleep(300)
        try:
            at = await db.fetchval("SELECT at FROM heartbeat WHERE name='worker'")
            stale = at is None or datetime.now(TZ) - at > timedelta(minutes=30)
            if stale and (last_alert is None or datetime.now(TZ) - last_alert > timedelta(hours=1)):
                await send(await admin_chat(), "🚨 <b>Worker to'xtadi</b> — hisobotlar yuborilmayapti.\n"
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
    current: str | None = None
    task: asyncio.Task | None = None
    bot = None
    log.info("Bot jarayoni ishga tushdi, token kutilmoqda")
    while True:
        settings._cache.pop("bot_token", None)
        token = await settings.bot_token()
        if token != current:
            if task and not task.done():
                try:
                    await dp.stop_polling()
                except RuntimeError:
                    pass
                await asyncio.gather(task, return_exceptions=True)
            if bot is not None:
                await bot.session.close()
            current, task, bot = token, None, None
            if token:
                bot = make_bot(token)
                try:
                    me = await bot.get_me()
                    await settings.set("bot_username", me.username)
                    await settings.set("bot_status", "ok")
                    log.info("Bot ulandi: @%s", me.username)
                    task = asyncio.create_task(dp.start_polling(
                        bot, handle_signals=False, allowed_updates=dp.resolve_used_update_types()))
                except Exception as ex:  # noqa: BLE001
                    log.error("Bot tokeni ishlamadi: %s", ex)
                    await settings.set("bot_status", f"error: {str(ex)[:200]}")
        elif task and task.done() and current:
            log.warning("Polling to'xtadi, qayta ulanish")
            current = None  # keyingi aylanishda qayta ishga tushadi
        await asyncio.sleep(15)


if __name__ == "__main__":
    asyncio.run(main())
