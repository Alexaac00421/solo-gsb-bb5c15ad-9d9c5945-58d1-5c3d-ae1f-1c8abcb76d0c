"""STL 解析（ASCII 与二进制），仅提取轴对齐包围盒。

约定：
- 尺寸单位视为毫米（STL 本身不携带单位，由用户保证）。
- 至少 1 个三角面；顶点必须是有限浮点数。
- XY 投影必须有正的面积（零宽/零深无法作为排版占位）。
- Z 高度允许为 0。
"""
import math
import struct


class STLError(ValueError):
    """STL 文件损坏或内容无效。"""


def _parse_ascii(data):
    """解析 ASCII STL，返回 (顶点可迭代解析结果, 三角面数)。

    严格匹配 facet normal ... outer loop / 3× vertex / endloop / endfacet，
    块之间允许任意空白。
    """
    import re

    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise STLError("不是合法的 ASCII STL（含非 ASCII 字节）") from exc

    if not re.match(r"\s*solid(\s|$)", text):
        raise STLError("ASCII STL 必须以 'solid' 开头")
    if "endsolid" not in text:
        raise STLError("ASCII STL 缺少 'endsolid'，文件可能被截断")

    token_re = re.compile(
        r"\s*facet\s+normal\s+"
        r"(\S+)\s+(\S+)\s+(\S+)\s+"
        r"outer\s+loop\s+"
        r"vertex\s+(\S+)\s+(\S+)\s+(\S+)\s+"
        r"vertex\s+(\S+)\s+(\S+)\s+(\S+)\s+"
        r"vertex\s+(\S+)\s+(\S+)\s+(\S+)\s+"
        r"endloop\s+endfacet",
        re.ASCII,
    )

    def to_float(s, where):
        try:
            v = float(s)
        except ValueError as exc:
            raise STLError(f"无法解析的数值 '{s}'（{where}）") from exc
        if not math.isfinite(v):
            raise STLError(f"{where} 包含非有限数值（NaN/无穷大）")
        return v

    pos = re.match(r"\s*solid[^\n]*", text).end()
    vertices = []
    count = 0
    while True:
        m = token_re.match(text, pos)
        if not m:
            break
        count += 1
        groups = m.groups()
        for i in range(3):  # 3 个 vertex，每组 3 个数（normal 的 3 个数跳过）
            x = to_float(groups[3 + i * 3], f"第 {count} 个三角面顶点 X")
            y = to_float(groups[4 + i * 3], f"第 {count} 个三角面顶点 Y")
            z = to_float(groups[5 + i * 3], f"第 {count} 个三角面顶点 Z")
            vertices.append((x, y, z))
        pos = m.end()

    tail = text[pos:]
    m_end = re.search(r"endsolid[^\n]*", tail)
    if m_end is None:
        raise STLError("ASCII STL 缺少 'endsolid'，文件可能被截断")
    # 最后一个三角面之后到 endsolid 之间只允许空白
    if tail[: m_end.start()].strip():
        raise STLError("ASCII STL 中 'endfacet' 与 'endsolid' 之间存在无法识别的内容")
    if count == 0:
        raise STLError("ASCII STL 不包含任何三角面")
    return vertices, count


def _parse_binary(data):
    """解析二进制 STL。"""
    if len(data) < 84:
        raise STLError("二进制 STL 长度不足 84 字节，文件已损坏或被截断")
    (n_tri,) = struct.unpack_from("<I", data, 80)
    expected = 84 + n_tri * 50
    if len(data) != expected:
        raise STLError(
            f"二进制 STL 长度异常：头部声明 {n_tri} 个三角面，"
            f"应有 {expected} 字节，实际 {len(data)} 字节"
        )

    vertices = []
    off = 84
    for i in range(n_tri):
        # normal(3f) + 3 个 vertex(各 3f) + 属性(2B)
        vals = struct.unpack_from("<12fH", data, off)
        for x, y, z in (vals[3:6], vals[6:9], vals[9:12]):
            for axis, v in zip("XYZ", (x, y, z)):
                if not math.isfinite(v):
                    raise STLError(f"第 {i + 1} 个三角面顶点 {axis} 为非有限数值")
            vertices.append((x, y, z))
        off += 50
    if n_tri == 0:
        raise STLError("二进制 STL 不包含任何三角面")
    return vertices, n_tri


def _looks_ascii(data):
    """第一遍粗判：ASCII 文件以 solid 开头且头部区域无 NUL。"""
    head = data[:512]
    if not head.lstrip()[:5].lower().startswith(b"solid"):
        return False
    if b"\x00" in head:
        return False
    return True


def parse_stl(data):
    """解析 STL 字节串，返回 {"width_mm","depth_mm","height_mm","triangles","size_mm"}。

    判定策略：先尝试 ASCII（要求 solid 头且无 NUL），再尝试二进制；
    两种格式都无法通过严格校验时报错。
    """
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        raise STLError("文件为空")
    data = bytes(data)

    vertices = None
    triangles = 0
    if _looks_ascii(data):
        try:
            vertices, triangles = _parse_ascii(data)
        except STLError:
            vertices = None  # 落到二进制分支

    if vertices is None:
        vertices, triangles = _parse_binary(data)

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    w = max(xs) - min(xs)
    d = max(ys) - min(ys)
    h = max(zs) - min(zs)

    if w <= 0 or d <= 0:
        raise STLError(
            f"模型 XY 投影面积为 0（宽 {w:.3f} × 深 {d:.3f} mm），无法作为排版占位"
        )

    return {
        "width_mm": round(w, 6),
        "depth_mm": round(d, 6),
        "height_mm": round(h, 6),
        "triangles": triangles,
        "size_mm": len(data),
    }
