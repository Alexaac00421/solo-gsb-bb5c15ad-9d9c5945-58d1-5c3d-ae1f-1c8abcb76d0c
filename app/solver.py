"""多批次二维矩形排版求解器（精确搜索）。

问题：每个实例是模型 XY 投影的轴对齐外接矩形，
只能取 0°/90°（即 (w, d) 或 (d, w)），需把所有实例
放入尽可能少的矩形批次（打印床去掉四边留白后的可用区域）。
任意两件之间水平净距 ≥ gap 或垂直净距 ≥ gap。

规模上限为 12 个实例，采用两层精确搜索，保证最优批次数：

1) 批次分配（bin packing）：逐件把实例分配到批次，
   - 总面积下界起步；空批次等价只试第一个；
   - 相同占位面的实例强制进入非递减批次，破除对称性。
2) 单批可行性（2D 正交装箱）：DFS + MRV，候选位置取已放件
   四边构成的完备网格点，并以“左/下支撑集合”去重，再用
   “剩余尺寸多重集 + 布局签名”做失败记忆。

间距处理（外扩变换）：把每个占位向四周外扩 gap/2 得到虚拟
矩形，其左下角相对原坐标偏移 gap/2。虚拟矩形互不相交 ⇔ 原
占位之间水平或垂直净距 ≥ gap；原件仍可贴原可用区域边缘
（虚拟矩形允许的位置范围已相应处理）。
"""
import math

EPS = 1e-9


def _orientations(w, d):
    """去重后的 (宽, 深) 方向列表，0° 在前。"""
    if math.isclose(w, d, abs_tol=EPS):
        return [(w, d)]
    return [(w, d), (d, w)]


def _candidate_points(placed, origin=(0.0, 0.0)):
    """候选左下角点：X = 已放件左右边集合，Y = 已放件上下边集合。

    始终包含原点。取网格组合后由碰撞检测过滤。placed 中坐标均
    为“虚拟矩形”坐标，origin 为原件贴左下边缘时的虚拟坐标。
    """
    ox, oy = origin
    xs = {round(ox, 6)}
    ys = {round(oy, 6)}
    for w, d, x, y, *_ in placed:
        xs.add(round(x, 6))
        xs.add(round(x + w, 6))
        ys.add(round(y, 6))
        ys.add(round(y + d, 6))
    return [(x, y) for y in sorted(ys) for x in sorted(xs)]


def can_pack(items, area_w, area_d, gap):
    """判断一批 items 能否装入单个矩形；成功返回放置列表，否则 None。

    items: [(w, d, *payload), ...]，w/d 为原始占位尺寸。
    返回: [(item, placed_w, placed_d, real_x, real_y), ...]，
    坐标为原坐标系（可用区域左下角为原点）。

    实现采用“外扩”变换：虚拟矩形尺寸 (w+g, d+g)，左下角
    (u, v) = (x+g/2, y+g/2)，虚拟区域为 [0, W+g]×[0, D+g]。
    原件贴原区域边缘 ⇔ 虚拟矩形贴虚拟区域边缘；虚拟矩形互不相交
    ⇔ 原件水平或垂直净距 ≥ g。从而把带间距问题化为普通装箱。

    精确性与剪枝：
    - 候选位置为已放件四边构成的网格点（含原点），集合完备；
    - “支撑集合去重”：同一物件的多个候选位置若左侧接触集合与
      下侧接触集合相同，则只保留一个代表位置（它们导致完全相同
      的剩余可行空间），不损失完备性；
    - 失败记忆：以“剩余尺寸多重集 + 已放布局签名”缓存失败状态；
    - 每次选择可行位置最少的物件（MRV）。
    """
    g = float(gap)
    h = g / 2.0

    # 面积剪枝：原占位面积之和必须放得下（注意不能用虚拟面积，
    # 因为各件外扩的“半个间隙”区域会相互重叠，其和可超过 W*D）。
    if sum(it[0] * it[1] for it in items) > area_w * area_d + EPS:
        return None

    placements = []  # 虚拟矩形: [(ew, ed, ux, uy, item, w, d)]
    fail_memo = set()

    def collides(ew, ed, ux, uy, rw, rd):
        # 边界：原左下角 (ux-h, uy-h)，原尺寸 (rw, rd) 必须在区域内
        if ux - h < -EPS or uy - h < -EPS:
            return True
        if ux - h + rw > area_w + EPS or uy - h + rd > area_d + EPS:
            return True
        # 件间：虚拟矩形两两不相交（边相切允许，故用 > EPS）
        for k, (pw, pd, px, py, *_x) in enumerate(placements):
            overlap_x = min(ux + ew, px + pw) - max(ux, px)
            overlap_y = min(uy + ed, py + pd) - max(uy, py)
            if overlap_x > EPS and overlap_y > EPS:
                return True
        return False

    def contacts(ux, uy, ew, ed):
        """返回 (左边接触集合, 下边接触集合)：
        左边沿相切的已放件右边/区域左边界，下边沿相切的已放件上边/区域底边界。"""
        left, below = set(), set()
        if abs(ux - h) <= 1e-6:
            left.add(-1)  # 区域左边界
        if abs(uy - h) <= 1e-6:
            below.add(-1)  # 区域底边界
        for k, (pw, pd, px, py, *_x) in enumerate(placements):
            if abs(px + pw - ux) <= 1e-6 and uy + ed > py + EPS and py + pd > uy + EPS:
                left.add(k)
            if abs(py + pd - uy) <= 1e-6 and ux + ew > px + EPS and px + pw > ux + EPS:
                below.add(k)
        return frozenset(left), frozenset(below)

    def layout_sig():
        # 已放虚拟矩形的归一化签名（排序，与放置先后无关）
        return tuple(sorted(
            (round(w, 6), round(d, 6), round(x, 6), round(y, 6))
            for w, d, x, y, *_x in placements
        ))

    def dfs(remaining):
        if not remaining:
            return True
        memo_key = (
            tuple(sorted((round(it[0], 6), round(it[1], 6)) for it in remaining)),
            layout_sig(),
        )
        if memo_key in fail_memo:
            return False

        choices = []
        for idx, (w0, d0, *_rest) in enumerate(remaining):
            positions = []
            seen_support = set()
            for w, d in _orientations(w0, d0):
                ew, ed = w + g, d + g
                for ux, uy in _candidate_points(placements, origin=(h, h)):
                    if not collides(ew, ed, ux, uy, w, d):
                        support = contacts(ux, uy, ew, ed)
                        if support in seen_support:
                            continue
                        seen_support.add(support)
                        positions.append((ux, uy, ew, ed, w, d))
            if not positions:
                fail_memo.add(memo_key)
                return False
            choices.append((len(positions), idx, positions))
        choices.sort(key=lambda c: (c[0], -max(remaining[c[1]][0], remaining[c[1]][1])))
        _, idx, positions = choices[0]
        item = remaining[idx]
        rest = remaining[:idx] + remaining[idx + 1:]

        seen = set()
        for ux, uy, ew, ed, w, d in positions:
            key = (round(ux, 6), round(uy, 6), round(ew, 6), round(ed, 6))
            if key in seen:
                continue
            seen.add(key)
            placements.append((ew, ed, ux, uy, item, w, d))
            if dfs(rest):
                return True
            placements.pop()
        fail_memo.add(memo_key)
        return False

    if dfs(list(items)):
        return [
            (item, w, d, ux - h, uy - h)
            for ew, ed, ux, uy, item, w, d in placements
        ]
    return None


def _extend_layout(base_virtual, item, area_w, area_d, gap):
    """在已有虚拟矩形布局上为单个新件寻找一个合法位置（快速启发式）。

    base_virtual: 已放件的虚拟矩形 [(ew, ed, ux, uy, full_item)]
    成功返回 can_pack 同款格式 [(full_item, pw, pd, real_x, real_y), ...]，
    失败返回 None。
    """
    g = float(gap)
    h = g / 2.0
    w0, d0 = item[0], item[1]

    def collides(ew, ed, ux, uy, rw, rd):
        if ux - h < -EPS or uy - h < -EPS:
            return True
        if ux - h + rw > area_w + EPS or uy - h + rd > area_d + EPS:
            return True
        for pw, pd, px, py, *_x in base_virtual:
            ox = min(ux + ew, px + pw) - max(ux, px)
            oy = min(uy + ed, py + pd) - max(uy, py)
            if ox > EPS and oy > EPS:
                return True
        return False

    for w, d in _orientations(w0, d0):
        ew, ed = w + g, d + g
        for ux, uy in _candidate_points(base_virtual, origin=(h, h)):
            if not collides(ew, ed, ux, uy, w, d):
                out = []
                for ew2, ed2, ux2, uy2, it2 in base_virtual:
                    # 从虚拟尺寸还原原尺寸/方向
                    pw2, pd2 = ew2 - g, ed2 - g
                    out.append((it2, pw2, pd2, ux2 - h, uy2 - h))
                out.append((item, w, d, ux - h, uy - h))
                return out
    return None


def solve(instances, area_w, area_d, gap):
    """求最小批次数。

    instances: [{"instance_id","model_id","name","index",
                 "width_mm","depth_mm"}]
    坐标系：可用区域左下角为 (0, 0)。
    成功返回批次列表；若有单件放不下返回 None。
    """
    if not instances:
        return []
    area_w, area_d, gap = float(area_w), float(area_d), float(gap)

    # 单件预检
    for inst in instances:
        if not any(
            pw <= area_w + EPS and pd <= area_d + EPS
            for pw, pd in _orientations(inst["width_mm"], inst["depth_mm"])
        ):
            return None

    # (w, d, instance_id, model_id, name, index)，大边/面积优先
    items = sorted(
        (
            (
                float(i["width_mm"]),
                float(i["depth_mm"]),
                i["instance_id"],
                i["model_id"],
                i["name"],
                i["index"],
            )
            for i in instances
        ),
        key=lambda it: (-max(it[0], it[1]), -(it[0] * it[1])),
    )
    n = len(items)
    total_area = sum(w * d for w, d, *_ in items)
    lb = max(1, math.ceil(total_area / (area_w * area_d) - EPS))

    def same_footprint(a, b):
        return (max(a[0], a[1]), min(a[0], a[1])) == (
            max(b[0], b[1]),
            min(b[0], b[1]),
        )

    for n_bins in range(lb, n + 1):
        bins = [[] for _ in range(n_bins)]
        layouts = [[] for _ in range(n_bins)]  # 各批当前的具体布局
        # 同一 n_bins 尝试内缓存“内容键 → 单批布局”，避免重复搜索
        pack_cache = {}

        def content_key(content):
            return tuple((round(it[0], 6), round(it[1], 6), it[2]) for it in content)

        def check_add(b, item):
            """尝试把 item 加入第 b 批；成功返回布局列表并写入 layouts[b]。"""
            content = bins[b]
            w, d = item[0], item[1]
            gv = gap
            hv = gv / 2.0
            used = sum(it[0] * it[1] for it in content)
            if content and used + w * d > area_w * area_d + EPS:
                return None

            # 1) 快速尝试：在现有布局上直接为新件找空位（最常见的成功路径）
            if content:
                base = [
                    (pw + gv, pd + gv, px + hv, py + hv, it)
                    for it, pw, pd, px, py in layouts[b]
                ]
                quick = _extend_layout(base, item, area_w, area_d, gv)
                if quick is not None:
                    return quick

            # 2) 完整重排（带缓存）
            new_content = content + [item]
            key = content_key(new_content)
            if key not in pack_cache:
                pack_cache[key] = can_pack(new_content, area_w, area_d, gap)
            return pack_cache[key]

        def dfs(pos, prev_bin):
            if pos == n:
                return True
            item = items[pos]
            # 与上一件占位面相同：只进入编号不小于上一件的批次，破除对称
            start = 0
            if pos > 0 and same_footprint(items[pos - 1], item):
                start = prev_bin
            first_empty = next((b for b, c in enumerate(bins) if not c), n_bins)
            for b in range(start, n_bins):
                if bins[b]:
                    old_layout = layouts[b]
                    packed = check_add(b, item)
                    if packed is None:
                        continue
                    bins[b].append(item)
                    layouts[b] = packed
                    if dfs(pos + 1, b):
                        return True
                    layouts[b] = old_layout
                    bins[b].pop()
                else:
                    if b != first_empty:
                        break  # 所有空批次等价，只试第一个
                    bins[b].append(item)
                    layouts[b] = can_pack([item], area_w, area_d, gap)
                    if dfs(pos + 1, b):
                        return True
                    layouts[b] = []
                    bins[b].pop()
            return False

        if dfs(0, 0):
            result = []
            for order, (content, packed0) in enumerate(
                ((c, l) for c, l in zip(bins, layouts) if c), start=1
            ):
                key = content_key(content)
                packed = packed0 if packed0 else pack_cache.get(key)
                if packed is None:
                    packed = can_pack(content, area_w, area_d, gap)
                entries = []
                for (w, d, iid, model_id, name, index), pw, pd, x, y in packed:
                    rotation = (
                        0
                        if math.isclose(pw, w, abs_tol=EPS)
                        and math.isclose(pd, d, abs_tol=EPS)
                        else 90
                    )
                    entries.append({
                        "instance_id": iid,
                        "model_id": model_id,
                        "name": name,
                        "index": index,
                        "rotation": rotation,
                        "x_mm": round(max(x, 0.0), 3),
                        "y_mm": round(max(y, 0.0), 3),
                        "width_mm": round(pw, 3),
                        "depth_mm": round(pd, 3),
                    })
                entries.sort(key=lambda e: (e["y_mm"], e["x_mm"]))
                result.append({"batch": order, "placements": entries})
            return result
    return None
