# ============================================================
# 征途问诊后端 - Docker 镜像
# 平台:linux/amd64(兼容 Render / 本地 / HuggingFace Spaces)
# ============================================================
FROM python:3.11-slim

# 不缓冲 Python 输出(让 log 立刻写到 stderr)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 默认端口 7860(HuggingFace Spaces 强制)
# Render 会自动注入 PORT=10000 覆盖(本 env 仅作默认值)
# 本地 Docker 测试: docker run -p 7860:7860 ...
ENV PORT=7860

# 工作目录
WORKDIR /app

# 系统依赖(ca-certificates 用于 HTTPS 调用微信接口)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# 先装 Python 依赖(利用 Docker 缓存,改代码不重装依赖)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . /app/

# gunicorn 监听 PORT env(Render=10000, 本地=7860)
# shell 形式 CMD 让 ${PORT} 变量替换生效
EXPOSE 7860

# 启动 gunicorn(生产 WSGI)
# - bind 0.0.0.0:${PORT}(Render 自动注入 PORT=10000,本地默认 7860)
# - workers 2(免费层 2C 4G 跑 2 个 worker 够用)
# - timeout 120(诊断可能调 AI 比较久)
# - accesslog 写到 stderr(让 Render log 能看到)
CMD gunicorn \
    --bind 0.0.0.0:${PORT} \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    app:app
