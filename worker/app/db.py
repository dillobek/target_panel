import json

import asyncpg

from .config import DATABASE_URL

pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def init() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, init=_init_conn)
    return pool


async def fetch(sql: str, *args):
    return await pool.fetch(sql, *args)


async def fetchrow(sql: str, *args):
    return await pool.fetchrow(sql, *args)


async def fetchval(sql: str, *args):
    return await pool.fetchval(sql, *args)


async def execute(sql: str, *args):
    return await pool.execute(sql, *args)
