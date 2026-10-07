"""排版求解器：把同一模型的若干份矩形占位装入打印床，求最小批次数。

模型（OR-Tools CP-SAT，精确求解）：
- 占位为模型原始 XY 投影的轴对齐外接矩形，仅允许绕 Z 轴旋转 0°/90°。
- 间距约束：任意两件须满足水平或垂直方向至少 spacing 的分隔。
  等价于把每个占位向右、向上各膨胀 spacing 后互不重叠（左/下侧的
  间距由对方的膨胀保证）。
- 每个占位（实际尺寸，不含膨胀）必须完整落在留白内的打印区中。
- 坐标先按 0.01mm 缩放为整数，求解后再换算回毫米。
"""

from ortools.sat.python import cp_model

SCALE = 100  # 0.01 mm 精度
MAX_COPIES = 12
DEFAULT_TIME_LIMIT = 10.0


class PackingError(Exception):
    """排版不可行或输入非法，消息为用户可读的中文原因。"""


def _to_int(mm):
    return int(round(mm * SCALE))


def _to_mm(units):
    return units / SCALE


def solve_layout(print_w, print_h, rect_w, rect_h, spacing, copies,
                 time_limit=DEFAULT_TIME_LIMIT):
    """在 print_w × print_h（留白内区域，毫米）中排版 copies 个 rect_w × rect_h。

    返回 {
        "batches": [[{"copy", "rotation", "x", "y", "width", "height"}, ...], ...],
        "batch_count": int,
        "proven_optimal": bool,
    }
    坐标为占位左下角在打印区局部坐标系中的毫米值（原点在打印区左下角）。
    不可行时抛出 PackingError。
    """
    if not (1 <= copies <= MAX_COPIES):
        raise PackingError(f"份数须为 1–{MAX_COPIES} 的整数")
    if print_w <= 0 or print_h <= 0:
        raise PackingError("留白后的打印区尺寸必须为正")
    if rect_w <= 0 or rect_h <= 0:
        raise PackingError("模型占位尺寸必须为正")
    if spacing < 0:
        raise PackingError("间距不能为负")

    pW, pH = _to_int(print_w), _to_int(print_h)
    w0, h0, s = _to_int(rect_w), _to_int(rect_h), _to_int(spacing)
    n = copies

    fits = (w0 <= pW and h0 <= pH) or (h0 <= pW and w0 <= pH)
    if not fits:
        raise PackingError(
            "单件无法放入打印区：占位 %.2f×%.2f mm（旋转 90° 后为 %.2f×%.2f mm），"
            "打印区仅 %.2f×%.2f mm" % (rect_w, rect_h, rect_h, rect_w, print_w, print_h)
        )

    m = cp_model.CpModel()
    lo = min(w0, h0)

    rot = [m.new_bool_var(f"rot_{i}") for i in range(n)]
    w = []
    h = []
    for i in range(n):
        wi = m.new_int_var(lo, max(w0, h0), f"w_{i}")
        hi = m.new_int_var(lo, max(w0, h0), f"h_{i}")
        m.add(wi == w0 + (h0 - w0) * rot[i])
        m.add(hi == h0 + (w0 - h0) * rot[i])
        w.append(wi)
        h.append(hi)
    if w0 == h0:  # 正方形占位旋转无意义，固定方向消除对称
        for i in range(n):
            m.add(rot[i] == 0)

    x = [m.new_int_var(0, pW - lo, f"x_{i}") for i in range(n)]
    y = [m.new_int_var(0, pH - lo, f"y_{i}") for i in range(n)]
    # 实际占位必须完整落在打印区内
    for i in range(n):
        m.add(x[i] + w[i] <= pW)
        m.add(y[i] + h[i] <= pH)

    # 向右/向上膨胀 spacing 后的“放置矩形”，用于无重叠约束
    pw = [m.new_int_var(lo + s, max(w0, h0) + s, f"pw_{i}") for i in range(n)]
    ph = [m.new_int_var(lo + s, max(w0, h0) + s, f"ph_{i}") for i in range(n)]
    xend = [m.new_int_var(0, pW + max(w0, h0) + s, f"xend_{i}") for i in range(n)]
    yend = [m.new_int_var(0, pH + max(w0, h0) + s, f"yend_{i}") for i in range(n)]
    for i in range(n):
        m.add(pw[i] == w[i] + s)
        m.add(ph[i] == h[i] + s)
        m.add(xend[i] == x[i] + pw[i])
        m.add(yend[i] == y[i] + ph[i])

    # 批次分配：n 件至多 n 批；used[b] 表示批次 b 是否被使用
    assign = [[m.new_bool_var(f"a_{i}_{b}") for b in range(n)] for i in range(n)]
    used = [m.new_bool_var(f"used_{b}") for b in range(n)]
    for i in range(n):
        m.add_exactly_one(assign[i][b] for b in range(n))
    for b in range(n):
        m.add_max_equality(used[b], [assign[i][b] for i in range(n)])

    # 每批内部：膨胀后的放置矩形两两不重叠（即水平或垂直分隔 ≥ spacing）
    for b in range(n):
        x_ivs = []
        y_ivs = []
        for i in range(n):
            x_ivs.append(
                m.new_optional_interval_var(
                    x[i], pw[i], xend[i], assign[i][b], f"xiv_{i}_{b}")
            )
            y_ivs.append(
                m.new_optional_interval_var(
                    y[i], ph[i], yend[i], assign[i][b], f"yiv_{i}_{b}")
            )
        m.add_no_overlap_2d(x_ivs, y_ivs)

    # 对称性破缺：批次按序启用；第 i 件不进入编号 > i 的批次
    for b in range(n - 1):
        m.add(used[b + 1] <= used[b])
    for i in range(n):
        for b in range(i + 1, n):
            m.add(assign[i][b] == 0)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8

    def snapshot():
        return {
            "assign": [[solver.value(assign[i][b]) for b in range(n)]
                       for i in range(n)],
            "rot": [solver.value(rot[i]) for i in range(n)],
            "x": [solver.value(x[i]) for i in range(n)],
            "y": [solver.value(y[i]) for i in range(n)],
            "w": [solver.value(w[i]) for i in range(n)],
            "h": [solver.value(h[i]) for i in range(n)],
        }

    # 阶段一：最小化批次数（须证明最优）
    m.minimize(sum(used))
    solver.parameters.max_time_in_seconds = time_limit * 0.7
    status = solver.solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # 单件可放时每件一批必然可行，走到这里说明输入异常
        raise PackingError("求解失败：未找到可行排布")
    proven_optimal = status == cp_model.OPTIMAL
    best_batches = int(round(solver.objective_value))
    sol = snapshot()

    # 阶段二：批次数不变，让占位尽量靠左下，排布更紧凑整齐
    m.add(sum(used) <= best_batches)
    m.minimize(sum(x) + sum(y))
    solver.parameters.max_time_in_seconds = time_limit * 0.3
    status = solver.solve(m)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        sol = snapshot()  # 否则保留阶段一的解

    batches = {}
    for i in range(n):
        b = next(b for b in range(n) if sol["assign"][i][b])
        batches.setdefault(b, []).append({
            "copy": i + 1,
            "rotation": 90 if sol["rot"][i] else 0,
            "x": _to_mm(sol["x"][i]),
            "y": _to_mm(sol["y"][i]),
            "width": _to_mm(sol["w"][i]),
            "height": _to_mm(sol["h"][i]),
        })
    ordered = [sorted(v, key=lambda e: e["copy"]) for _, v in sorted(batches.items())]
    return {
        "batches": ordered,
        "batch_count": len(ordered),
        "proven_optimal": proven_optimal,
    }
