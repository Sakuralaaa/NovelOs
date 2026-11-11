# NovelOS 一体化镜像：stage1 构建前端，stage2 运行后端并托管前端静态文件
# ---------- stage 1: 前端 ----------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: 后端 ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    NOVELOS_DATA_DIR=/data \
    NOVELOS_STATIC_DIR=/app/static
# 中文字体（封面书名排版）+ 时区数据
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-microhei tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist ./static
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
