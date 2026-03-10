# 第一阶段：前端构建
FROM node:20-slim AS frontend-builder
WORKDIR /app/portal
COPY portal/package*.json ./
RUN npm install
COPY portal/ ./
RUN npm run build

# 第二阶段：运行环境
FROM python:3.11-slim
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 拷贝后端代码与依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# 从前端构建阶段拷贝 dist 到正确位置
COPY --from=frontend-builder /app/portal/dist ./portal/dist

# 设置环境变量默认值（生产环境应由 Zeabur 注入）
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# 启动服务
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
