"""SQLite 持久化：打印床设置、当前模型、当前排布。

三张单行表：
- settings：床宽高、四边留白、间距
- model：当前模型（文件名、份数、XY 投影占位尺寸、三角形数）
- layout：最近一次求解结果（JSON）及状态（valid / stale）

修改设置或替换模型时，旧排布被标记为 stale，重新求解前不可导出。
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "data", "app.db")
DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB_PATH)

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    bed_w REAL NOT NULL,
    bed_h REAL NOT NULL,
    margin_left REAL NOT NULL,
    margin_right REAL NOT NULL,
    margin_bottom REAL NOT NULL,
    margin_top REAL NOT NULL,
    spacing REAL NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    filename TEXT NOT NULL,
    copies INTEGER NOT NULL,
    width REAL NOT NULL,
    height REAL NOT NULL,
    triangles INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS layout (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL CHECK (status IN ('valid', 'stale')),
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock, _connect() as conn:
        conn.executescript(_SCHEMA)


def get_settings():
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    if not row:
        return None
    return {
        "bed_w": row["bed_w"],
        "bed_h": row["bed_h"],
        "margin_left": row["margin_left"],
        "margin_right": row["margin_right"],
        "margin_bottom": row["margin_bottom"],
        "margin_top": row["margin_top"],
        "spacing": row["spacing"],
    }


def save_settings(s):
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO settings
               (id, bed_w, bed_h, margin_left, margin_right,
                margin_bottom, margin_top, spacing, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 bed_w=excluded.bed_w, bed_h=excluded.bed_h,
                 margin_left=excluded.margin_left,
                 margin_right=excluded.margin_right,
                 margin_bottom=excluded.margin_bottom,
                 margin_top=excluded.margin_top,
                 spacing=excluded.spacing, updated_at=excluded.updated_at""",
            (s["bed_w"], s["bed_h"], s["margin_left"], s["margin_right"],
             s["margin_bottom"], s["margin_top"], s["spacing"], _now()),
        )


def get_model():
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM model WHERE id = 1").fetchone()
    if not row:
        return None
    return {
        "filename": row["filename"],
        "copies": row["copies"],
        "width": row["width"],
        "height": row["height"],
        "triangles": row["triangles"],
    }


def save_model(m):
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO model
               (id, filename, copies, width, height, triangles, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 filename=excluded.filename, copies=excluded.copies,
                 width=excluded.width, height=excluded.height,
                 triangles=excluded.triangles, updated_at=excluded.updated_at""",
            (m["filename"], m["copies"], m["width"], m["height"],
             m["triangles"], _now()),
        )


def get_layout():
    """返回 {"status": ..., "payload": <dict>} 或 None。"""
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM layout WHERE id = 1").fetchone()
    if not row:
        return None
    return {"status": row["status"], "payload": json.loads(row["payload"])}


def save_layout(payload):
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO layout (id, status, payload, created_at)
               VALUES (1, 'valid', ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 status='valid', payload=excluded.payload,
                 created_at=excluded.created_at""",
            (json.dumps(payload, ensure_ascii=False), _now()),
        )


def invalidate_layout():
    """把有效排布标记为失效（设置或模型变更时调用）。"""
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE layout SET status = 'stale' WHERE id = 1 AND status = 'valid'"
        )
