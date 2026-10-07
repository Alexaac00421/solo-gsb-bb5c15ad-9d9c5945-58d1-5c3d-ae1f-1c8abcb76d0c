"""应用配置。可通过环境变量覆盖。"""
import os

# 持久化数据目录（SQLite 数据库位于其中）
DATA_DIR = os.environ.get("NESTER_DATA_DIR", "/data")
DB_PATH = os.environ.get("NESTER_DB_PATH", os.path.join(DATA_DIR, "nester.sqlite3"))

# Web 监听
HOST = os.environ.get("NESTER_HOST", "0.0.0.0")
PORT = int(os.environ.get("NESTER_PORT", "8000"))

# 约束常量
MAX_TOTAL_INSTANCES = 12
EPS = 1e-9

DEFAULT_CONFIG = {
    "bed_width_mm": 200.0,
    "bed_depth_mm": 200.0,
    "margin_mm": 5.0,
    "gap_mm": 2.0,
}
