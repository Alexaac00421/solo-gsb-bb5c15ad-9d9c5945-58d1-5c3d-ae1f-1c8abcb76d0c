"""SQLite 持久化层。

存储：
- meta   键/值表，保存床参数 JSON、最近一次排布（含失效标记）
- models 已上传 STL 模型（投影尺寸、份数）

任何修改床参数或模型的操作都会把最近一次排布标记为失效，
重新求解成功后才会写入新的有效排布。
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

from . import config


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_conn():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS models (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT UNIQUE NOT NULL,
                size_mm     REAL NOT NULL,
                width_mm    REAL NOT NULL,
                depth_mm    REAL NOT NULL,
                height_mm   REAL NOT NULL,
                triangles   INTEGER NOT NULL,
                copies      INTEGER NOT NULL,
                created_at  TEXT NOT NULL
            );
            """
        )
        if conn.execute("SELECT 1 FROM meta WHERE key='config'").fetchone() is None:
            _put(conn, "config", config.DEFAULT_CONFIG)
        if conn.execute("SELECT 1 FROM meta WHERE key='solution'").fetchone() is None:
            _put(conn, "solution", None)
        conn.commit()


def _put(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )


def get_config(conn):
    row = conn.execute("SELECT value FROM meta WHERE key='config'").fetchone()
    return json.loads(row["value"]) if row and row["value"] != "null" else dict(config.DEFAULT_CONFIG)


def set_config(conn, cfg):
    _put(conn, "config", cfg)
    invalidate_solution(conn)
    conn.commit()


def get_solution(conn):
    row = conn.execute("SELECT value FROM meta WHERE key='solution'").fetchone()
    return json.loads(row["value"]) if row and row["value"] != "null" else None


def save_solution(conn, solution):
    _put(conn, "solution", solution)
    conn.commit()


def invalidate_solution(conn):
    sol = get_solution(conn)
    if sol is not None and sol.get("valid", False):
        sol["valid"] = False
        sol["invalidated_at"] = now_iso()
        _put(conn, "solution", sol)
        conn.commit()


def list_models(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM models ORDER BY id")]


def get_model(conn, model_id):
    row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    return dict(row) if row else None


def upsert_model(conn, name, size_mm, dims, triangles, copies):
    created = now_iso()
    conn.execute(
        """
        INSERT INTO models(name, size_mm, width_mm, depth_mm, height_mm,
                           triangles, copies, created_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            size_mm=excluded.size_mm,
            width_mm=excluded.width_mm,
            depth_mm=excluded.depth_mm,
            height_mm=excluded.height_mm,
            triangles=excluded.triangles,
            copies=excluded.copies
        """,
        (name, size_mm, dims["width_mm"], dims["depth_mm"], dims["height_mm"],
         triangles, copies, created),
    )
    invalidate_solution(conn)
    conn.commit()


def update_copies(conn, model_id, copies):
    conn.execute("UPDATE models SET copies=? WHERE id=?", (copies, model_id))
    invalidate_solution(conn)
    conn.commit()


def delete_model(conn, model_id):
    conn.execute("DELETE FROM models WHERE id=?", (model_id,))
    invalidate_solution(conn)
    conn.commit()


def total_copies(conn, exclude_id=None):
    q = "SELECT COALESCE(SUM(copies), 0) AS n FROM models"
    if exclude_id is not None:
        q += f" WHERE id != {int(exclude_id)}"
    return conn.execute(q).fetchone()["n"]
