"""Adminkadan keladigan vazifalar (jobs jadvali)."""
import logging

from . import db, diagnostics, reports, sync
from .notify import admin_chat, send

log = logging.getLogger("jobs")


async def run_pending() -> None:
    while True:
        job = await db.fetchrow(
            """UPDATE jobs SET status='running' WHERE id = (
                 SELECT id FROM jobs WHERE status='pending' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
               RETURNING *""")
        if not job:
            return
        p = job["payload"] or {}
        result = None
        try:
            if job["type"] == "sync_now":
                conn = await db.fetchrow("SELECT * FROM connections WHERE id=$1", int(p["connection_id"]))
                if conn:
                    await sync.sync_connection(conn)
                    conn = await db.fetchrow("SELECT * FROM connections WHERE id=$1", conn["id"])
                    if conn["status"] == "ok":
                        await sync.fetch_insights(conn)
            elif job["type"] == "test_report":
                if not await reports.send_test_report(int(p["client_id"])):
                    raise RuntimeError("Hisobot yuborilmadi (bot guruhda bormi?)")
            elif job["type"] in ("ai_analysis", "diagnostics_now"):
                c = await db.fetchrow("SELECT * FROM clients WHERE id=$1", int(p["client_id"]))
                if c:
                    result = {"analysis_id": await diagnostics.run_for_client(dict(c), kind="manual")}
            elif job["type"] == "ai_question":
                c = await db.fetchrow("SELECT * FROM clients WHERE id=$1", int(p["client_id"]))
                if c:
                    aid, text = await diagnostics.ask(dict(c), str(p.get("question", "")))
                    result = {"analysis_id": aid, "answer": text}
            elif job["type"] == "test_admin_message":
                chat = await admin_chat()
                if not chat:
                    raise RuntimeError("Admin chat belgilanmagan")
                if not await send(chat, "✅ Sinov xabari: bot va admin chat to'g'ri sozlangan."):
                    raise RuntimeError("Xabar yuborilmadi — bot tokeni va chat ID ni tekshiring")
            await db.execute("UPDATE jobs SET status='done', result=$1, done_at=now() WHERE id=$2", result, job["id"])
        except Exception as ex:  # noqa: BLE001
            log.exception("Job %s xato", job["id"])
            await db.execute("UPDATE jobs SET status='error', error=$1, done_at=now() WHERE id=$2",
                             str(ex)[:500], job["id"])
