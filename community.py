import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "community.db")


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS works (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            old_item TEXT,
            requirement TEXT,
            image BLOB,
            author TEXT DEFAULT '匿名用户',
            likes INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS exchanges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            contact TEXT,
            status TEXT DEFAULT '可用',
            created_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def publish_work(title, description, old_item, requirement, image_bytes, author="匿名用户"):
    conn = _get_db()
    conn.execute(
        "INSERT INTO works (title, description, old_item, requirement, image, author, created_at) VALUES (?,?,?,?,?,?,?)",
        (title, description, old_item, requirement, image_bytes, author, datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()
    conn.close()


def list_works(limit=30):
    conn = _get_db()
    rows = conn.execute("SELECT * FROM works ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows


def like_work(work_id):
    conn = _get_db()
    conn.execute("UPDATE works SET likes = likes + 1 WHERE id = ?", (work_id,))
    conn.commit()
    conn.close()


def publish_exchange(item_name, description, category, contact):
    conn = _get_db()
    conn.execute(
        "INSERT INTO exchanges (item_name, description, category, contact, created_at) VALUES (?,?,?,?,?)",
        (item_name, description, category, contact, datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()
    conn.close()


def list_exchanges(limit=30):
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM exchanges WHERE status='可用' ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows
