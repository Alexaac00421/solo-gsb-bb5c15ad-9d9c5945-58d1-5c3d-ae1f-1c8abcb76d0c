"""STL 文件解析（ASCII / 二进制，单位毫米）。

只关心所有顶点在 XY 平面上的投影，用于计算轴对齐外接矩形。
解析失败时抛出 STLError，消息为用户可读的中文原因。
"""

import math
import re
import struct


class STLError(Exception):
    """STL 文件损坏或无法识别。"""


_VERTEX_RE = re.compile(r"^\s*vertex\s+(\S+)\s+(\S+)\s+(\S+)\s*$", re.IGNORECASE)

# 单文件上限，防止异常大文件拖垮服务（二进制 STL 50 字节/三角形）
MAX_STL_BYTES = 64 * 1024 * 1024


def _finish(tri_count, xs, ys):
    if tri_count == 0 or not xs:
        raise STLError("文件中没有有效的三角形")
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    width = maxx - minx
    height = maxy - miny
    if not (width > 0 and height > 0):
        raise STLError(
            "模型的 XY 投影退化（宽或高为 0），无法作为矩形占位排版"
        )
    return tri_count, minx, miny, maxx, maxy


def _parse_binary(data, tri_count):
    xs = []
    ys = []
    offset = 84
    for t in range(tri_count):
        vals = struct.unpack_from("<12f", data, offset)
        for v in range(3):
            x = vals[3 + v * 3]
            y = vals[4 + v * 3]
            z = vals[5 + v * 3]
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                raise STLError(f"第 {t + 1} 个三角形包含非法坐标（NaN/Inf）")
            xs.append(x)
            ys.append(y)
        offset += 50
    return _finish(tri_count, xs, ys)


def _parse_ascii(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except UnicodeDecodeError:
            raise STLError("既不是结构完整的二进制 STL，也不是可解码的 ASCII STL")
    if "solid" not in text[:512].lower():
        raise STLError("缺少 solid 头，不是可识别的 ASCII STL")
    xs = []
    ys = []
    for lineno, line in enumerate(text.splitlines(), 1):
        m = _VERTEX_RE.match(line)
        if not m:
            continue
        try:
            x, y, z = float(m.group(1)), float(m.group(2)), float(m.group(3))
        except ValueError:
            raise STLError(f"第 {lineno} 行顶点坐标无法解析")
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            raise STLError(f"第 {lineno} 行顶点坐标非法（NaN/Inf）")
        xs.append(x)
        ys.append(y)
    if len(xs) % 3 != 0:
        raise STLError("顶点数量不是 3 的倍数，STL 数据不完整")
    return _finish(len(xs) // 3, xs, ys)


def parse_stl(data):
    """解析 STL 字节流。

    返回 (tri_count, minx, miny, maxx, maxy)，单位毫米。
    失败抛出 STLError。
    """
    if not data:
        raise STLError("文件为空")
    if len(data) > MAX_STL_BYTES:
        raise STLError("文件过大（超过 64 MB）")
    # 二进制 STL：80 字节头 + 4 字节三角形数 + 每三角形 50 字节，长度须精确匹配
    if len(data) >= 84:
        (tri_count,) = struct.unpack_from("<I", data, 80)
        if tri_count > 0 and 84 + tri_count * 50 == len(data):
            return _parse_binary(data, tri_count)
    return _parse_ascii(data)
