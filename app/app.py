"""Flask Web 应用：床参数配置、STL 上传、排版求解与 JSON 导出。"""
import json
import os

from flask import Flask, jsonify, render_template, request, send_file

from . import config as cfg
from . import db, solver, stl

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 单个 STL 上限 64MB


def init():
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    db.init_db()


def bad_request(msg, status=400):
    return jsonify({"error": msg}), status


def num(value, field, minimum=0.0, strict=False, maximum=None):
    """校验数值参数。strict=True 时要求严格大于 minimum。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} 必须是数字")
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"{field} 不能为 NaN 或无穷大")
    if strict and v <= minimum:
        raise ValueError(f"{field} 必须大于 {minimum:g}")
    if not strict and v < minimum:
        raise ValueError(f"{field} 不能小于 {minimum:g}")
    if maximum is not None and v > maximum:
        raise ValueError(f"{field} 不能大于 {maximum:g}")
    return v


def validate_config(data):
    """校验并返回规整化的床参数。"""
    required = ("bed_width_mm", "bed_depth_mm", "margin_mm", "gap_mm")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError("缺少参数：" + "、".join(missing))
    width = num(data["bed_width_mm"], "打印床宽度", strict=True, maximum=100000)
    depth = num(data["bed_depth_mm"], "打印床深度", strict=True, maximum=100000)
    margin = num(data["margin_mm"], "四边留白", minimum=0.0, maximum=100000)
    gap = num(data["gap_mm"], "模型间距", minimum=0.0, maximum=100000)
    if 2 * margin >= width - 1e-9:
        raise ValueError(f"四边留白（{margin:g} mm）过大：留白后可用宽度 {width - 2 * margin:g} mm 必须为正")
    if 2 * margin >= depth - 1e-9:
        raise ValueError(f"四边留白（{margin:g} mm）过大：留白后可用深度 {depth - 2 * margin:g} mm 必须为正")
    return {
        "bed_width_mm": round(width, 3),
        "bed_depth_mm": round(depth, 3),
        "margin_mm": round(margin, 3),
        "gap_mm": round(gap, 3),
    }


def state_payload(conn):
    conf = db.get_config(conn)
    models = db.list_models(conn)
    total = sum(m["copies"] for m in models)
    printable = {
        "width_mm": round(conf["bed_width_mm"] - 2 * conf["margin_mm"], 3),
        "depth_mm": round(conf["bed_depth_mm"] - 2 * conf["margin_mm"], 3),
    }
    return {
        "config": conf,
        "models": models,
        "solution": db.get_solution(conn),
        "printable": printable,
        "total_instances": total,
        "max_total_instances": cfg.MAX_TOTAL_INSTANCES,
    }


def build_instances(conn, models, conf):
    """把每个模型按份数展开为实例；返回 (instances, 放不下的模型名列表)。"""
    pw = conf["bed_width_mm"] - 2 * conf["margin_mm"]
    pd = conf["bed_depth_mm"] - 2 * conf["margin_mm"]
    instances, oversized = [], []
    for m in models:
        w, d = m["width_mm"], m["depth_mm"]
        fits = (w <= pw + 1e-9 and d <= pd + 1e-9) or (
            d <= pw + 1e-9 and w <= pd + 1e-9
        )
        if not fits:
            oversized.append(f"{m['name']}（{w:g}×{d:g} mm）")
        for i in range(1, m["copies"] + 1):
            instances.append({
                "instance_id": f"m{m['id']}-{i}",
                "model_id": m["id"],
                "name": m["name"],
                "index": i,
                "width_mm": w,
                "depth_mm": d,
            })
    return instances, oversized


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def get_state():
    with db.get_conn() as conn:
        return jsonify(state_payload(conn))


@app.post("/api/config")
def post_config():
    try:
        conf = validate_config(request.get_json(silent=True) or {})
    except ValueError as exc:
        return bad_request(str(exc))
    with db.get_conn() as conn:
        db.set_config(conn, conf)  # 内部同时令旧排布失效
        return jsonify(state_payload(conn))


@app.post("/api/models")
def upload_model():
    f = request.files.get("file")
    if f is None or not f.filename:
        return bad_request("缺少 STL 文件（表单字段名 file）")
    copies_raw = request.form.get("copies", "1")
    try:
        copies = int(copies_raw)
        if str(copies) != str(copies_raw).strip() or not (1 <= copies <= cfg.MAX_TOTAL_INSTANCES):
            raise ValueError
    except (TypeError, ValueError):
        return bad_request(f"份数必须是 1~{cfg.MAX_TOTAL_INSTANCES} 的整数")

    name = os.path.basename(f.filename)
    data = f.read()
    try:
        dims = stl.parse_stl(data)
    except stl.STLError as exc:
        return bad_request(f"STL 解析失败（{name}）：{exc}")

    with db.get_conn() as conn:
        existing = conn.execute("SELECT id FROM models WHERE name=?", (name,)).fetchone()
        others = db.total_copies(conn, exclude_id=existing["id"] if existing else None)
        if others + copies > cfg.MAX_TOTAL_INSTANCES:
            return bad_request(
                f"实例总数将为 {others + copies}，超过上限 {cfg.MAX_TOTAL_INSTANCES}；请先减少其他模型份数"
            )
        # 单件是否放得下，用当前床参数给出明确原因
        conf = db.get_config(conn)
        pw = conf["bed_width_mm"] - 2 * conf["margin_mm"]
        pd = conf["bed_depth_mm"] - 2 * conf["margin_mm"]
        w, d = dims["width_mm"], dims["depth_mm"]
        if not ((w <= pw + 1e-9 and d <= pd + 1e-9) or (d <= pw + 1e-9 and w <= pd + 1e-9)):
            return bad_request(
                f"单件无法放入：模型 {name} 占位 {w:g}×{d:g} mm，"
                f"当前留白内可用区域仅 {pw:g}×{pd:g} mm（允许旋转 90°）"
            )
        db.upsert_model(conn, name, dims["size_mm"], dims, dims["triangles"], copies)
        return jsonify(state_payload(conn))


@app.patch("/api/models/<int:model_id>")
def patch_model(model_id):
    body = request.get_json(silent=True) or {}
    if "copies" not in body:
        return bad_request("缺少 copies 参数")
    try:
        copies = int(body["copies"])
        if str(copies) != str(body["copies"]).strip() or not (1 <= copies <= cfg.MAX_TOTAL_INSTANCES):
            raise ValueError
    except (TypeError, ValueError):
        return bad_request(f"份数必须是 1~{cfg.MAX_TOTAL_INSTANCES} 的整数")

    with db.get_conn() as conn:
        if db.get_model(conn, model_id) is None:
            return bad_request("模型不存在", 404)
        others = db.total_copies(conn, exclude_id=model_id)
        if others + copies > cfg.MAX_TOTAL_INSTANCES:
            return bad_request(
                f"实例总数将为 {others + copies}，超过上限 {cfg.MAX_TOTAL_INSTANCES}"
            )
        db.update_copies(conn, model_id, copies)
        return jsonify(state_payload(conn))


@app.delete("/api/models/<int:model_id>")
def remove_model(model_id):
    with db.get_conn() as conn:
        if db.get_model(conn, model_id) is None:
            return bad_request("模型不存在", 404)
        db.delete_model(conn, model_id)
        return jsonify(state_payload(conn))


@app.post("/api/solve")
def solve():
    with db.get_conn() as conn:
        conf = db.get_config(conn)
        models = db.list_models(conn)
        if not models:
            return bad_request("请先上传至少一个 STL 模型")
        total = sum(m["copies"] for m in models)
        if total > cfg.MAX_TOTAL_INSTANCES:
            return bad_request(f"实例总数 {total} 超过上限 {cfg.MAX_TOTAL_INSTANCES}")

        instances, oversized = build_instances(conn, models, conf)
        if oversized:
            return bad_request(
                "单件无法放入留白内可用区域（已允许旋转 90°）：" + "；".join(oversized)
            )

        pw = conf["bed_width_mm"] - 2 * conf["margin_mm"]
        pd = conf["bed_depth_mm"] - 2 * conf["margin_mm"]
        batches = solver.solve(instances, pw, pd, conf["gap_mm"])
        if batches is None:  # 防御性分支：单件预检后理论上不会发生
            return bad_request("当前参数下不存在可行排布")

        # 坐标转换：求解器以可用区域左下角为原点，导出/展示以打印床左下角为原点
        margin = conf["margin_mm"]
        for b in batches:
            for p in b["placements"]:
                p["x_mm"] = round(p["x_mm"] + margin, 3)
                p["y_mm"] = round(p["y_mm"] + margin, 3)

        solution = {
            "valid": True,
            "solved_at": db.now_iso(),
            "coordinate_origin": "bed_bottom_left",
            "config_snapshot": conf,
            "printable": {"width_mm": round(pw, 3), "depth_mm": round(pd, 3)},
            "total_instances": total,
            "batch_count": len(batches),
            "batches": batches,
        }
        db.save_solution(conn, solution)
        return jsonify(state_payload(conn))


@app.get("/api/export")
def export_solution():
    with db.get_conn() as conn:
        sol = db.get_solution(conn)
        if sol is None:
            return bad_request("尚无排布结果，请先点击“重新求解”", 409)
        if not sol.get("valid"):
            return bad_request("排布已因床参数或模型变更而失效，请重新求解后再导出", 409)

        conf = sol["config_snapshot"]
        margin = conf["margin_mm"]
        payload = {
            "coordinate_origin": "bed_bottom_left",
            "generated_at": sol["solved_at"],
            "bed": {
                "width_mm": conf["bed_width_mm"],
                "depth_mm": conf["bed_depth_mm"],
                "margin_mm": margin,
                "gap_mm": conf["gap_mm"],
                "printable_area": {
                    "width_mm": sol["printable"]["width_mm"],
                    "depth_mm": sol["printable"]["depth_mm"],
                    "origin": {"x_mm": margin, "y_mm": margin},
                },
            },
            "total_instances": sol["total_instances"],
            "batch_count": sol["batch_count"],
            "batches": [
                {
                    "batch": b["batch"],
                    "placements": [
                        {
                            "model": p["name"],
                            "model_id": p["model_id"],
                            "copy_index": p["index"],
                            "rotation_deg": p["rotation"],
                            "x_mm": p["x_mm"],
                            "y_mm": p["y_mm"],
                            "width_mm": p["width_mm"],
                            "depth_mm": p["depth_mm"],
                        }
                        for p in b["placements"]
                    ],
                }
                for b in sol["batches"]
            ],
        }
        path = os.path.join(cfg.DATA_DIR, "last_layout.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return send_file(
            path,
            mimetype="application/json",
            as_attachment=True,
            download_name="layout.json",
        )


# 统一 JSON 错误（如 413）
@app.errorhandler(413)
def too_large(_e):
    return bad_request("上传文件超过 64MB 上限", 413)


@app.errorhandler(404)
def not_found(_e):
    return bad_request("接口不存在", 404)
