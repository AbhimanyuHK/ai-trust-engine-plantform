"""Snowflake DB-API adapter; all user values are parameter-bound."""
from __future__ import annotations
from contextlib import contextmanager
from typing import Any, Iterator, Sequence
import snowflake.connector
from snowflake.connector import SnowflakeConnection
from trust_engine.common.config.settings import Settings

@contextmanager
def connection(settings: Settings | None = None) -> Iterator[SnowflakeConnection]:
    conn = snowflake.connector.connect(**(settings or Settings()).snowflake_config)
    try:
        yield conn
    finally:
        conn.close()

def query(sql: str, params: Sequence[Any] | None = None, settings: Settings | None = None) -> list[dict[str, Any]]:
    with connection(settings) as conn, conn.cursor(snowflake.connector.DictCursor) as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())

def execute(sql: str, params: Sequence[Any] | None = None, settings: Settings | None = None) -> int:
    with connection(settings) as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return int(cur.rowcount or 0)
