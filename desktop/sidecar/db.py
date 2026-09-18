"""Локальное хранилище приложения (SQLite): треды и сообщения чата.

Держим на устройстве — приватно и работает офлайн для истории. Вложения/RAG уходят в
курсовые S3+Qdrant через шлюз; здесь только метаданные и текст сообщений.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    profile TEXT NOT NULL DEFAULT 'standard',
    skills TEXT NOT NULL DEFAULT '',
    favorite INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    role TEXT NOT NULL,          -- user | assistant | system
    content TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_thread ON messages(thread_id);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    chars INTEGER NOT NULL DEFAULT 0,
    chunks INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_att_thread ON attachments(thread_id);
"""


def _conn() -> sqlite3.Connection:
    config.ensure_dirs()
    c = sqlite3.connect(config.DB_FILE)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)
        # мягкие миграции для уже установленных копий (CREATE IF NOT EXISTS не добавляет колонки)
        try:
            c.execute("ALTER TABLE threads ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # колонка уже есть
        c.commit()


def q(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    with _conn() as c:
        cur = c.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]


def run(sql: str, args: tuple = ()) -> int:
    with _conn() as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def now() -> float:
    return time.time()
