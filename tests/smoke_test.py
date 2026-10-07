"""端到端冒烟测试：直接运行 `python3 tests/smoke_test.py`。

使用 Flask 测试客户端与临时 SQLite 库，覆盖：
- 尺寸校验与错误提示
- ASCII / 二进制 STL 上传、损坏与退化模型的拒绝
- 份数上限（总实例数 ≤ 12）
- 求解最小批次数（含已知答案的最优性断言）
- 排布几何性质（留白内、间距分隔、份号齐全）
- 参数/模型变更后的失效与导出限制
"""

import io
import json
import os
import struct
import sys
import tempfile

# 在导入应用前指向临时数据库
_tmpdir = tempfile.mkdtemp(prefix="layout_test_")
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402

CLIENT = app.test_client()
FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def box_ascii(w, h, d):
    verts = [(x, y, z) for x in (0, w) for y in (0, h) for z in (0, d)]
    tris = [(0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6),
            (0, 1, 4), (1, 5, 4), (2, 6, 3), (3, 6, 7),
            (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5)]
    lines = ["solid box"]
    for a, b, c in tris:
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        for i in (a, b, c):
            lines.append("      vertex %s %s %s" % verts[i])
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid box")
    return ("\n".join(lines) + "\n").encode()


def box_binary(w, h, d):
    verts = [(x, y, z) for x in (0, w) for y in (0, h) for z in (0, d)]
    tris = [(0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6),
            (0, 1, 4), (1, 5, 4), (2, 6, 3), (3, 6, 7),
            (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5)]
    out = bytearray(b"\0" * 80)
    out += struct.pack("<I", len(tris))
    for a, b, c in tris:
        out += struct.pack("<3f", 0, 0, 0)
        for i in (a, b, c):
            out += struct.pack("<3f", *verts[i])
        out += b"\0\0"
    return bytes(out)


def upload(stl_bytes, copies, filename="box.stl"):
    return CLIENT.post("/api/model", data={
        "copies": str(copies),
        "file": (io.BytesIO(stl_bytes), filename),
    }, content_type="multipart/form-data")


def set_settings(**kw):
    return CLIENT.post("/api/settings",
                       data=json.dumps(kw),
                       content_type="application/json")


def solve():
    return CLIENT.post("/api/solve")


def separated(a, b, s, eps=1e-6):
    return (a["x"] + a["width"] + s <= b["x"] + eps or
            b["x"] + b["width"] + s <= a["x"] + eps or
            a["y"] + a["height"] + s <= b["y"] + eps or
            b["y"] + b["height"] + s <= a["y"] + eps)


def verify_layout(payload, copies):
    bed = payload["bed"]
    m = bed["margins"]
    eps = 1e-6
    ok = payload["batch_count"] == len(payload["batches"])
    seen = []
    for batch in payload["batches"]:
        insts = batch["instances"]
        for inst in insts:
            seen.append(inst["copy"])
            inside = (inst["x"] >= m["left"] - eps and
                      inst["y"] >= m["bottom"] - eps and
                      inst["x"] + inst["width"] <= bed["width"] - m["right"] + eps and
                      inst["y"] + inst["height"] <= bed["height"] - m["top"] + eps)
            ok = ok and inside and inst["rotation"] in (0, 90)
        for i in range(len(insts)):
            for j in range(i + 1, len(insts)):
                ok = ok and separated(insts[i], insts[j], bed["spacing"])
    ok = ok and sorted(seen) == list(range(1, copies + 1))
    return ok


# ---------- 1. 尺寸校验 ----------
r = set_settings(bed_w=-5, bed_h=220, margin_left=10, margin_right=10,
                 margin_bottom=10, margin_top=10, spacing=5)
check("非法床宽被拒绝并说明原因",
      r.status_code == 400 and "尺寸无效" in r.get_json()["error"])

r = set_settings(bed_w=100, bed_h=100, margin_left=60, margin_right=50,
                 margin_bottom=0, margin_top=0, spacing=0)
check("留白之和不小于床宽被拒绝", r.status_code == 400)

r = set_settings(bed_w=float("nan"), bed_h=100, margin_left=0, margin_right=0,
                 margin_bottom=0, margin_top=0, spacing=0)
check("NaN 尺寸被拒绝", r.status_code == 400)

r = set_settings(bed_w=220, bed_h=220, margin_left=10, margin_right=10,
                 margin_bottom=10, margin_top=10, spacing=5)
check("合法设置保存成功", r.status_code == 200)

r = solve()
check("未上传模型时求解被拒绝", r.status_code == 400)

# ---------- 2. STL 校验 ----------
r = upload(b"this is definitely not an stl file", 3)
check("损坏 STL 被拒绝并说明原因",
      r.status_code == 400 and "STL 损坏" in r.get_json()["error"])

r = upload(box_ascii(20, 0, 5), 3)  # XY 投影高度为 0
check("XY 投影退化的模型被拒绝", r.status_code == 400)

r = upload(box_ascii(20, 10, 5), 13)
check("份数超过 12 被拒绝", r.status_code == 400)

# ---------- 3. 求解与最优性 ----------
r = upload(box_ascii(20, 10, 5), 12)
check("ASCII STL 上传成功（12 份）", r.status_code == 200)

r = solve()
check("求解成功", r.status_code == 200)
payload = r.get_json()["layout"]["result"]
check("12 件 20×10 在 200×200 打印区内一批装下",
      payload["batch_count"] == 1, f"got {payload['batch_count']}")
check("排布几何性质（留白内/间距/份号）成立",
      verify_layout(payload, 12))

# ---------- 4. 导出 ----------
r = CLIENT.get("/api/export")
exported = json.loads(r.data.decode())
check("有效排布可导出，内容与展示一致",
      r.status_code == 200 and exported == payload)

# ---------- 5. 失效与重新求解 ----------
r = set_settings(bed_w=220, bed_h=220, margin_left=10, margin_right=10,
                 margin_bottom=10, margin_top=10, spacing=6)
state = r.get_json()
check("修改床参数后旧排布标为失效", state["layout"]["status"] == "stale")
r = CLIENT.get("/api/export")
check("失效排布禁止导出", r.status_code == 409)

r = solve()
check("重新求解后恢复有效", r.get_json()["layout"]["status"] == "valid")
r = CLIENT.get("/api/export")
check("重新求解后可导出", r.status_code == 200)

# ---------- 6. 多批次最优性（已知答案） ----------
set_settings(bed_w=50, bed_h=50, margin_left=10, margin_right=10,
             margin_bottom=10, margin_top=10, spacing=5)
upload(box_ascii(20, 10, 5), 3)
r = solve()
payload = r.get_json()["layout"]["result"]
check("30×30 打印区、间距 5 时 3 件 20×10 需 2 批",
      payload["batch_count"] == 2, f"got {payload['batch_count']}")
check("多批次排布几何性质成立", verify_layout(payload, 3))

# ---------- 7. 单件放不入 ----------
r = upload(box_ascii(500, 500, 5), 1)
check("超大模型上传成功（仅记录占位）", r.status_code == 200)
r = solve()
check("单件无法放入时求解报错",
      r.status_code == 400 and "单件无法放入" in r.get_json()["error"])
r = CLIENT.get("/api/export")
check("求解失败后旧排布已失效、不可导出", r.status_code == 409)

# ---------- 8. 二进制 STL ----------
r = upload(box_binary(20, 10, 5), 4, filename="box_bin.stl")
state = r.get_json()
model = state["model"]
check("二进制 STL 上传成功且占位正确",
      r.status_code == 200 and abs(model["width"] - 20) < 1e-9
      and abs(model["height"] - 10) < 1e-9)
r = solve()
check("二进制模型求解成功且几何性质成立",
      r.status_code == 200
      and verify_layout(r.get_json()["layout"]["result"], 4))

print()
if FAILURES:
    print(f"{len(FAILURES)} 项失败: {FAILURES}")
    sys.exit(1)
print("全部通过。")
