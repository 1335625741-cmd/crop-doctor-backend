# ============================================================
# 征途问诊后端 - Docker 镜像
# 平台:linux/amd64(兼容 Render / 微信云托管 / HuggingFace Spaces)
# ============================================================
FROM python:3.11-slim

# 不缓冲 Python 输出(让 log 立刻写到 stderr)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

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

# ★ 写死端口 80(微信云托管要求)
#   - 不要用 ${PORT} 变量(gunicorn 26 会嗅探 HF Spaces env 强制 7860)
#   - 不要用 exec 之外的 shell 形式(变量替换不可控)
#   - exec 形式直接执行,无 shell 解析,确保 bind 0.0.0.0:80
EXPOSE 80

# 启动 gunicorn(生产 WSGI)
# - workers 2
# - timeout 120(诊断可能调 AI 比较久)
# - accesslog 写到 stderr
CMD ["gunicorn", \
     "--bind", "0.0.0.0:80", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
