"""生成示例模型：20 × 10 × 5 mm 长方体的 ASCII STL（examples/box_20x10x5.stl）。"""

import os

W, H, D = 20.0, 10.0, 5.0

# 长方体 8 个顶点
V = [(x, y, z) for x in (0, W) for y in (0, H) for z in (0, D)]
# 12 个三角形（顶点下标按上面 V 的顺序：x*4 + y*2 + z）
TRIS = [
    (0, 2, 1), (1, 2, 3),  # 底面 z=0
    (4, 5, 6), (5, 7, 6),  # 顶面 z=D
    (0, 1, 4), (1, 5, 4),  # 前面 y=0
    (2, 6, 3), (3, 6, 7),  # 后面 y=H
    (0, 4, 2), (2, 4, 6),  # 左面 x=0
    (1, 3, 5), (3, 7, 5),  # 右面 x=W
]


def main():
    lines = ["solid box"]
    for a, b, c in TRIS:
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        for idx in (a, b, c):
            x, y, z = V[idx]
            lines.append(f"      vertex {x} {y} {z}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid box")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "box_20x10x5.stl")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("written:", path)


if __name__ == "__main__":
    main()
