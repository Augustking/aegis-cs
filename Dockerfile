# ---- 前端构建 ----
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# ---- 运行时 ----
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=frontend /app/frontend/dist ./frontend/dist
ENV FLASK_DEBUG=false PYTHONUNBUFFERED=1
EXPOSE 5000
CMD ["python", "web_app.py"]
