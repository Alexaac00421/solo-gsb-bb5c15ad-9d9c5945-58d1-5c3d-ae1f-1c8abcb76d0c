"""WSGI 入口：导入即初始化数据库；供 gunicorn 使用。"""
from .app import app, init

init()

if __name__ == "__main__":
    # 本地开发：python -m app.wsgi
    from . import config

    app.run(host=config.HOST, port=config.PORT)
