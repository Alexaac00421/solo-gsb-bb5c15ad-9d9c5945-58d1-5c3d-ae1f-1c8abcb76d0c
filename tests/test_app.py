"""端到端集成测试（需要 flask）：
NESTER_DATA_DIR=/tmp/nester-test python3 tests/test_app.py
"""
import io
import json
import os
import struct
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix="nester-test-")
os.environ["NESTER_DATA_DIR"] = tmp
os.environ["NESTER_DB_PATH"] = os.path.join(tmp, "test.sqlite3")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.app import app, init  # noqa: E402

init()
client = app.test_client()


def box_stl(w, d, h, ascii_fmt=True):
    def faces():
        x0 = y0 = z0 = 0
        x1, y1, z1 = w, d, h
        p = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        idx = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 5, 1),
               (0, 4, 5), (2, 6, 7), (2, 7, 3), (1, 5, 6), (1, 6, 2),
               (0, 3, 7), (0, 7, 4)]
        return [(p[a], p[b], p[c]) for a, b, c in idx]
    fs = faces()
    if ascii_fmt:
        lines = ["solid s"]
        for a, b, c in fs:
            lines.append("facet normal 0 0 0\nouter loop")
            for x, y, z in (a, b, c):
                lines.append(f"vertex {x} {y} {z}")
            lines.append("endloop\nendfacet")
        lines.append("endsolid s")
        return ("\n".join(lines)).encode()
    out = bytearray(b"\0" * 80) + struct.pack("<I", len(fs))
    for a, b, c in fs:
        out += struct.pack("<3f", 0, 0, 0)
        for v in (a, b, c):
            out += struct.pack("<3f", *v)
        out += struct.pack("<H", 0)
    return bytes(out)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("ok:", msg)


def api(method, path, **kw):
    fn = getattr(client, method)
    return fn(path, **kw)


# 初始状态
r = api("get", "/api/state")
s = r.get_json()
check(s["config"]["bed_width_mm"] == 200.0 and s["total_instances"] == 0
      and s["solution"] is None, "初始状态为默认 200x200、无模型无排布")

# 无效床参数
r = api("post", "/api/config", json={"bed_width_mm": -1, "bed_depth_mm": 200,
                                     "margin_mm": 0, "gap_mm": 0})
check(r.status_code == 400 and "宽度" in r.get_json()["error"], "负床宽被拒绝")
r = api("post", "/api/config", json={"bed_width_mm": 10, "bed_depth_mm": 10,
                                     "margin_mm": 6, "gap_mm": 0})
check(r.status_code == 400 and "留白" in r.get_json()["error"], "留白过大被拒绝")
r = api("post", "/api/config", json={"bed_width_mm": "abc", "bed_depth_mm": 10,
                                     "margin_mm": 1, "gap_mm": 1})
check(r.status_code == 400, "非数字被拒绝")

# 合法参数
r = api("post", "/api/config", json={"bed_width_mm": 100, "bed_depth_mm": 100,
                                     "margin_mm": 5, "gap_mm": 2})
check(r.status_code == 200, "保存合法床参数")

# 无模型时导出/求解
check(api("get", "/api/export").status_code == 409, "无排布时导出 409")
check(api("post", "/api/solve").status_code == 400, "无模型时求解 400")

# 损坏 STL
r = api("post", "/api/models", data={
    "file": (io.BytesIO(b"not an stl at all but text"), "bad.stl"),
    "copies": "1",
}, content_type="multipart/form-data")
check(r.status_code == 400 and "STL" in r.get_json()["error"], "损坏 STL 被拒绝且不保存")
r = api("get", "/api/state")
check(len(r.get_json()["models"]) == 0, "损坏 STL 未写入")

# 单件过大：95x95（可用 90x90，旋转无帮助）
r = api("post", "/api/models", data={
    "file": (io.BytesIO(box_stl(95, 95, 10)), "big.stl"),
    "copies": "1",
}, content_type="multipart/form-data")
check(r.status_code == 400 and "单件无法放入" in r.get_json()["error"], "单件过大被拒绝")

# 上传二进制 STL：60x50，份数 2（可用 90x90，gap2）
stl_bin = box_stl(60, 50, 12, ascii_fmt=False)
r = api("post", "/api/models", data={
    "file": (io.BytesIO(stl_bin), "partA.stl"),
    "copies": "2",
}, content_type="multipart/form-data")
s = r.get_json()
check(r.status_code == 200 and s["total_instances"] == 2, "上传二进制 STL 份数 2")
m = s["models"][0]
check((m["width_mm"], m["depth_mm"], m["height_mm"]) == (60.0, 50.0, 12.0)
      and m["triangles"] == 12, "包围盒与面数正确")

# 份数上限
r = api("post", "/api/models", data={
    "file": (io.BytesIO(box_stl(10, 10, 10)), "tiny.stl"),
    "copies": "13",
}, content_type="multipart/form-data")
check(r.status_code == 400, "份数 13 被拒绝")
r = api("patch", f"/api/models/{m['id']}", json={"copies": 0})
check(r.status_code == 400, "份数 0 被拒绝")

# 求解：两件 60x50 在 90x90、gap2：
# 任意两个方向组合（60x50/50x60）都无法在 90x90 内保持间距 → 2 批
r = api("post", "/api/solve")
s = r.get_json()
check(r.status_code == 200 and s["solution"]["valid"]
      and s["solution"]["batch_count"] == 2, f"求解成功且为 2 批（实际 {s['solution']['batch_count']}）")

# 导出 JSON
r = api("get", "/api/export")
check(r.status_code == 200 and r.headers["Content-Disposition"].endswith("layout.json"),
      "导出 200 且文件名 layout.json")
payload = json.loads(r.data)
check(payload["coordinate_origin"] == "bed_bottom_left"
      and payload["batch_count"] == 2
      and payload["total_instances"] == 2
      and payload["bed"]["printable_area"]["origin"] == {"x_mm": 5.0, "y_mm": 5.0},
      "导出内容结构与坐标原点正确")
p0 = payload["batches"][0]["placements"][0]
check({"model", "copy_index", "rotation_deg", "x_mm", "y_mm",
       "width_mm", "depth_mm"} <= set(p0), "导出条目字段齐全")

# 导出文件也落盘到数据目录（供核对）
check(os.path.exists(os.path.join(tmp, "last_layout.json")), "导出缓存写入数据目录")

# 修改份数 → 失效
r = api("patch", f"/api/models/{m['id']}", json={"copies": 1})
sol = r.get_json()["solution"]
check(sol is not None and not sol["valid"] and "invalidated_at" in sol,
      "修改份数后旧排布标记失效")
r = api("get", "/api/export")
check(r.status_code == 409 and "失效" in r.get_json()["error"], "失效状态导出 409")

# 改床参数 → 失效；然后重解为 1 批
api("post", "/api/config", json={"bed_width_mm": 200, "bed_depth_mm": 200,
                                 "margin_mm": 5, "gap_mm": 2})
check(client.get("/api/state").get_json()["solution"]["valid"] is False,
      "改床参数后仍为失效")
r = api("post", "/api/solve")
check(r.status_code == 200 and r.get_json()["solution"]["batch_count"] == 1,
      "大床后重新求解为 1 批")
r = api("get", "/api/export")
check(r.status_code == 200, "有效排布可导出")

# 替换同名模型 → 失效 + 尺寸更新
r = api("post", "/api/models", data={
    "file": (io.BytesIO(box_stl(40, 20, 8)), "partA.stl"),
    "copies": "1",
}, content_type="multipart/form-data")
s = r.get_json()
check(len(s["models"]) == 1 and s["models"][0]["width_mm"] == 40.0,
      "同名替换更新尺寸（模型数不增加）")
check(s["solution"] is None or not s["solution"]["valid"], "替换后排布失效")

# 总数 12 上限：已有 1 件，再传 12 份应拒绝
r = api("post", "/api/models", data={
    "file": (io.BytesIO(box_stl(5, 5, 5)), "many.stl"),
    "copies": "12",
}, content_type="multipart/form-data")
check(r.status_code == 400 and "12" in r.get_json()["error"], "总实例数超 12 被拒绝")

# 12 份恰好允许
r = api("post", "/api/models", data={
    "file": (io.BytesIO(box_stl(5, 5, 5)), "many.stl"),
    "copies": "11",
}, content_type="multipart/form-data")
check(r.status_code == 200 and r.get_json()["total_instances"] == 12, "总数恰好 12 允许")

# 删除模型
mid = r.get_json()["models"][1]["id"]
r = api("delete", f"/api/models/{mid}")
check(r.status_code == 200 and r.get_json()["total_instances"] == 1, "删除模型")

# 首页
r = api("get", "/api/state")
page = client.get("/")
check(page.status_code == 200 and b"3D" in page.data, "首页可访问")

print(f"\n全部集成测试通过 ✔（数据目录 {tmp}）")
