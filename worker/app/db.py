import json
import logging
import os

import asyncpg

from .config import DATABASE_URL

pool: asyncpg.Pool | None = None
log = logging.getLogger("db")


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def migrate() -> None:
    path = os.environ.get("MIGRATE_SQL", "/app/db/migrate.sql")
    if not os.path.exists(path):
        log.warning("%s topilmadi, migratsiya o'tkazib yuborildi", path)
        return
    sql = open(path, encoding="utf-8").read()
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock(424242)")
        try:
            await conn.execute(sql)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(424242)")


async def init() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, init=_init_conn)
        await migrate()
    return pool


async def fetch(sql: str, *args):
    return await pool.fetch(sql, *args)


async def fetchrow(sql: str, *args):
    return await pool.fetchrow(sql, *args)


async def fetchval(sql: str, *args):
    return await pool.fetchval(sql, *args)


async def execute(sql: str, *args):
    return await pool.execute(sql, *args)
