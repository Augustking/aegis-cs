# 设计文档：质检节点 + 人工接管

日期：2026-09-06
状态：已批准
对应简历宣称：智能体回复的"人工确认与升级"机制

## 背景与目标

当前系统的回复由业务智能体直接生成后原样输出，没有质量把关，也没有任何人工介入通道。本设计在 LangGraph 图上新增**质检节点**与**人工接管节点**，形成"AI 回复 → 质检打分 → 低分转人工 → 工单挂起 → 人工处理 → 恢复 AI"的完整闭环。

非目标（本设计不做）：坐席登录与权限、WebSocket 实时推送、前端界面（属第二件事 Vue 工作台）、业务智能体与分类逻辑的任何改动。

## 已确认的决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| 质检所在层 | 图内节点（方案 A） | Studio 可见、与多智能体编排叙事一致 |
| 质检方式 | LLM-as-judge 0-10 打分 | 评估维度可讲、与后续评测集复用 |
| 接管形态 | 工单队列 + 线程挂起 | 与工作台衔接，闭环完整 |
| 质检失败策略 | fail-open（按满分放行） | 质检系统自身故障不应导致全部会话转人工 |

## 新图结构

```
classify_query ─┬─ suspended ─────────────────────────→ final_response
                ├─ product_info → product_agent ──┐
                ├─ technical_support → tech_agent ┤
                ├─ billing → billing_agent ────────┤→ quality_check
                ├─ complaint → complaint_agent ────┤    ├─ score ≥ 阈值 → final_response
                ├─ general_inquiry → general_agent ┘    └─ score < 阈值 → human_handoff → final_response
                └─ out_of_scope（护栏固定话术，不质检）─→ final_response
```

- `quality_check`：LLM-as-judge。输入用户问题、AI 回答、最近对话上下文；按相关性 / 是否解答 / 是否幻觉三个维度综合打 0-10 分并给理由；提示词要求只输出 JSON `{"score": <int>, "reason": "<str>"}`。解析顺序：直接 json.loads → 正则抽取首个整数 → 全部失败按 fail-open 处理（score=10，reason=parse_failed）。
- `human_handoff`：将 `state["response"]`（业务智能体原始回答）作为草稿写入工单库并置线程挂起；给用户回固定转接话术；质检理由不透出给用户。
- 挂起判定在 `classify_query_node` 入口处：该 thread 存在 open 工单 → 记录用户消息后直接返回固定话术，`query_type="suspended"`，不调用分类 LLM、不进业务智能体。
- 阈值来源优先级：run 请求 `configurable.quality_threshold` > 环境变量 `QUALITY_THRESHOLD` > 默认 6.0。`QUALITY_CHECK_ENABLED=false` 时质检节点直接放行（用于演示与降级）。

## 数据模型：工单库（SQLite）

新模块 `ticket_store.py`，图进程（langgraph dev）与 Flask 进程共用同一数据文件 `tickets.db`（WAL 模式，短事务）。

```sql
CREATE TABLE tickets (
    id            TEXT PRIMARY KEY,   -- uuid4
    thread_id     TEXT NOT NULL,
    user_query    TEXT NOT NULL,
    draft_reply   TEXT NOT NULL,      -- 业务智能体原始回答，供坐席采纳/修改
    quality_score REAL NOT NULL,
    quality_reason TEXT NOT NULL,
    status        TEXT NOT NULL,      -- open / resolved
    created_at    TEXT NOT NULL,
    resolved_at   TEXT,
    human_reply   TEXT
);
CREATE INDEX idx_tickets_thread_status ON tickets(thread_id, status);
```

接口：`create_ticket(...)`、`has_open_ticket(thread_id)`、`list_tickets(status=None)`、`get_ticket(id)`、`resolve_ticket(id, human_reply)`。

## 新增 HTTP API（Flask 层）

- `GET /api/tickets?status=open` — 工单队列列表
- `GET /api/tickets/<id>` — 工单详情（含草稿回复与质检理由）
- `POST /api/tickets/<id>/resolve` — body `{"human_reply": "..."}`；工单置 resolved，人工回复经 LangGraph `POST /threads/{thread_id}/state` 写回线程 `persisted_dialogue`，对话恢复 AI 接管且上下文完整。若状态写回接口行为不符预期，降级为仅工单内可见（不阻塞主链路），实现时验证。

路由放 `web_app.py`，业务逻辑放 `chat_web_service.py`，与现有分层一致。

## 状态字段变更（AgentState）

新增：`quality_score: float`、`quality_reason: str`、`needs_human: bool`、`ticket_id: str`。既有字段与持久化行为不变。

## 错误处理汇总

| 故障 | 行为 |
|---|---|
| 质检 LLM 超时/异常 | fail-open，score=10 放行，日志记录 |
| judge 输出解析失败 | 正则兜底 → 仍失败则 fail-open |
| SQLite 写入失败 | 记录日志，回复照常送达用户（转人工话术照发），`needs_human` 仍置位 |
| 人工回复状态写回失败 | 工单仍置 resolved，降级为工单内可见 |

## 测试计划

1. 单元：`ticket_store` 全 CRUD + 并发读写；judge 输出解析（合法 JSON / 带杂讯 / 无数字）。
2. 端到端（扩展 `deploy_verify.py` 为剧本式）：
   - 正常问题 → 直达回复，无工单产生；
   - 经 `configurable.quality_threshold=10` 强制转人工 → 工单落库、回复为转接话术；
   - 挂起中再发消息 → 收到等待话术，不产生新工单、不调业务 LLM；
   - 调 resolve API 提交人工回复 → 工单 resolved，下一条消息恢复 AI 且能引用人工回复上下文。
3. 观测：Studio 图视图出现 `quality_check` / `human_handoff` 节点及两条条件边。

## 风险

- judge 与业务调用串行导致单轮延迟增加一次 LLM 往返：接受（模型已换为秒回档）。
- 双进程共写 SQLite：WAL + 短事务足够；如出现锁竞争再演进。
