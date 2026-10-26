# ==========================================================
# 掌控校园 - 后端镜像（华为云 ECS / 任意装了 Docker 的机器）
# 构建：docker build -t campus-master .
# 运行：docker run -d --env-file .env -p 8100:8100 \
#         -v /data/campus-uploads:/app/uploads campus-master
# 注意：.env 不打进镜像（见 .dockerignore），一律 --env-file 外挂
# ==========================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先只拷依赖清单：代码改动重建镜像时这层缓存不失效，装包不用重来
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ app/
COPY web/ web/
COPY sql/ sql/
RUN mkdir -p uploads

EXPOSE 8100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
