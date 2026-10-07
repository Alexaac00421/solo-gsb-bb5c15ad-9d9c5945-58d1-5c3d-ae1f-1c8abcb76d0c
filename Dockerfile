FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NESTER_DATA_DIR=/data

WORKDIR /app

# 仅安装依赖，利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app/ ./app/

# 持久化数据目录（SQLite 与导出缓存）
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# 容器启动时自动初始化 SQLite（首次运行），随后以单进程 gunicorn 运行
CMD ["sh", "-c", "python -c 'from app.wsgi import init; init()' && exec gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 8 --timeout 120 app.wsgi:app"]
