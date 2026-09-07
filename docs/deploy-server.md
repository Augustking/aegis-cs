# 服务器部署指南（Aegis-CS）

适用：任意有 Docker 的 Linux 服务器（1C2G 起步即可，含 Docker Compose v2）。
架构为单容器（前端构建 + 图内嵌 Flask 一体）+ 可选 PostgreSQL。

## 一、前置检查

```bash
docker --version          # ≥ 24
docker compose version    # ≥ 2.20
```

## 二、部署步骤

```bash
# 1. 拉代码
git clone https://github.com/Augustking/aegis-cs.git && cd aegis-cs

# 2. 配置（唯一必填项是模型 API key）
cp env_example.txt .env && vi .env
#   必改：OPENAI_API_KEY=你的key
#   建议：FLASK_DEBUG=false（已默认）
#   坐席口令：AGENT_DEFAULT_PASSWORD=换成强口令

# 3. 构建并启动（首次构建约 3-5 分钟）
docker compose up -d --build

# 4. 验证
curl http://127.0.0.1:5000/api/health
docker compose logs web --tail 20
```

## 三、域名 + HTTPS（对外提供 demo 必做）

推荐 Caddy（自动签发证书，两行配置）：

```bash
# Caddyfile
your-demo-domain.com {
    reverse_proxy 127.0.0.1:5000
}
```

Nginx 等价配置：

```nginx
server {
    listen 443 ssl;
    server_name your-demo-domain.com;
    # ssl_certificate / ssl_certificate_key ...
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;          # SSE 必需：工单实时推送
        proxy_read_timeout 300s;      # 单轮对话最长 180s
    }
}
```

DNS 解析 A 记录指向服务器 IP → 启动 Caddy/nginx → 完成。

## 四、日常运维

```bash
docker compose logs web -f          # 看实时日志（含 request_id 结构化日志）
docker compose restart              # 重启（对话/工单从数据卷恢复）
docker compose up -d --build        # 代码更新后重新部署
docker compose down                 # 停止（数据保留在卷）
```

## 五、安全清单（对外 demo 前过一遍）

- [ ] `.env` 中的 `AGENT_DEFAULT_PASSWORD` 已改为强口令（坐席登录用）
- [ ] 模型 API key 设置了额度上限（公开 demo 会消耗你的配额）
- [ ] 服务器防火墙只放行 80/443（5000 仅本机，由反代对外）
- [ ] `.env` 不进 git（已在 .gitignore / .dockerignore）

## 六、常见问题

| 现象 | 原因/处理 |
|---|---|
| 页面白屏 | 前端构建产物未生成：`docker compose build` 会自动构建，确认镜像为新 |
| 回复很慢或超时转人工 | 模型档位慢属正常，超时上限 `RUN_WAIT_LIMIT`（默认 180s）可调 |
| SSE 无实时推送 | 反代未关缓冲：确认 `proxy_buffering off` |
| 数据丢了 | 未挂载数据卷就改过路径：确认 compose 中三个 `*_DB_PATH` 指向 `/app/data` |
