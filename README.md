# 3D 打印排版（本地 Web 应用）

设置矩形打印床（宽高、四边留白、模型间距），上传毫米单位的 ASCII / 二进制 STL
并指定份数（总实例数 ≤ 12），应用以模型原始 XY 投影的轴对齐外接矩形为占位
（仅允许绕 Z 轴旋转 0° / 90°），用 CP-SAT 精确求解**所需批次数的最小值**，
在浏览器画布上展示每批实例的模型、份号、方向与左下角坐标，并可下载同内容的 JSON。

## 功能规则

- 每个占位必须完整落在四边留白围成的打印区内。
- 同一批内任意两件之间，水平或垂直方向至少有指定间距的分隔。
- 修改床参数或替换模型后，旧排布自动标记为**失效**，重新求解前禁止导出。
- 尺寸无效、STL 损坏、或单件无法放入打印区时，接口返回具体原因且不保存排布。

## 一键启动（Docker Compose）

```bash
docker compose up --build
```

启动后访问 **http://localhost:8000**（宿主机端口 `8000`，容器端口 `8000`）。
SQLite 数据库持久化在 `./data/app.db`（通过 volume 挂载到容器 `/app/data`）。

## 手动 Docker

```bash
docker build -t print-layout .
docker run --rm -p 8000:8000 -v "$PWD/data:/app/data" print-layout
```

## 本地开发（不用 Docker）

```bash
pip install -r requirements.txt
python app.py
```

同样访问 http://localhost:8000 。

## 配置（环境变量）

| 变量      | 默认值               | 说明                     |
|-----------|----------------------|--------------------------|
| `PORT`    | `8000`               | Web 服务监听端口         |
| `DB_PATH` | `<项目目录>/data/app.db`（容器内 `/app/data/app.db`） | SQLite 数据库文件路径 |

修改宿主机端口映射可编辑 `docker-compose.yml` 中的 `ports`，例如 `"9000:8000"`。

## 使用流程

1. **打印床设置**：填写床宽、床高、左右上下四边留白、模型间距（单位毫米），保存。
2. **上传模型**：选择 STL 文件（ASCII 或二进制，毫米单位）并指定份数（1–12）。
   上传新文件会替换当前模型。
3. **求解**：点击“求解最小批次数”，结果按批次展示——画布可视化（虚线为留白
   边界与间距光晕）加实例表格（模型、份号、方向、左下角 X/Y、占位宽高）。
4. **下载 JSON**：导出与页面展示完全一致的结果（`layout.json`）。
   排布失效时按钮禁用、接口返回 409。

## JSON 导出格式

```json
{
  "bed": {"width": 220, "height": 220,
          "margins": {"left": 10, "right": 10, "bottom": 10, "top": 10},
          "spacing": 5},
  "model": {"filename": "box.stl", "copies": 5, "width": 20, "height": 10},
  "batch_count": 1,
  "proven_optimal": true,
  "batches": [
    {"batch": 1, "instances": [
      {"model": "box.stl", "copy": 1, "rotation": 0,
       "x": 10.0, "y": 10.0, "width": 20.0, "height": 10.0}
    ]}
  ]
}
```

`x` / `y` 为占位左下角在整床坐标系（左下角原点）中的毫米坐标；
`rotation` 为绕 Z 轴旋转角度（0 或 90）。

## 项目结构

```
app.py            Flask 应用与 API 路由
solver.py         CP-SAT 排版求解（最小批次数 + 紧凑化）
stl_parser.py     ASCII / 二进制 STL 解析与 XY 投影外接矩形
db.py             SQLite 持久化（设置 / 模型 / 排布及失效标记）
static/           前端页面（画布可视化）
examples/         示例 STL 及生成脚本
tests/            端到端冒烟测试
```

## 测试

```bash
python3 tests/smoke_test.py
```

覆盖尺寸校验、STL 损坏 / 退化拒绝、份数上限、已知答案的最小批次数断言、
排布几何性质（留白内、间距分隔、份号齐全）、失效与导出限制等 24 项检查。

## 技术说明

- 后端：Python + Flask + SQLite（三张单行表：设置、模型、排布）。
- 求解：OR-Tools CP-SAT。坐标按 0.01 mm 缩放为整数；间距通过把占位向右、
  向上各膨胀一个间距后施加二维不重叠约束实现；先最小化批次数（证明最优），
  再在批次数不变下做靠左下紧凑化。
- 前端：原生 HTML/JS + Canvas，无构建步骤。
