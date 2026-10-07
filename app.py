"""3D 打印排版 Web 应用（本地运行）。

流程：设置打印床 → 上传 STL 并指定份数 → 求解最小批次数 → 画布预览 → 导出 JSON。
修改床参数或替换模型后，旧排布自动失效，须重新求解才能导出。
"""

import json
import math
import os

from flask import Flask, jsonify, request, send_from_directory, Response

import db
from solver import solve_layout, PackingError, MAX_COPIES
from stl_parser import parse_stl, STLError

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024  # 上传上限

SETTINGS_FIELDS = ("bed_w", "bed_h", "margin_left", "margin_right",
                   "margin_bottom", "margin_top", "spacing")


# ---------- 校验 ----------

def _parse_settings(data):
    """校验并返回设置 dict；失败返回 (None, 错误消息)。"""
    if not isinstance(data, dict):
        return None, "请求体须为 JSON 对象"
    values = {}
    for field in SETTINGS_FIELDS:
        raw = data.get(field)
        try:
            values[field] = float(raw)
        except (TypeError, ValueError):
            return None, f"字段 {field} 缺失或不是数字"
        if not math.isfinite(values[field]):
            return None, f"字段 {field} 不是有限数值"
    if values["bed_w"] <= 0 or values["bed_h"] <= 0:
        return None, "打印床宽高必须为正数"
    for f in ("margin_left", "margin_right", "margin_bottom", "margin_top"):
        if values[f] < 0:
            return None, "留白不能为负数"
    if values["spacing"] < 0:
        return None, "模型间距不能为负数"
    if values["margin_left"] + values["margin_right"] >= values["bed_w"]:
        return None, "左右留白之和须小于床宽，否则打印区宽度非正"
    if values["margin_bottom"] + values["margin_top"] >= values["bed_h"]:
        return None, "上下留白之和须小于床高，否则打印区高度非正"
    return values, None


def _state():
    layout = db.get_layout()
    return {
        "settings": db.get_settings(),
        "model": db.get_model(),
        "layout": None if layout is None else {
            "status": layout["status"],
            "result": layout["payload"],
        },
        "max_copies": MAX_COPIES,
    }


def _err(message, code=400):
    return jsonify({"error": message}), code


# ---------- 路由 ----------

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def api_state():
    return jsonify(_state())


@app.post("/api/settings")
def api_settings():
    values, error = _parse_settings(request.get_json(silent=True))
    if error:
        return _err(f"尺寸无效：{error}")
    current = db.get_settings()
    if current != values:  # 参数真正变化才使旧排布失效
        db.save_settings(values)
        db.invalidate_layout()
    return jsonify(_state())


@app.post("/api/model")
def api_model():
    file = request.files.get("file")
    if file is None or not file.filename:
        return _err("请选择要上传的 STL 文件")
    try:
        copies = int(request.form.get("copies", ""))
    except ValueError:
        return _err("份数须为整数")
    if not 1 <= copies <= MAX_COPIES:
        return _err(f"份数须为 1–{MAX_COPIES}（总实例数不超过 {MAX_COPIES}）")
    data = file.read()
    try:
        tri_count, minx, miny, maxx, maxy = parse_stl(data)
    except STLError as e:
        return _err(f"STL 损坏：{e}")
    db.save_model({
        "filename": os.path.basename(file.filename),
        "copies": copies,
        "width": maxx - minx,
        "height": maxy - miny,
        "triangles": tri_count,
    })
    db.invalidate_layout()  # 替换模型后旧排布失效
    return jsonify(_state())


@app.post("/api/solve")
def api_solve():
    settings = db.get_settings()
    if settings is None:
        return _err("请先设置打印床参数")
    model = db.get_model()
    if model is None:
        return _err("请先上传 STL 模型")

    print_w = settings["bed_w"] - settings["margin_left"] - settings["margin_right"]
    print_h = settings["bed_h"] - settings["margin_bottom"] - settings["margin_top"]
    try:
        result = solve_layout(print_w, print_h, model["width"], model["height"],
                              settings["spacing"], model["copies"])
    except PackingError as e:
        return _err(str(e))  # 求解失败不保存任何排布

    # 坐标从打印区局部系换算到整床坐标系（左下角为原点）
    ox, oy = settings["margin_left"], settings["margin_bottom"]
    batches = []
    for idx, batch in enumerate(result["batches"], 1):
        instances = [{
            "model": model["filename"],
            "copy": inst["copy"],
            "rotation": inst["rotation"],
            "x": round(inst["x"] + ox, 2),
            "y": round(inst["y"] + oy, 2),
            "width": inst["width"],
            "height": inst["height"],
        } for inst in batch]
        batches.append({"batch": idx, "instances": instances})

    payload = {
        "bed": {
            "width": settings["bed_w"],
            "height": settings["bed_h"],
            "margins": {
                "left": settings["margin_left"],
                "right": settings["margin_right"],
                "bottom": settings["margin_bottom"],
                "top": settings["margin_top"],
            },
            "spacing": settings["spacing"],
        },
        "model": {
            "filename": model["filename"],
            "copies": model["copies"],
            "width": model["width"],
            "height": model["height"],
        },
        "batch_count": result["batch_count"],
        "proven_optimal": result["proven_optimal"],
        "batches": batches,
    }
    db.save_layout(payload)
    return jsonify(_state())


@app.get("/api/export")
def api_export():
    layout = db.get_layout()
    if layout is None:
        return _err("尚无排布，请先求解", 409)
    if layout["status"] != "valid":
        return _err("排布已失效（床参数或模型已变更），请重新求解后再导出", 409)
    body = json.dumps(layout["payload"], ensure_ascii=False, indent=2)
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=layout.json"},
    )


db.init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
