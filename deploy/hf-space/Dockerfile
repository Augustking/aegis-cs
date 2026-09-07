# HF Space 构建文件：构建时从 GitHub 拉取最新代码，单容器运行
# 前端构建 + 后端运行时在同一镜像内完成
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 拉取最新代码（Space 重新构建时自动取新版）
RUN git clone --depth 1 https://github.com/Augustking/aegis-cs.git /app
WORKDIR /app

# 前端构建
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && cd frontend && npm ci --registry=https://registry.npmmirror.com --no-fund --no-audit && npm run build

RUN pip install --no-cache-dir -r requirements.txt

# HF Space 规范：监听 7860；数据目录预建（持久化需在 Space 设置中开启持久存储）
ENV FLASK_PORT=7860 FLASK_DEBUG=false PYTHONUNBUFFERED=1 \
    TICKET_DB_PATH=/data/tickets.db AUTH_DB_PATH=/data/auth.db CHECKPOINT_DB=/data/checkpoints.sqlite
RUN mkdir -p /data /app/data

EXPOSE 7860
CMD ["python", "web_app.py"]
