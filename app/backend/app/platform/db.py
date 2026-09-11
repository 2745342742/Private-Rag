from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row


def database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "未配置 DATABASE_URL。示例："
            "postgresql://postgres:postgres@127.0.0.1:5432/rag_demo"
        )
    return url


@contextmanager
def get_conn() -> Generator[psycopg.Connection, None, None]:
    conn = psycopg.connect(database_url(), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    schema_path = Path(__file__).with_name("schema.sql")
    sql = schema_path.read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.execute(sql)


def fetchone(conn: psycopg.Connection, query: str, params: Any = None) -> dict | None:
    cur = conn.execute(query, params)
    return cur.fetchone()


def fetchall(conn: psycopg.Connection, query: str, params: Any = None) -> list[dict]:
    cur = conn.execute(query, params)
    return list(cur.fetchall())
