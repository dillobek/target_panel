"""Adminkadan keladigan vazifalar (jobs jadvali)."""
import logging

from . import db, diagnostics, reports, sync

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
            elif job["type"] == "diagnostics_now":
                c = await db.fetchrow("SELECT * FROM clients WHERE id=$1", int(p["client_id"]))
                if c:
                    await diagnostics.run_for_client(c)
            await db.execute("UPDATE jobs SET status='done', done_at=now() WHERE id=$1", job["id"])
        except Exception as ex:  # noqa: BLE001
            log.exception("Job %s xato", job["id"])
            await db.execute("UPDATE jobs SET status='error', error=$1, done_at=now() WHERE id=$2",
                             str(ex)[:500], job["id"])
