"""Worker: 24/7 ishlaydigan jadval (ma'lumot olish, hisobot, alert, tahlil)."""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import db, diagnostics, jobs, reports, sync
from .config import DIAGNOSTICS_TIME, TZ

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def safe(fn):
    async def wrapper():
        try:
            await fn()
        except Exception:  # noqa: BLE001
            log.exception("%s xato bilan tugadi", fn.__name__)
    wrapper.__name__ = fn.__name__
    return wrapper


async def heartbeat():
    await db.execute(
        "INSERT INTO heartbeat (name, at) VALUES ('worker', now()) ON CONFLICT (name) DO UPDATE SET at=now()")


async def main():
    await db.init()
    log.info("Worker ishga tushdi")
    sch = AsyncIOScheduler(timezone=TZ)
    opts = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 300}
    sch.add_job(safe(heartbeat), "interval", minutes=5, **opts)
    sch.add_job(safe(sync.sync_all), "interval", minutes=15, **opts)
    sch.add_job(safe(sync.fetch_insights), "interval", minutes=60, **opts)
    sch.add_job(safe(sync.fetch_insights), "cron", hour=8, minute=40, id="insights_morning", **opts)
    sch.add_job(safe(sync.process_events), "interval", minutes=1, **opts)
    sch.add_job(safe(reports.send_due_reports), "interval", minutes=1, **opts)
    sch.add_job(safe(jobs.run_pending), "interval", seconds=20, **opts)
    h, m = map(int, DIAGNOSTICS_TIME.split(":"))
    sch.add_job(safe(diagnostics.run_all), "cron", hour=h, minute=m, **opts)
    sch.start()

    await safe(heartbeat)()
    await safe(sync.sync_all)()
    await safe(sync.fetch_insights)()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
