"""核心逻辑本地验证（仅依赖标准库）：
python3 tests/test_core.py
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import solver, stl


def make_ascii(vertices_faces):
    lines = ["solid test"]
    for a, b, c in vertices_faces:
        lines.append("facet normal 0 0 0")
        lines.append("  outer loop")
        for x, y, z in (a, b, c):
            lines.append(f"    vertex {x} {y} {z}")
        lines.append("  endloop")
        lines.append("endfacet")
    lines.append("endsolid test")
    return "\n".join(lines).encode()


def make_binary(faces):
    out = bytearray(b"\0" * 80)
    out += struct.pack("<I", len(faces))
    for a, b, c in faces:
        out += struct.pack("<3f", 0, 0, 0)
        for v in (a, b, c):
            out += struct.pack("<3f", *v)
        out += struct.pack("<H", 0)
    return bytes(out)


def box_faces(x0, y0, z0, x1, y1, z1):
    p = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    idx = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
           (0, 5, 1), (0, 4, 5), (2, 6, 7), (2, 7, 3),
           (1, 5, 6), (1, 6, 2), (0, 3, 7), (0, 7, 4)]
    return [(p[a], p[b], p[c]) for a, b, c in idx]


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("ok:", msg)


# ---------- STL ----------
faces = box_faces(0, 0, -1, 30, 60, 10)
d_ascii = stl.parse_stl(make_ascii(faces))
check((d_ascii["width_mm"], d_ascii["depth_mm"], d_ascii["height_mm"]) == (30.0, 60.0, 11.0),
      "ASCII STL 包围盒（含负坐标）")
check(d_ascii["triangles"] == 12, "ASCII 三角面计数")

d_bin = stl.parse_stl(make_binary(faces))
check((d_bin["width_mm"], d_bin["depth_mm"], d_bin["height_mm"]) == (30.0, 60.0, 11.0),
      "二进制 STL 包围盒")
check(d_bin["triangles"] == 12, "二进制三角面计数")

# 二进制 STL 头部含 "solid" 字样也必须识别为二进制（长度校验）
tricky = b"solid" + b"\0" * 75 + make_binary(faces)[80:]
d_tricky = stl.parse_stl(tricky)
check(d_tricky["triangles"] == 12, "头部含 solid+NUL 时识别为二进制")

for bad, label in [
    (b"", "空文件"),
    (b"solid x\nendsolid x\n", "ASCII 无三角面"),
    (b"solid x\nfacet normal 0 0 0\nouter loop\nvertex 0 0 0\n"
     b"vertex 1 0 0\nvertex x 0 0\nendloop\nendfacet\nendsolid x", "ASCII 非法数字"),
    (b"solid x\nfacet normal 0 0 0\nouter loop\nvertex 0 0 0\n"
     b"vertex 1 0 0\nvertex 0.5 0 0\nendloop\nendfacet", "ASCII 被截断缺 endsolid"),
    (make_binary(box_faces(0, 0, 0, 30, 60, 10))[:-5], "二进制长度不符"),
    (b"\0" * 80 + struct.pack("<I", 5) + b"\0" * 100, "二进制声明面数不符"),
]:
    try:
        stl.parse_stl(bad)
        raise AssertionError(f"应当报错：{label}")
    except stl.STLError:
        print("ok: 拒绝损坏 STL -", label)

# XY 投影为 0：一根沿 Z 的棱（退化面）→ 宽或深为 0
zero_xy = make_ascii([((0, 0, 0), (0, 0, 1), (0, 0, 2))])
try:
    stl.parse_stl(zero_xy)
    raise AssertionError("XY 为零应当报错")
except stl.STLError:
    print("ok: XY 投影为零被拒绝")

# ---------- 求解器 ----------
def inst(i, model_id, w, d, index=1, name=None):
    return {"instance_id": f"t{i}", "model_id": model_id,
            "name": name or f"M{model_id}", "index": index,
            "width_mm": w, "depth_mm": d}


def verify_batches(res, n, pw, pd, gap):
    check(res is not None and len(res) == n, f"批次数 == {n}")
    seen = set()
    total = 0
    for b in res:
        for p in b["placements"]:
            seen.add(p["instance_id"])
            total += 1
            check(p["x_mm"] >= -1e-6 and p["y_mm"] >= -1e-6
                  and p["x_mm"] + p["width_mm"] <= pw + 1e-6
                  and p["y_mm"] + p["depth_mm"] <= pd + 1e-6,
                  f"{p['instance_id']} 在界内")
            check(p["rotation"] in (0, 90), "方向合法")
        ps = b["placements"]
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                a, c = ps[i], ps[j]
                hsep = max(a["x_mm"] - (c["x_mm"] + c["width_mm"]),
                           c["x_mm"] - (a["x_mm"] + a["width_mm"]))
                vsep = max(a["y_mm"] - (c["y_mm"] + c["depth_mm"]),
                           c["y_mm"] - (a["y_mm"] + a["depth_mm"]))
                check(max(hsep, vsep) >= gap - 1e-6,
                      f"间距满足：{a['instance_id']}/{c['instance_id']} "
                      f"(h={hsep:.2f}, v={vsep:.2f}, gap={gap})")
    return seen, total


# 1) 两件 60x60，可用 100x100，gap=10：一件占 0..60，另一件需要 x≥70 → 70+60>100，
#    垂直同理；必须 2 批
items = [inst(1, 1, 60, 60), inst(2, 1, 60, 60, 2)]
res = solver.solve(items, 100, 100, 10)
seen, total = verify_batches(res, 2, 100, 100, 10)
check(total == 2 and seen == {"t1", "t2"}, "两件恰好相切失败 → 2 批")

# gap=0 时同床可放两件（60+60>100? 120>100 — 等等，放不下）
# 改用 50x50 两件，gap=0 宽 100 恰好放两件；gap=1 则需两批
items = [inst(1, 1, 50, 50), inst(2, 1, 50, 50, 2)]
res = solver.solve(items, 100, 100, 0)
verify_batches(res, 1, 100, 100, 0)
check(res[0]["placements"][0]["rotation"] == 0, "gap=0 两件 50x50 同批（1 批）")
res = solver.solve(items, 100, 100, 1)
verify_batches(res, 2, 100, 100, 1)
check(True, "gap=1 两件 50x50 必须分批")

# 2) 30x60 ×4，可用 100x100，gap=2：旋转后 60x30，
#    一行两件 (30+2+30=62 宽，高60)；第二行 y=62+30=92 ≤100，
#    可放 4 件（两行两列：列宽 30,30 行高 60+2+30=92）→ 1 批
items = [inst(i + 1, 2, 30, 60, i + 1) for i in range(4)]
res = solver.solve(items, 100, 100, 2)
seen, total = verify_batches(res, 1, 100, 100, 2)
check(total == 4, "30x60 四件 90° 旋转同批")

# 3) 经典 2D 装箱：5 件 (30x110, 30x110, 45x70, 45x70, 60x45...)
#    做一个面积迫使 2 批的案例：3 件 60x60，区域 100x100，gap=0
#    每件 3600，两件 7200 < 10000 但 60+60>100 → 每批 1 件 → 3 批
items = [inst(i + 1, 3, 60, 60, i + 1) for i in range(3)]
res = solver.solve(items, 100, 100, 0)
verify_batches(res, 3, 100, 100, 0)
check(True, "60x60 三件在 100x100 → 3 批")

# 4) 旋转收益：2 件 80x30 横放在 100x100：
#    0° 时两件 80+80>100（x 排不开），y 30+30<=100 可叠放 → 1 批
items = [inst(1, 4, 80, 30), inst(2, 4, 80, 30, 2)]
res = solver.solve(items, 100, 100, 0)
check(len(res) == 1, "80x30 两件竖直堆叠同批")

# 5) 必须旋转才能放：70x120 的件，区域 100x120 → 0° 放不下（宽 70 ok, 深120 ok 其实放得下）
#    换：120x70，区域 100x120：0° 宽 120>100，90° 后 70x120 放得下
res = solver.solve([inst(1, 5, 120, 70)], 100, 120, 0)
check(res is not None and res[0]["placements"][0]["rotation"] == 90,
      "超宽件旋转 90° 后放入")
check(res[0]["placements"][0]["width_mm"] == 70.0, "旋转后占位为 70x120")

# 6) 单件无论如何放不下 → None
check(solver.solve([inst(1, 6, 121, 121)], 100, 120, 0) is None, "121x121 在 100x120 无解")
check(solver.solve([inst(1, 6, 120, 120)], 100, 120, 1) is None,
      "gap 不影响单件但 120x120 在 100x120 宽度放不下 → None")

# 7) 12 件混合压力测试，确认精确搜索能完成且自洽
import random
random.seed(7)
items = []
for i in range(12):
    w = random.choice([20, 25, 30, 40, 45])
    d = random.choice([20, 25, 30, 40, 55])
    items.append(inst(i + 1, i + 1, w, d, 1))
res = solver.solve(items, 100, 100, 3)
seen, total = verify_batches(res, len(res), 100, 100, 3)
check(total == 12 and len(seen) == 12, f"12 件混合：{len(res)} 批，全部覆盖")

# 8) 最优性抽查：面积下界决定批次
#    区域 100x100=10000，3 件 70x50(3500 每件)：总面积 10500 → ≥2 批；
#    同批两件 70+50 方向可 70x50 + 50x70？检查：能否 2 件同批？
#    70x50 与 50x70：放 (0,0) 和 (50,30?) — 用求解器验证自洽即可
items = [inst(i + 1, 7, 70, 50, i + 1) for i in range(3)]
res = solver.solve(items, 100, 100, 0)
check(len(res) == 2, f"总面积 10500 > 10000 → ≥2 批，实际 {len(res)}")
verify_batches(res, len(res), 100, 100, 0)

print("\n全部核心测试通过 ✔")
