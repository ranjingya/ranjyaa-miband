# 使用 Python 3.13 slim 镜像作为基础
FROM python:3.13-slim

# 安装 uv
RUN pip install --no-cache-dir -i https://mirrors.ustc.edu.cn/pypi/simple/ uv

# 设置工作目录
WORKDIR /app

# 复制配置文件
COPY pyproject.toml ./
COPY gun.py ./
COPY cloud_bridge.py ./
COPY agent.py ./
COPY ./html/frontend.html ./html/

# 创建数据目录
RUN mkdir -p data

# 使用 uv 安装依赖
RUN uv sync -i https://mirrors.ustc.edu.cn/pypi/simple/

# 暴露端口
EXPOSE 5001

# 使用 gunicorn 启动服务
CMD ["./.venv/bin/gunicorn", "-c", "gun.py", "cloud_bridge:app"]
