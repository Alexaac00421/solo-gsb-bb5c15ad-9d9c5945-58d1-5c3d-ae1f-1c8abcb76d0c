FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DB_PATH=/app/data/app.db

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data

EXPOSE 8000

# 初始化数据库并启动服务（建表为幂等操作，应用启动时自动执行）
CMD ["python", "app.py"]
