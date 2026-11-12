"""Accountlarni sinxronlash, insights yig'ish, Meta webhook hodisalarini qayta ishlash."""
import logging
from datetime import date, datetime, timedelta

from . import db
from .config import TZ
from .crypto import decrypt
from .meta import INSIGHT_FIELDS, MetaClient, MetaError, insights_url, minor_to_major
from .notify import alert, e

log = logging.getLogger("sync")

STATUS_TEXT = {
    1: "Faol", 2: "Bloklangan (disabled)", 3: "To'lov qarzi bor", 7: "Risk tekshiruvida",
    8: "To'lov kutilmoqda", 9: "Grace period", 100: "Yopilish kutilmoqda", 101: "Yopilgan",
}


def today() -> date:
    return datetime.now(TZ).date()


async def _client_for(conn_row) -> MetaClient:
    return MetaClient(decrypt(conn_row["token_enc"]))


async def _connection_failed(conn_row, ex: MetaError) -> None:
    await db.execute(
        "UPDATE connections SET status='error', last_error=$1, last_checked_at=now() WHERE id=$2",
        str(ex)[:500], conn_row["id"],
    )
    if ex.is_token_error:
        await alert(
            "token_error", f"token:{conn_row['id']}:{today()}",
            f"❗ <b>Token ishlamay qoldi</b>: {e(conn_row['name'])}\n{e(ex)}\n\nAdminkada tokenni yangilang.",
        )


async def sync_connection(conn_row) -> None:
    """Accountlar ro'yxati va holatini yangilaydi, holat o'zgarsa alert beradi."""
    if conn_row["platform"] != "meta":
        return
    try:
        client = await _client_for(conn_row)
        accounts = await client.ad_accounts()
    except MetaError as ex:
        log.error("Ulanish %s: %s", conn_row["id"], ex)
        await _connection_failed(conn_row, ex)
        return

    await db.execute(
        "UPDATE connections SET status='ok', last_error=NULL, last_checked_at=now() WHERE id=$1", conn_row["id"])

    for a in accounts:
        ext = str(a["account_id"])
        new_status = int(a.get("account_status") or 0)
        old = await db.fetchrow("SELECT id, account_status FROM ad_accounts WHERE platform='meta' AND external_id=$1", ext)
        spend_cap = minor_to_major(a.get("spend_cap"))
        amount_spent = minor_to_major(a.get("amount_spent"))
        acc_id = await db.fetchval(
            """INSERT INTO ad_accounts (connection_id, platform, external_id, name, currency, account_status,
                                        disable_reason, spend_cap, amount_spent, updated_at)
               VALUES ($1, 'meta', $2, $3, $4, $5, $6, $7, $8, now())
               ON CONFLICT (platform, external_id) DO UPDATE SET
                 connection_id=EXCLUDED.connection_id, name=EXCLUDED.name, currency=EXCLUDED.currency,
                 account_status=EXCLUDED.account_status, disable_reason=EXCLUDED.disable_reason,
                 spend_cap=EXCLUDED.spend_cap, amount_spent=EXCLUDED.amount_spent, updated_at=now()
               RETURNING id""",
            conn_row["id"], ext, a.get("name") or ext, a.get("currency"), new_status,
            int(a.get("disable_reason") or 0), spend_cap, amount_spent,
        )

        if old and old["account_status"] != new_status:
            if new_status == 1:
                msg = f"✅ <b>Account tiklandi</b>: {e(a.get('name'))} (act_{e(ext)})"
            else:
                msg = (f"❗ <b>Account holati o'zgardi</b>: {e(a.get('name'))} (act_{e(ext)})\n"
                       f"{e(STATUS_TEXT.get(old['account_status'], old['account_status']))} → "
                       f"<b>{e(STATUS_TEXT.get(new_status, new_status))}</b>")
            await alert("account_status", f"status:{acc_id}:{new_status}:{datetime.now(TZ):%Y%m%d%H}", msg, acc_id)

        if spend_cap and amount_spent is not None:
            await _check_spend_cap(acc_id, a, spend_cap, amount_spent)


async def _check_spend_cap(acc_id: int, a: dict, cap: float, spent: float) -> None:
    clients = await db.fetch("SELECT client_id FROM client_sources WHERE ad_account_id=$1 LIMIT 1", acc_id)
    from .notify import get_rule

    rule = await get_rule(clients[0]["client_id"] if clients else 0, "spend_limit")
    limit_pct = float(rule["threshold"] or 90)
    used = spent / cap * 100
    if used >= limit_pct:
        await alert(
            "spend_limit", f"cap:{acc_id}:{int(cap)}:{int(limit_pct)}",
            f"⚠️ <b>Spend limitga yaqin</b>: {e(a.get('name'))}\n"
            f"Sarflangan {spent:.2f} / {cap:.2f} {e(a.get('currency'))} ({used:.0f}%). Limitni oshiring.",
            acc_id,
        )


async def sync_all() -> None:
    for conn_row in await db.fetch("SELECT * FROM connections WHERE platform='meta'"):
        await sync_connection(conn_row)


async def fetch_insights(conn_row=None) -> None:
    """Oxirgi 7 kunlik kunma-kun insights (atributsiya kechikishi uchun har safar qayta yoziladi)."""
    conns = [conn_row] if conn_row else await db.fetch("SELECT * FROM connections WHERE platform='meta' AND status='ok'")
    for c in conns:
        accounts = await db.fetch("SELECT id, external_id FROM ad_accounts WHERE connection_id=$1", c["id"])
        if not accounts:
            continue
        try:
            client = await _client_for(c)
            urls = [insights_url(a["external_id"], level="account", date_preset="last_7d", time_increment=1,
                                 fields=INSIGHT_FIELDS, limit=50) for a in accounts]
            results = await client.batch(urls)
        except MetaError as ex:
            await _connection_failed(c, ex)
            continue
        yesterday = today() - timedelta(days=1)
        for acc, body in zip(accounts, results):
            if body is None:
                continue
            y_spend = 0.0
            for row in body.get("data", []):
                d = date.fromisoformat(row["date_start"])
                spend = float(row.get("spend") or 0)
                if d == yesterday:
                    y_spend = spend
                await db.execute(
                    """INSERT INTO insights_daily (ad_account_id, date, spend, impressions, reach, clicks, ctr, cpm,
                                                  frequency, actions, updated_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, now())
                       ON CONFLICT (ad_account_id, date) DO UPDATE SET
                         spend=EXCLUDED.spend, impressions=EXCLUDED.impressions, reach=EXCLUDED.reach,
                         clicks=EXCLUDED.clicks, ctr=EXCLUDED.ctr, cpm=EXCLUDED.cpm, frequency=EXCLUDED.frequency,
                         actions=EXCLUDED.actions, updated_at=now()""",
                    acc["id"], d, spend, int(row.get("impressions") or 0), int(row.get("reach") or 0),
                    int(row.get("clicks") or 0), float(row.get("ctr") or 0), float(row.get("cpm") or 0),
                    float(row.get("frequency") or 0), row.get("actions") or [],
                )
            await db.execute("UPDATE ad_accounts SET yesterday_spend=$1 WHERE id=$2", y_spend, acc["id"])


# ---------- Meta webhook hodisalari ----------

def _event_text(field: str, v: dict) -> str | None:
    if field == "with_issues_ad_objects":
        return (f"⚠️ <b>Muammo</b> ({e(v.get('level', ''))} {e(v.get('id', ''))}): "
                f"{e(v.get('error_summary') or v.get('error_message') or 'noma`lum')}")
    if field == "in_process_ad_objects":
        status = str(v.get("status_name", ""))
        if status in ("DISAPPROVED", "WITH_ISSUES"):
            return f"❌ <b>Reklama rad etildi</b> ({e(v.get('level', ''))} {e(v.get('id', ''))}): {e(status)}"
        return None
    if field == "effective_status":
        return f"ℹ️ <b>Holat o'zgardi</b>: {e(v.get('id', ''))} → {e(v.get('effective_status') or v)}"
    if field == "creative_fatigue":
        return f"🥱 <b>Kreativ charchayapti</b>: {e(v.get('ad_id') or v.get('id') or '')} — yangi kreativ qo'shing"
    if field == "ad_recommendations":
        return f"💡 <b>Meta tavsiyasi</b>: {e(v.get('recommendation_message') or v.get('recommendation_type') or '')}"
    return None


async def process_events() -> None:
    rows = await db.fetch("SELECT * FROM events WHERE processed=false ORDER BY id LIMIT 200")
    for ev in rows:
        try:
            v = ev["payload"] if isinstance(ev["payload"], dict) else {}
            text = _event_text(ev["field"], v)
            if text:
                acc = await db.fetchrow(
                    "SELECT id, name FROM ad_accounts WHERE platform='meta' AND external_id=$1", ev["external_id"])
                prefix = f"{e(acc['name'])}\n" if acc else f"act_{e(ev['external_id'])}\n"
                await alert("ad_issues", f"event:{ev['id']}", prefix + text, acc["id"] if acc else None)
        finally:
            await db.execute("UPDATE events SET processed=true WHERE id=$1", ev["id"])
