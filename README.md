# 3D 打印排版 Web 应用（Print Nester）

本地运行的 3D 打印批次排版工具：设置矩形打印床宽高、四边留白与模型间距，
上传毫米单位的 ASCII / 二进制 STL 模型并指定份数（实例总数 ≤ 12），
以模型 **XY 投影的轴对齐外接矩形** 为占位，实例仅允许绕 Z 轴旋转
0° 或 90°。应用求出**所需批次数的最小值**，在浏览器画布中展示
每批每件的模型、份号、方向与左下角坐标，并可下载相同内容的 JSON。

## 功能与规则

- 打印床为矩形，宽、深、四边留白、模型间距均以毫米配置。
- 每个占位必须完全位于留白围成的可用区域内。
- 同批任意两件之间：**水平净距 ≥ 间距 或 垂直净距 ≥ 间距**
  （间距为 0 时即普通的不重叠，边可相切）。
- 精确搜索（差分点 + DFS 剪枝，总数 ≤ 12）保证批次数最小。
- 修改床参数、增删/替换模型或修改份数后，旧排布自动标记为**失效**，
  重新求解成功前无法导出 JSON（页面按钮禁用，接口返回 409）。
- 错误均给出明确原因且不保存排布：
  - 床尺寸/留白/间距非法（含留白后可用区域不为正）；
  - STL 为空、格式损坏、被截断、含非有限数值、无三角面、XY 投影为零；
  - 单件（即使旋转 90°）无法放入当前留白内可用区域；
  - 实例总数超过 12。
- 数据保存在 SQLite（床参数、模型尺寸与份数、最近一次排布），
  STL 文件内容不落盘，仅提取包围盒。

## 一键启动（Docker Compose）

需要本机已安装 Docker 与 Docker Compose 插件。

```bash
docker compose up -d --build
```

启动后用浏览器打开：

```
http://localhost:8000
```

停止：

```bash
docker compose down          # 保留数据（Docker 卷 nester-data）
docker compose down -v       # 同时删除数据卷
```

查看日志：

```bash
docker compose logs -f
```

## 仅用 Docker（不使用 Compose）

```bash
docker build -t print-nester .
docker run -d --name print-nester -p 8000:8000 \
  -v nester-data:/data print-nester
```

## 本地直接运行（不使用 Docker）

需要 Python 3.11+：

```bash
python -m pip install -r requirements.txt
export NESTER_DATA_DIR=./data        # 可选，默认 /data
python -m app.wsgi                   # 或：gunicorn -b 0.0.0.0:8000 app.wsgi:app
```

访问 http://localhost:8000 。

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `NESTER_DATA_DIR` | `/data` | 持久化目录，SQLite 数据库位于其中 |
| `NESTER_DB_PATH` | `$NESTER_DATA_DIR/nester.sqlite3` | SQLite 文件完整路径 |
| `NESTER_HOST` | `0.0.0.0` | 开发服务器监听地址 |
| `NESTER_PORT` | `8000` | 开发服务器监听端口（gunicorn 固定监听容器内 8000） |

如需更改宿主机映射端口，修改 `docker-compose.yml` 中的
`ports`，例如 `"18000:8000"` 后通过 http://localhost:18000 访问。

## 使用步骤

1. 在“打印床参数”中填写床宽、床深、四边留白、模型间距并保存
   （默认 200 × 200 mm，留白 5 mm，间距 2 mm）。
2. 在“模型”中选择 STL 文件、填写份数后上传；同名文件会替换旧模型；
   可在表格中随时修改份数或删除模型。
3. 点击“重新求解（最小批次数）”，查看各批画布与明细表。
4. 点击“下载 JSON”导出当前有效排布（文件名 `layout.json`）。

## 坐标约定与导出格式

- 坐标原点为**打印床左下角**，X 沿床宽向右，Y 沿床深向上。
- 留白内可用区域原点为 `(margin, margin)`。
- `x_mm`/`y_mm` 为每个占位左下角在床坐标系中的位置；
  `width_mm`/`depth_mm` 为旋转后的实际占位宽深；
  `rotation_deg` 为 0 或 90。

`layout.json` 示例结构：

```json
{
  "coordinate_origin": "bed_bottom_left",
  "generated_at": "2026-10-07T08:00:00+00:00",
  "bed": {
    "width_mm": 200.0, "depth_mm": 200.0,
    "margin_mm": 5.0, "gap_mm": 2.0,
    "printable_area": {
      "width_mm": 190.0, "depth_mm": 190.0,
      "origin": { "x_mm": 5.0, "y_mm": 5.0 }
    }
  },
  "total_instances": 3,
  "batch_count": 1,
  "batches": [
    {
      "batch": 1,
      "placements": [
        {
          "model": "bracket.stl", "model_id": 1, "copy_index": 1,
          "rotation_deg": 90,
          "x_mm": 5.0, "y_mm": 5.0,
          "width_mm": 30.0, "depth_mm": 60.0
        }
      ]
    }
  ]
}
```

## HTTP 接口（可供脚本调用）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/state` | 当前参数、模型、排布（含失效标记） |
| POST | `/api/config` | 保存床参数（JSON body） |
| POST | `/api/models` | 上传/替换 STL（multipart：`file`、`copies`） |
| PATCH | `/api/models/<id>` | 修改份数（JSON：`{"copies": n}`） |
| DELETE | `/api/models/<id>` | 删除模型 |
| POST | `/api/solve` | 重新求解并保存有效排布 |
| GET | `/api/export` | 下载 `layout.json`（失效/无结果时 409） |

## 目录结构

```
app/
  config.py     配置与约束常量
  db.py         SQLite 初始化、读写与失效逻辑
  stl.py        ASCII / 二进制 STL 解析与包围盒
  solver.py     最小批次数精确排版求解器
  app.py        Flask 路由与参数校验
  wsgi.py       gunicorn / 开发服务器入口
  templates/    单页界面
  static/       画布渲染与交互
Dockerfile
docker-compose.yml
requirements.txt
```
