"""Mijoz guruhlariga kunlik va haftalik hisobotlar."""
import logging
from datetime import date, datetime, timedelta

from . import db
from .config import TZ, WEEKLY_REPORT_TIME
from .metrics import RESULT_LABEL, aggregate, pct_change
from .notify import e, send

log = logging.getLogger("reports")


def _fmt_money(v, cur) -> str:
    return "—" if v is None else f"{v:,.2f} {cur}".replace(",", " ")


def _fmt_int(v) -> str:
    return f"{int(v):,}".replace(",", " ")


def _arrow(change) -> str:
    if change is None:
        return ""
    return f" ({'▲' if change > 0 else '▼'}{abs(change):.0f}%)"


async def _meta_rows(client_id: int, start: date, end: date):
    return await db.fetch(
        """SELECT a.currency, i.* FROM client_sources s
           JOIN ad_accounts a ON a.id = s.ad_account_id AND a.platform = 'meta'
           JOIN insights_daily i ON i.ad_account_id = a.id AND i.date BETWEEN $2 AND $3
           WHERE s.client_id = $1""",
        client_id, start, end,
    )


def _block(title: str, cur: dict, prev: dict | None, currency: str, label: str) -> str:
    lines = [f"<b>{title}</b>"]
    lines.append(f"💰 Sarf: {_fmt_money(cur['spend'], currency)}")
    cpr_change = pct_change(cur["cpr"], prev["cpr"]) if prev else None
    lines.append(f"🎯 {label}: {_fmt_int(cur['results'])}  |  Narxi: {_fmt_money(cur['cpr'], currency)}{_arrow(cpr_change)}")
    lines.append(f"👁 Reach: {_fmt_int(cur['reach'])}  |  CTR: {cur['ctr']:.2f}%  |  CPM: {_fmt_money(cur['cpm'], currency)}")
    return "\n".join(lines)


async def build_report(client, start: date, end: date, kind: str) -> str | None:
    rows = await _meta_rows(client["id"], start, end)
    span = (end - start).days + 1
    prev_rows = await _meta_rows(client["id"], start - timedelta(days=span), start - timedelta(days=1))
    label = RESULT_LABEL.get(client["result_type"], "Natijalar")

    if kind == "daily":
        head = f"📊 <b>{e(client['name'])}</b> — {start:%d.%m.%Y} hisoboti"
    else:
        head = f"📈 <b>{e(client['name'])}</b> — haftalik hisobot ({start:%d.%m} – {end:%d.%m})"

    parts = [head]
    if rows:
        currency = rows[0]["currency"] or ""
        cur = aggregate([dict(r) for r in rows], client["result_type"])
        prev = aggregate([dict(r) for r in prev_rows], client["result_type"]) if prev_rows else None
        parts.append(_block("Meta Ads", cur, prev, e(currency), label))
        if kind == "weekly" and prev:
            sc = pct_change(cur["spend"], prev["spend"])
            rc = pct_change(cur["results"], prev["results"])
            parts.append(f"O'tgan haftaga nisbatan: sarf{_arrow(sc) or ' (—)'}, {label.lower()}{_arrow(rc) or ' (—)'}")

    has_tg = await db.fetchval(
        """SELECT count(*) FROM client_sources s JOIN ad_accounts a ON a.id=s.ad_account_id
           WHERE s.client_id=$1 AND a.platform='tg_ads'""", client["id"])
    if has_tg:
        parts.append("<b>Telegram Ads</b>\nMa'lumot API ulagichi qo'shilgandan keyin chiqadi.")

    if len(parts) == 1:
        return None
    return "\n\n".join(parts)


async def send_report(client, kind: str, start: date, end: date, period: date, log_it: bool = True) -> bool:
    if not client["chat_id"]:
        return False
    text = await build_report(client, start, end, kind)
    if text is None:
        text = f"📊 <b>{e(client['name'])}</b>\nBu davr uchun reklama ma'lumoti yo'q."
    ok = await send(client["chat_id"], text)
    if log_it:
        await db.execute(
            """INSERT INTO reports_log (client_id, kind, period, ok, error) VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (client_id, kind, period) DO UPDATE SET ok=EXCLUDED.ok, error=EXCLUDED.error""",
            client["id"], kind, period, ok, None if ok else "Telegram'ga yuborilmadi",
        )
    return ok


CLIENTS_SQL = """SELECT c.*, g.chat_id FROM clients c
                 JOIN tg_groups g ON g.id = c.group_id AND g.active"""


def _in_window(now: datetime, hhmm: str, hours: int = 3) -> bool:
    """Belgilangan vaqtdan keyingi 3 soat ichida (server o'chib qolsa ham yetkazish uchun)."""
    h, m = map(int, hhmm.split(":"))
    minutes = now.hour * 60 + now.minute
    return h * 60 + m <= minutes <= h * 60 + m + hours * 60


async def send_due_reports() -> None:
    """Har daqiqada chaqiriladi: vaqti kelgan va hali yuborilmagan hisobotlarni yuboradi."""
    now = datetime.now(TZ)
    today = now.date()
    yesterday = today - timedelta(days=1)
    for c in await db.fetch(CLIENTS_SQL):
        if c["report_daily"] and _in_window(now, c["report_daily_time"]):
            sent = await db.fetchval(
                "SELECT ok FROM reports_log WHERE client_id=$1 AND kind='daily' AND period=$2", c["id"], today)
            if sent is None:
                await send_report(c, "daily", yesterday, yesterday, today)
        if c["report_weekly"] and now.weekday() == 0 and _in_window(now, WEEKLY_REPORT_TIME):
            sent = await db.fetchval(
                "SELECT ok FROM reports_log WHERE client_id=$1 AND kind='weekly' AND period=$2", c["id"], today)
            if sent is None:
                await send_report(c, "weekly", today - timedelta(days=7), yesterday, today)


async def send_test_report(client_id: int) -> bool:
    c = await db.fetchrow(CLIENTS_SQL + " WHERE c.id = $1", client_id)
    if not c:
        raise RuntimeError("Mijozga guruh biriktirilmagan")
    y = datetime.now(TZ).date() - timedelta(days=1)
    return await send_report(c, "daily", y, y, y, log_it=False)
