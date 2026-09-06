# 设计文档：Vue3 坐席工作台

日期：2026-09-06
状态：已批准
对应简历宣称：Vue3 坐席工作台（前后端分离）；坐席可看每步决策依据、工单草稿一键采纳/修改

## 背景与目标

当前前端是单个 Jinja 模板页（客户聊天），无坐席侧界面。本设计将前端整体迁移到 Vue3 SPA（客户聊天 + 坐席工作台 + 会话回放），Flask 退化为纯 API 后端并托管打包产物；工单实时提醒用 SSE。

## 已确认的决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| Vue 化范围 | 全部前端（聊天页一并重写） | "前后端分离"叙事完整，单一前端 |
| 新工单提醒 | SSE 推送（`GET /api/tickets/stream`） | 单向实时、实现适中、面试可讲 |
| 工单创建的跨进程感知 | Flask SSE 生成器轮询共享 SQLite（2s） | 双进程唯一共享源就是工单库，引入 IPC 不值当 |
| UI 框架 | Element Plus（全量引入，中文 locale） | 简单可靠，JD 主流 |
| 状态管理 | Pinia（工单角标 + SSE 连接） | JD 关键词，职责单一 |
| 登录/JWT、WebSocket、导出 | 不做 | YAGNI |

## 总体架构

```
frontend/  Vue3 + Vite + Element Plus + Vue Router + Pinia
  dev:  Vite dev server 5173，proxy /api → 127.0.0.1:5000
  prod: npm run build → frontend/dist，由 Flask 托管 + SPA fallback（单端口演示）
backend/   Flask 纯 API（现有接口零破坏）+ 3 处增强
```

## 页面清单（顶部导航切换）

1. **客户聊天 `/`**：左侧会话列表（新建/切换/删除），右侧消息气泡 + 输入框。对齐原 Jinja 页能力：多轮聊天（thread_id 维持）、历史加载、清空会话。不做"数据导出"。
2. **工单台 `/tickets`**：待处理/已处理 Tab + 表格（时间、问题、质检分、质检理由、状态）；详情抽屉内：工单信息 + 草稿回复文本框（预填草稿）→ 坐席可直接提交（采纳）或修改后提交 → `POST /api/tickets/<id>/resolve`。
3. **会话回放 `/sessions`**：左侧会话列表；右侧上半对话气泡流，下半 `el-timeline` 决策轨迹（分类结果 → 质检得分/理由 → 转人工/放行/挂起 → 最终回复）。

## 后端三处增强

### 1. 决策轨迹 decision_trace
- `AgentState` 新增 `decision_trace: List[Any]`，由 checkpointer 持久化；
- 各节点 append 记录（带 timestamp）：
  - `classify_query_node`：`{"step": "classify", "query_type": ...}`；挂起短路为 `{"step": "suspended"}`；
  - `quality_check_node`：`{"step": "quality_check", "score": ..., "reason": ..., "threshold": ...}`；
  - `human_handoff_node`：`{"step": "handoff", "ticket_id": ...}`；
  - `final_response_node`：`{"step": "final_response", "agent": current_agent}`；
- `GET /api/sessions/<id>` 返回体新增 `decision_trace`（读线程 state `values.decision_trace`）。

### 2. SSE 工单推送
- 新增 `GET /api/tickets/stream`，返回 `text/event-stream`；
- 生成器逻辑（`chat_web_service.ticket_stream_events(poll_interval=2.0)`，可注入间隔便于测试）：每轮查询 open 工单 id 列表；首轮回 `{"type":"init","open_count":N}`；与上轮相比有变化回 `{"type":"update","open_count":N,"new_ids":[...]}`；无变化不发；查询异常发 `{"type":"error",...}` 后继续（不断流）；
- 事件 diff 抽为纯函数 `ticket_change_event(last_ids, ids) -> Optional[dict]`，单测覆盖 init/update/无变化/新增；
- 前端 EventSource 断线自动重连，收到 `update` 时角标 +1 并对 `new_ids` 弹 ElNotification、刷新列表。

### 3. SPA 静态托管
- `web_app.py`：`Flask(static_folder=frontend/dist, static_url_path="/")`；`/` 返回 `dist/index.html`；catch-all `/<path:path>` 实现 history 路由 fallback（`api/` 前缀仍走 404 JSON；dist 未构建时返回构建提示文本）；
- 删除 `templates/index.html` 与 `render_template` 用法（Jinja 前端下线，git 历史可溯）。

## 前端结构

```
frontend/
├── package.json / vite.config.js / index.html
└── src/
    ├── main.js / App.vue
    ├── router/index.js          # /  /tickets  /sessions
    ├── api/index.js             # axios 封装：chat/sessions/tickets/resolve/stream
    ├── stores/tickets.js        # Pinia：openCount、SSE 连接生命周期
    └── views/
        ├── ChatView.vue
        ├── TicketsView.vue
        └── SessionsView.vue
```

## 错误处理

| 故障 | 行为 |
|---|---|
| SSE 查询工单库异常 | 推 `error` 事件后继续轮询，不断流 |
| EventSource 断线 | 浏览器自动重连（默认 3s） |
| resolve 提交失败（409/500） | ElMessage 展示后端错误信息，抽屉不关闭 |
| dist 未构建时访问 `/` | 返回构建提示文本（不报 500） |

## 测试与验收

1. 单元（TDD）：`ticket_change_event` 四态；decision_trace 在放行/转人工/挂起/护栏四条路径上的记录（进程内图测试，复用 FakeLLM 模式）。
2. 构建：`npm install && npm run build` 成功产出 dist。
3. 浏览器全流程验收（自动化 GUI 测试）：客户发退款进度问题 → 转人工 → 工单台角标与通知 → 坐席修改草稿处理 → 回放页核对对话与决策轨迹、人工回复入列。
4. 回归：`pytest tests/` 全量通过；四场景 API 验收脚本 `deploy_verify.py` 重跑通过。

## 风险

- Element Plus 全量引入体积大（~1MB gzip 前）：演示项目可接受，生产可换按需引入。
- Flask dev server + SSE 并发连接：`app.run` 默认 threaded，演示规模足够。
