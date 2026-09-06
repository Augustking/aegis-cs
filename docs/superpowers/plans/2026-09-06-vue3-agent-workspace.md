# Vue3 坐席工作台 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 前端整体 Vue3 化（客户聊天 + 工单台 + 会话回放），Flask 变纯 API + SPA 托管，工单 SSE 实时推送，决策轨迹可视化。

**Architecture:** 后端三处增强（decision_trace / SSE / 静态托管）先行并 TDD；前端为独立 `frontend/` Vite 工程，build 产物由 Flask 托管，dev 模式经 Vite proxy 访问 API。规格：`docs/superpowers/specs/2026-09-06-vue3-agent-workspace-design.md`。

**Tech Stack:** Vue 3.5 / Vite 6 / Element Plus 2.9 / Pinia 2 / vue-router 4 / axios；Flask 3 / pytest

## Global Constraints

- 现有 API 语义零破坏：`/api/chat`、`/api/sessions*`、`/api/tickets*` 行为不变（只增不改）。
- SSE 事件格式：`{"type": "init"|"update"|"error", "open_count": N, "new_ids": [...]}`（error 事件无 open_count）。
- 决策轨迹步骤常量：`classify` / `quality_check` / `handoff` / `suspended` / `final_response`，均带 `timestamp`。
- 前端 Element Plus 全量引入 + 中文 locale；Pinia 只管工单角标与 SSE 连接。
- npm 安装用国内镜像：`npm install --registry=https://registry.npmmirror.com`。
- `.gitignore` 需追加 `frontend/node_modules/`、`frontend/dist/`。
- Python 命令一律 `./.venv/Scripts/python.exe`；工作目录 `E:/mye盘项目/jianli project/customer-service-ai-agent`。

---

### Task 1: 决策轨迹 decision_trace（TDD）

**Files:**
- Modify: `multi_agent_customer_service.py`（AgentState 字段 + 4 个节点追加轨迹）
- Modify: `chat_web_service.py`（`fetch_session_detail` 返回体带 `decision_trace`）
- Test: `tests/test_decision_trace.py`

**Interfaces:**
- Produces: `AgentState.decision_trace: List[Any]`；线程 state `values.decision_trace`；`GET /api/sessions/<id>` 返回 `session.decision_trace`。步骤字段：
  - `{"step": "classify", "query_type": str, "timestamp"}`
  - `{"step": "quality_check", "score": float, "reason": str, "threshold": float, "timestamp"}`
  - `{"step": "handoff", "ticket_id": str, "timestamp"}`
  - `{"step": "suspended", "timestamp"}`
  - `{"step": "final_response", "agent": str, "timestamp"}`

- [ ] **Step 1: 写失败测试** `tests/test_decision_trace.py`

```python
# -*- coding: utf-8 -*-
"""决策轨迹：放行 / 转人工 / 挂起 / 护栏四条路径的轨迹记录。"""
import pytest

import multi_agent_customer_service as svc
import ticket_store
from tests.test_graph_quality import FakeLLM, _FakeResp  # 复用 FakeLLM


@pytest.fixture()
def graph_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "tickets.db"))
    monkeypatch.setattr(svc, "get_llm", lambda: FakeLLM())
    return tmp_path


def _invoke(session_id, query="帮我查退款进度", llm=None):
    if llm is not None:
        svc.get_llm = lambda: llm
    app = svc.make_graph()
    return app.invoke({"customer_query": query, "session_id": session_id})


def test_trace_pass_path(graph_env):
    state = _invoke("tr-pass")
    steps = [s["step"] for s in state["decision_trace"]]
    assert steps == ["classify", "quality_check", "final_response"]
    assert state["decision_trace"][0]["query_type"] == "billing"
    assert state["decision_trace"][1]["score"] == 9.0
    assert state["decision_trace"][1]["threshold"] == 6.0
    assert state["decision_trace"][2]["agent"] == "账单专家"


def test_trace_handoff_then_suspended(graph_env, monkeypatch):
    monkeypatch.setattr(
        svc, "get_llm", lambda: FakeLLM(judge_json='{"score": 2, "reason": "差"}')
    )
    state = _invoke("tr-hand")
    steps = [s["step"] for s in state["decision_trace"]]
    assert steps == ["classify", "quality_check", "handoff", "final_response"]
    assert state["decision_trace"][2]["ticket_id"]

    # 工单已存在，同线程再次进入 → 挂起短路
    state2 = _invoke("tr-hand")
    steps2 = [s["step"] for s in state2["decision_trace"]]
    assert steps2 == ["suspended", "final_response"]


def test_trace_out_of_scope(graph_env, monkeypatch):
    class OOS(FakeLLM):
        def invoke(self, messages):
            for m in messages:
                if getattr(m, "type", "") == "system" and "查询分类专家" in m.content:
                    return _FakeResp("out_of_scope")
            raise AssertionError("护栏后不应调 LLM")

    monkeypatch.setattr(svc, "get_llm", lambda: OOS())
    state = _invoke("tr-oos", query="写一首诗")
    steps = [s["step"] for s in state["decision_trace"]]
    assert steps == ["classify", "final_response"]
    assert state["decision_trace"][0]["query_type"] == "out_of_scope"
```

注意：`tests/test_graph_quality.py` 的 `FakeLLM` / `_FakeResp` 需可在导入时使用——若它们以类形式定义在模块顶层（当前如此），直接导入即可；若导入报错，将其上移为模块级（不放在函数内）。

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_decision_trace.py -v`
Expected: FAIL（`KeyError: 'decision_trace'`）

- [ ] **Step 3: 实现**

`multi_agent_customer_service.py`：

3a. `AgentState` 追加字段（`ticket_id: str` 之后）：

```python
    # 每步决策快照（分类/质检/转人工/挂起/最终回复），checkpointer 持久化，供工作台回放
    decision_trace: List[Any]
```

3b. `classify_query_node` 状态初始化块（`needs_human` 初始化后）追加：

```python
    if "decision_trace" not in state:
        state["decision_trace"] = []
```

3c. `classify_query_node` 挂起分支（`state["persisted_dialogue"] = pd` 之后、`return state` 之前）追加：

```python
            state["decision_trace"] = list(state.get("decision_trace") or []) + [
                {"step": "suspended", "timestamp": now}
            ]
```

3d. `classify_query_node` 正常分类路径（`state["query_type"] = query_type` 之后）追加：

```python
    state["decision_trace"] = list(state.get("decision_trace") or []) + [
        {"step": "classify", "query_type": query_type,
         "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    ]
```

3e. `quality_check_node` 重构为统一出口（替换现有实现；保持 fail-open 语义不变）：

```python
def quality_check_node(state: AgentState) -> AgentState:
    """LLM-as-judge 给业务回复打 0-10 分；任何故障 fail-open 放行。"""
    threshold = _quality_threshold()
    if not QUALITY_CHECK_ENABLED:
        score, reason = 10.0, "quality_check_disabled"
    else:
        score, reason = 10.0, "quality_check_error"
        try:
            llm = get_llm()
            if llm is None:
                raise ValueError("LLM 不可用")
            pd = list(state.get("persisted_dialogue") or [])
            context = "\n".join(
                f"{'用户' if m.get('is_user') else 'AI'}: {m.get('content', '')}"
                for m in pd[-6:]
            )
            resp = llm.invoke(
                build_judge_messages(
                    state.get("customer_query", ""), state.get("response", ""), context
                )
            )
            score, reason = parse_judge_output(getattr(resp, "content", ""))
        except Exception as e:
            print(f"⚠️ 质检失败，fail-open 放行: {e}")

    state["quality_score"] = float(score)
    state["quality_reason"] = str(reason)
    state["tools_used"].append("quality_check")
    state["decision_trace"] = list(state.get("decision_trace") or []) + [
        {"step": "quality_check", "score": float(score), "reason": str(reason),
         "threshold": threshold,
         "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    ]
    print(f"🔍 质检得分 {score}（阈值 {threshold}）：{reason}")
    return state
```

3f. `human_handoff_node`（`state["persisted_dialogue"] = pd` 之前）追加：

```python
    state["decision_trace"] = list(state.get("decision_trace") or []) + [
        {"step": "handoff", "ticket_id": ticket_id,
         "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    ]
```

3g. `final_response_node`（`state["response"] = f"【{current_agent}'s Response】\n{response}"` 之后）追加：

```python
    state["decision_trace"] = list(state.get("decision_trace") or []) + [
        {"step": "final_response", "agent": current_agent,
         "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    ]
```

3h. `chat_web_service.py` 的 `fetch_session_detail`：读取 state 后同时取轨迹——

```python
        state_data = None
        try:
            state_response = requests.get(
                f"{LANGGRAPH_API_URL}/threads/{session_id}/state",
                timeout=5
            )
            if state_response.status_code == 200:
                state_data = state_response.json()
                conversation_history = conversation_history_from_state_data(state_data)
        except Exception as e:
            print(f"⚠️ 获取线程状态时出错: {e}")
            import traceback
            traceback.print_exc()

        decision_trace = []
        if state_data and "values" in state_data:
            decision_trace = list((state_data.get("values") or {}).get("decision_trace") or [])

        session_data = {
            "session_id": session_id,
            "created_at": thread_data.get("created_at", time.time()),
            "conversation_history": conversation_history,
            "decision_trace": decision_trace,
        }
```

（原实现中 try 块只填 conversation_history；按上面整体替换该 try 段与 `session_data` 构造，行为兼容、只增字段。）

- [ ] **Step 4: 跑全部测试确认通过**

Run: `./.venv/Scripts/python.exe -m pytest tests/ 2>&1 | tail -1`
Expected: 全部 passed（原 17 个 + 新增 ≥3）

- [ ] **Step 5: 提交**

```bash
git add multi_agent_customer_service.py chat_web_service.py tests/test_decision_trace.py
git commit -m "feat: 决策轨迹 decision_trace（各节点快照，随会话详情输出）"
```

---

### Task 2: SSE 工单推送（TDD）

**Files:**
- Modify: `chat_web_service.py`（`ticket_change_event` + `ticket_stream_events`，顶部 `import ticket_store`）
- Modify: `web_app.py`（`GET /api/tickets/stream` 路由）
- Test: `tests/test_ticket_stream.py`

**Interfaces:**
- Produces:
  - `chat_web_service.ticket_change_event(last_ids: Optional[List[str]], ids: List[str]) -> Optional[dict]`
  - `chat_web_service.ticket_stream_events(poll_interval: float = 2.0) -> Iterator[str]`（SSE data 行）
  - `GET /api/tickets/stream`（`text/event-stream`）

- [ ] **Step 1: 写失败测试** `tests/test_ticket_stream.py`

```python
# -*- coding: utf-8 -*-
import json

import ticket_store
from chat_web_service import ticket_change_event, ticket_stream_events


def test_ticket_change_event_states():
    assert ticket_change_event(None, ["a"]) == {"type": "init", "open_count": 1}
    assert ticket_change_event(["a"], ["a"]) is None
    assert ticket_change_event(["a"], ["b", "a"]) == {
        "type": "update", "open_count": 2, "new_ids": ["b"],
    }
    # 工单被关闭也要推送（数量变化）
    assert ticket_change_event(["a", "b"], ["a"]) == {
        "type": "update", "open_count": 1, "new_ids": [],
    }


def test_ticket_stream_events_init_then_update(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "t.db"))
    gen = ticket_stream_events(poll_interval=0.05)
    first = json.loads(next(gen).removeprefix("data: ").strip())
    assert first["type"] == "init" and first["open_count"] == 0

    ticket_store.create_ticket("th", "q", "d", 1.0, "r")  # 制造变化
    second = json.loads(next(gen).removeprefix("data: ").strip())
    assert second["type"] == "update"
    assert second["open_count"] == 1 and len(second["new_ids"]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_ticket_stream.py -v`
Expected: FAIL（`ImportError: cannot import name 'ticket_change_event'`）

- [ ] **Step 3: 实现**

`chat_web_service.py` 顶部导入区加 `import ticket_store`，文件末尾追加：

```python
def ticket_change_event(last_ids, ids):
    """diff 两次 open 工单 id 列表 → SSE 事件；无变化返回 None。"""
    if last_ids is None:
        return {"type": "init", "open_count": len(ids)}
    if ids == last_ids:
        return None
    return {
        "type": "update",
        "open_count": len(ids),
        "new_ids": [i for i in ids if i not in last_ids],
    }


def ticket_stream_events(poll_interval: float = 2.0):
    """SSE 生成器：轮询共享工单库产出事件；查询异常发 error 事件后继续（不断流）。"""
    last_ids = None
    while True:
        try:
            ids = [t["id"] for t in ticket_store.list_tickets(status="open")]
            event = ticket_change_event(last_ids, ids)
            if event:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            last_ids = ids
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        time.sleep(poll_interval)
```

`web_app.py`：`from chat_web_service import (...)` 追加 `ticket_stream_events`，路由区追加：

```python
@app.route('/api/tickets/stream')
def ticket_stream_route():
    """SSE：工单队列变化推送（EventSource 断线自动重连）"""
    return Response(
        ticket_stream_events(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )
```

- [ ] **Step 4: 跑全部测试确认通过**

Run: `./.venv/Scripts/python.exe -m pytest tests/ 2>&1 | tail -1`
Expected: 全部 passed

- [ ] **Step 5: 提交**

```bash
git add chat_web_service.py web_app.py tests/test_ticket_stream.py
git commit -m "feat: 工单 SSE 实时推送（跨进程感知共享工单库）"
```

---

### Task 3: SPA 静态托管 + Jinja 下线（TDD）

**Files:**
- Modify: `web_app.py`（静态托管 + 404 fallback；移除 `render_template`）
- Delete: `templates/index.html`
- Test: `tests/test_spa.py`

**Interfaces:**
- Produces: `/` 返回 `frontend/dist/index.html`；未知非 API 路径 fallback 到 `index.html`（history 路由）；`/api/*` 未知路径 404 JSON；dist 缺失时 `/` 返回构建提示文本（200）。
- 实现要点：Flask `static_url_path="/"` 会注册 `/<path:filename>` 静态规则并优先于 catch-all，因此**用 404 errorhandler 做 fallback**（显式 API 路由与静态文件命中不受影响）。

- [ ] **Step 1: 写失败测试** `tests/test_spa.py`

```python
# -*- coding: utf-8 -*-
import pytest

import web_app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>SPA</html>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(web_app, "DIST_DIR", str(dist))
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()


def test_index_serves_spa(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"SPA" in resp.data


def test_history_route_falls_back_to_index(client):
    assert client.get("/tickets").status_code == 200
    assert b"SPA" in client.get("/tickets").data


def test_static_assets_served(client):
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert b"console.log" in resp.data


def test_unknown_api_returns_json_404(client):
    resp = client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not found"


def test_missing_dist_hint(monkeypatch, client_without_dist):
    resp = client_without_dist.get("/")
    assert resp.status_code == 200
    assert "npm run build" in resp.get_data(as_text=True)


@pytest.fixture()
def client_without_dist(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DIST_DIR", str(tmp_path / "nope"))
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_spa.py -v`
Expected: FAIL（`AttributeError: module 'web_app' has no attribute 'DIST_DIR'`）

- [ ] **Step 3: 实现**

`web_app.py`：

3a. import 行去掉 `render_template`：

```python
from flask import Flask, request, jsonify, session, Response
```

3b. app 创建处替换为（`app = Flask(__name__)` 原行）：

```python
DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")
app = Flask(__name__, static_folder=DIST_DIR, static_url_path="/")
```

3c. `index` 路由整体替换：

```python
@app.route('/')
def index():
    """SPA 入口；dist 未构建时给出提示"""
    if os.path.isfile(os.path.join(DIST_DIR, "index.html")):
        return app.send_static_file("index.html")
    return "前端尚未构建：请在 frontend/ 目录执行 npm install && npm run build", 200, {
        "Content-Type": "text/plain; charset=utf-8"
    }
```

3d. 文件末尾（`main()` 之前）追加 404 fallback：

```python
@app.errorhandler(404)
def spa_fallback(e):
    """history 路由 fallback：非 API 的未知路径回 SPA 入口；静态文件已由 static 规则优先命中"""
    if request.path.startswith("/api/"):
        return jsonify({'error': 'not found'}), 404
    if os.path.isfile(os.path.join(DIST_DIR, "index.html")):
        return app.send_static_file("index.html")
    return jsonify({'error': 'not found'}), 404
```

3e. `git rm templates/index.html`（templates 目录若空一并删除）。

- [ ] **Step 4: 跑全部测试确认通过**

Run: `./.venv/Scripts/python.exe -m pytest tests/ 2>&1 | tail -1`
Expected: 全部 passed

- [ ] **Step 5: 提交**

```bash
git add web_app.py tests/test_spa.py
git rm templates/index.html
git commit -m "feat: Flask 托管 Vue SPA（history fallback + 构建提示），下线 Jinja 前端"
```

---

### Task 4: 前端工程与三页面

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`
- Create: `frontend/src/main.js`, `frontend/src/App.vue`, `frontend/src/router/index.js`
- Create: `frontend/src/api/index.js`, `frontend/src/stores/tickets.js`
- Create: `frontend/src/views/ChatView.vue`, `frontend/src/views/TicketsView.vue`, `frontend/src/views/SessionsView.vue`
- Modify: `.gitignore`（追加 `frontend/node_modules/`、`frontend/dist/`）

**Interfaces:**
- Consumes: 后端 `/api/chat`、`/api/sessions`、`/api/sessions/<id>`（含 `decision_trace`）、`/api/sessions/<id>/clear`、`/api/tickets`、`/api/tickets/<id>/resolve`、`/api/tickets/stream`（SSE）
- Produces: `npm run build` 产出的 `frontend/dist`

- [ ] **Step 1: 工程骨架**

`frontend/package.json`：

```json
{
  "name": "customer-service-workspace",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@element-plus/icons-vue": "^2.3.1",
    "axios": "^1.7.9",
    "element-plus": "^2.9.3",
    "pinia": "^2.3.0",
    "vue": "^3.5.13",
    "vue-router": "^4.5.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.2.1",
    "vite": "^6.0.7"
  }
}
```

`frontend/vite.config.js`：

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:5000', changeOrigin: true } }
  }
})
```

`frontend/index.html`：

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>智能客服工作台</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

`frontend/src/main.js`：

```js
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
```

`frontend/src/router/index.js`：

```js
import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '../views/ChatView.vue'
import TicketsView from '../views/TicketsView.vue'
import SessionsView from '../views/SessionsView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: ChatView },
    { path: '/tickets', component: TicketsView },
    { path: '/sessions', component: SessionsView },
  ],
})
```

`frontend/src/api/index.js`：

```js
import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 180000 })

export const sendMessage = (message, sessionId) =>
  http.post('/chat', { message, session_id: sessionId }).then(r => r.data)
export const listSessions = () => http.get('/sessions').then(r => r.data.sessions)
export const getSession = (id) => http.get(`/sessions/${id}`).then(r => r.data.session)
export const deleteSession = (id) => http.delete(`/sessions/${id}`).then(r => r.data)
export const clearSession = (id) => http.post(`/sessions/${id}/clear`).then(r => r.data)
export const listTickets = (status) =>
  http.get('/tickets', { params: { status } }).then(r => r.data.tickets)
export const resolveTicket = (id, human_reply) =>
  http.post(`/tickets/${id}/resolve`, { human_reply }).then(r => r.data)
```

`frontend/src/stores/tickets.js`：

```js
import { defineStore } from 'pinia'
import { ElNotification } from 'element-plus'

export const useTicketStore = defineStore('tickets', {
  state: () => ({ openCount: 0, connected: false, _es: null }),
  actions: {
    startSSE(onUpdate) {
      if (this._es) return
      const es = new EventSource('/api/tickets/stream')
      this._es = es
      es.onopen = () => { this.connected = true }
      es.onerror = () => { this.connected = false } // 浏览器自动重连
      es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data)
          if (ev.type === 'init') this.openCount = ev.open_count
          if (ev.type === 'update') {
            this.openCount = ev.open_count
            if (ev.new_ids && ev.new_ids.length && onUpdate) {
              ElNotification({
                title: '新工单',
                message: `有 ${ev.new_ids.length} 个工单待处理`,
                type: 'warning',
              })
              onUpdate()
            }
          }
        } catch { /* 忽略解析失败 */ }
      }
    },
  },
})
```

`.gitignore` 追加两行：

```
frontend/node_modules/
frontend/dist/
```

- [ ] **Step 2: App 外壳与三页面**

`frontend/src/App.vue`：

```vue
<script setup>
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useTicketStore } from './stores/tickets'

const store = useTicketStore()
const route = useRoute()
onMounted(() => store.startSSE())
</script>

<template>
  <el-container class="layout">
    <el-header class="header">
      <span class="title">智能客服工作台</span>
      <el-menu mode="horizontal" :default-active="route.path" router class="menu" :ellipsis="false">
        <el-menu-item index="/">客户聊天</el-menu-item>
        <el-menu-item index="/tickets">
          <el-badge :value="store.openCount" :hidden="!store.openCount">工单台</el-badge>
        </el-menu-item>
        <el-menu-item index="/sessions">会话回放</el-menu-item>
      </el-menu>
      <el-tag :type="store.connected ? 'success' : 'info'" size="small">
        {{ store.connected ? '实时已连接' : '实时未连接' }}
      </el-tag>
    </el-header>
    <el-main class="main"><router-view /></el-main>
  </el-container>
</template>

<style>
html, body, #app, .layout { height: 100%; margin: 0; }
.header { display: flex; align-items: center; gap: 16px; border-bottom: 1px solid #eee; }
.title { font-weight: 600; white-space: nowrap; }
.menu { flex: 1; border-bottom: none !important; }
.main { padding: 0; }
</style>
```

`frontend/src/views/ChatView.vue`：

```vue
<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { clearSession, deleteSession, getSession, listSessions, sendMessage } from '../api'

const sessions = ref([])
const currentId = ref('')
const history = ref([])
const input = ref('')
const sending = ref(false)
const boxRef = ref(null)

async function refreshSessions() {
  sessions.value = await listSessions()
}

function scrollBottom() {
  nextTick(() => {
    if (boxRef.value) boxRef.value.scrollTop = boxRef.value.scrollHeight
  })
}

async function selectSession(id) {
  currentId.value = id
  const s = await getSession(id)
  history.value = s.conversation_history || []
  scrollBottom()
}

function newSession() {
  currentId.value = ''
  history.value = []
}

async function removeSession(id) {
  await deleteSession(id)
  if (currentId.value === id) newSession()
  refreshSessions()
}

async function clearCurrent() {
  if (!currentId.value) return
  const data = await clearSession(currentId.value)
  await selectSession(data.new_thread_id)
  refreshSessions()
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  history.value.push({ is_user: true, content: text })
  input.value = ''
  scrollBottom()
  try {
    const data = await sendMessage(text, currentId.value || 'default')
    currentId.value = data.thread_id
    history.value.push({ is_user: false, content: data.response })
    refreshSessions()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '发送失败')
  } finally {
    sending.value = false
    scrollBottom()
  }
}

onMounted(refreshSessions)
</script>

<template>
  <el-container class="page">
    <el-aside width="280px" class="aside">
      <el-button type="primary" plain style="width: 100%" @click="newSession">新建会话</el-button>
      <div v-for="s in sessions" :key="s.session_id" class="session-item"
           :class="{ active: s.session_id === currentId }" @click="selectSession(s.session_id)">
        <div class="q">{{ s.last_user_question || '（无消息）' }}</div>
        <div class="meta">
          <span>{{ new Date(s.created_at * 1000).toLocaleString() }}</span>
          <el-button link type="danger" size="small" @click.stop="removeSession(s.session_id)">删除</el-button>
        </div>
      </div>
    </el-aside>
    <el-main class="chat-main">
      <div class="toolbar">
        <el-button size="small" :disabled="!currentId" @click="clearCurrent">清空当前会话</el-button>
      </div>
      <div ref="boxRef" class="msg-box">
        <el-empty v-if="!history.length" description="开始你的咨询吧" />
        <div v-for="(m, i) in history" :key="i" class="msg" :class="m.is_user ? 'user' : 'ai'">
          <div class="bubble">{{ m.content }}</div>
        </div>
      </div>
      <div class="input-row">
        <el-input v-model="input" type="textarea" :rows="2" placeholder="输入消息，Enter 发送"
                  @keydown.enter.exact.prevent="send" />
        <el-button type="primary" :loading="sending" @click="send">发送</el-button>
      </div>
    </el-main>
  </el-container>
</template>

<style scoped>
.page { height: calc(100vh - 60px); }
.aside { border-right: 1px solid #eee; padding: 10px; overflow-y: auto; }
.session-item { padding: 8px; border-radius: 6px; cursor: pointer; margin-top: 8px; }
.session-item:hover { background: #f5f7fa; }
.session-item.active { background: #ecf5ff; }
.session-item .q { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-item .meta { font-size: 12px; color: #999; display: flex; justify-content: space-between; }
.chat-main { display: flex; flex-direction: column; }
.toolbar { padding: 6px 0; }
.msg-box { flex: 1; overflow-y: auto; padding: 10px; }
.msg { display: flex; margin: 8px 0; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 70%; padding: 10px 12px; border-radius: 8px; white-space: pre-wrap; font-size: 14px; line-height: 1.5; }
.msg.user .bubble { background: #409eff; color: #fff; }
.msg.ai .bubble { background: #f4f4f5; }
.input-row { display: flex; gap: 10px; padding-top: 10px; border-top: 1px solid #eee; }
</style>
```

`frontend/src/views/TicketsView.vue`：

```vue
<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listTickets, resolveTicket } from '../api'

const tab = ref('open')
const rows = ref([])
const drawer = ref(false)
const current = ref(null)
const reply = ref('')
const submitting = ref(false)

async function refresh() {
  rows.value = await listTickets(tab.value)
}

function openTicket(row) {
  current.value = row
  reply.value = row.status === 'open' ? (row.draft_reply || '') : (row.human_reply || '')
  drawer.value = true
}

async function submit() {
  if (!reply.value.trim()) {
    ElMessage.warning('回复内容不能为空')
    return
  }
  submitting.value = true
  try {
    const data = await resolveTicket(current.value.id, reply.value.trim())
    if (data.degraded) ElMessage.warning(data.message)
    else ElMessage.success(data.message)
    drawer.value = false
    await refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '处理失败')
  } finally {
    submitting.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <el-tabs v-model="tab" @tab-change="refresh">
      <el-tab-pane label="待处理" name="open" />
      <el-tab-pane label="已处理" name="resolved" />
    </el-tabs>
    <el-table :data="rows" style="cursor: pointer" @row-click="openTicket">
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column prop="user_query" label="客户问题" min-width="220" show-overflow-tooltip />
      <el-table-column prop="quality_score" label="质检分" width="90" />
      <el-table-column prop="quality_reason" label="质检理由" min-width="160" show-overflow-tooltip />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'open' ? 'warning' : 'success'">
            {{ row.status === 'open' ? '待处理' : '已处理' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="drawer" title="工单详情" size="45%">
      <el-descriptions v-if="current" :column="1" border>
        <el-descriptions-item label="客户问题">{{ current.user_query }}</el-descriptions-item>
        <el-descriptions-item label="质检得分">{{ current.quality_score }}</el-descriptions-item>
        <el-descriptions-item label="质检理由">{{ current.quality_reason }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ current.created_at }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="current && current.status === 'open'" style="margin-top: 16px">
        <div style="margin-bottom: 8px">草稿回复（AI 原始回答，可修改后提交）：</div>
        <el-input v-model="reply" type="textarea" :rows="6" />
        <el-button type="primary" style="margin-top: 12px" :loading="submitting" @click="submit">
          提交人工回复
        </el-button>
      </div>
      <div v-else-if="current" style="margin-top: 16px">
        <div style="margin-bottom: 8px">人工回复：</div>
        <el-input :model-value="reply" type="textarea" :rows="6" disabled />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page { padding: 0 16px; }
</style>
```

`frontend/src/views/SessionsView.vue`：

```vue
<script setup>
import { onMounted, ref } from 'vue'
import { getSession, listSessions } from '../api'

const sessions = ref([])
const currentId = ref('')
const history = ref([])
const trace = ref([])

const STEP_META = {
  classify: { label: '意图分类', type: 'primary' },
  quality_check: { label: '回复质检', type: 'warning' },
  handoff: { label: '转人工', type: 'danger' },
  suspended: { label: '挂起等待人工', type: 'info' },
  final_response: { label: '生成回复', type: 'success' },
}

function stepText(s) {
  if (s.step === 'classify') return `分类为 ${s.query_type}`
  if (s.step === 'quality_check') return `质检 ${s.score} 分（阈值 ${s.threshold}）：${s.reason}`
  if (s.step === 'handoff') return `已创建工单 ${(s.ticket_id || '').slice(0, 8)}…`
  if (s.step === 'suspended') return '会话挂起中'
  if (s.step === 'final_response') return `由【${s.agent}】输出`
  return JSON.stringify(s)
}

async function refresh() {
  sessions.value = await listSessions()
}

async function select(id) {
  currentId.value = id
  const s = await getSession(id)
  history.value = s.conversation_history || []
  trace.value = s.decision_trace || []
}

onMounted(refresh)
</script>

<template>
  <el-container class="page">
    <el-aside width="280px" class="aside">
      <div v-for="s in sessions" :key="s.session_id" class="session-item"
           :class="{ active: s.session_id === currentId }" @click="select(s.session_id)">
        <div class="q">{{ s.last_user_question || '（无消息）' }}</div>
        <div class="meta">{{ s.message_count }} 条消息</div>
      </div>
    </el-aside>
    <el-main class="detail">
      <el-empty v-if="!currentId" description="选择左侧会话查看回放" />
      <template v-else>
        <div class="msg-box">
          <div v-for="(m, i) in history" :key="i" class="msg" :class="m.is_user ? 'user' : 'ai'">
            <div class="bubble">{{ m.content }}</div>
          </div>
        </div>
        <div class="trace">
          <h4>决策轨迹</h4>
          <el-timeline>
            <el-timeline-item v-for="(s, i) in trace" :key="i"
                              :timestamp="s.timestamp" :type="STEP_META[s.step]?.type || 'info'">
              <b>{{ STEP_META[s.step]?.label || s.step }}</b>：{{ stepText(s) }}
            </el-timeline-item>
          </el-timeline>
        </div>
      </template>
    </el-main>
  </el-container>
</template>

<style scoped>
.page { height: calc(100vh - 60px); }
.aside { border-right: 1px solid #eee; padding: 10px; overflow-y: auto; }
.session-item { padding: 8px; border-radius: 6px; cursor: pointer; margin-top: 8px; }
.session-item:hover { background: #f5f7fa; }
.session-item.active { background: #ecf5ff; }
.session-item .q { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-item .meta { font-size: 12px; color: #999; }
.detail { display: flex; flex-direction: column; overflow-y: auto; }
.msg-box { flex: 1; }
.msg { display: flex; margin: 8px 0; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 70%; padding: 10px 12px; border-radius: 8px; white-space: pre-wrap; font-size: 14px; line-height: 1.5; }
.msg.user .bubble { background: #409eff; color: #fff; }
.msg.ai .bubble { background: #f4f4f5; }
.trace { border-top: 1px solid #eee; padding-top: 12px; }
</style>
```

- [ ] **Step 3: 安装依赖并构建**

```bash
cd "E:/mye盘项目/jianli project/customer-service-ai-agent/frontend"
npm install --registry=https://registry.npmmirror.com
npm run build
```

Expected: `dist/` 生成，构建无报错。

- [ ] **Step 4: 提交**

```bash
git add frontend/ .gitignore
git commit -m "feat: Vue3 前端（客户聊天/工单台/会话回放 + SSE 工单提醒）"
```

---

### Task 5: 部署与浏览器全流程验收

**Files:**
- 无新增（运行验证）

- [ ] **Step 1: 重启 Flask（langgraph dev 无需重启，SSE/SPA 均在 Flask 层）**

停掉旧 Flask 后台任务后重启：

```bash
cd "E:/mye盘项目/jianli project/customer-service-ai-agent"
./.venv/Scripts/python.exe web_app.py > web_app.log 2>&1 &
```

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/ && curl -s -m 3 -N http://127.0.0.1:5000/api/tickets/stream | head -1`
Expected: `200` + `data: {"type": "init", "open_count": 0}`

- [ ] **Step 2: 回归测试**

Run: `./.venv/Scripts/python.exe -m pytest tests/ 2>&1 | tail -1 && ./.venv/Scripts/python.exe deploy_verify.py 2>&1 | tail -1`
Expected: 全部 passed + `✅ 全部 4 个场景验收通过`

- [ ] **Step 3: 浏览器全流程 GUI 验收（browser-use）**

用浏览器自动化走真实流程并截图核对：
1. 打开 `http://localhost:5000/` —— 工作台外壳渲染、导航三项可见、右上角"实时已连接"；
2. 客户聊天页发送"帮我查一下退款进度" → AI/转接话术气泡出现；
3. 切到工单台 → 待处理列表出现该工单（若由 SSE 通知弹出则更佳），点开抽屉核对质检分与草稿；
4. 修改草稿提交 → 已处理 Tab 出现；
5. 切到会话回放 → 选中会话，核对气泡与决策轨迹时间线（分类/质检/转人工/生成回复），人工回复出现在对话里。

Expected: 每步截图与断言一致；控制台无阻断性报错。

- [ ] **Step 4: 提交（如有微调）**

```bash
git status --short && git add -A && git commit -m "fix: 浏览器验收微调"
```

---

## Self-Review 记录

- 规格覆盖：三页面（Task 4）、decision_trace（Task 1）、SSE（Task 2）、SPA 托管与 Jinja 下线（Task 3）、错误处理矩阵（Task 2 error 事件 / Task 3 fallback / Task 4 提交失败提示）、验收（Task 5）——无遗漏。
- 占位符：无 TBD/TODO；前端文件全部给出完整代码。
- 类型一致性：`ticket_change_event(None, ids) → init` 与 store 首条消息消费一致；resolve 返回 `{message, degraded}` 与 TicketsView 消费一致；`getSession()` 返回 `session.decision_trace` 与 SessionsView 一致；事件字段 `open_count/new_ids` 与 store 一致。
- 已知实现时风险：Flask 静态规则 `/<path:filename>` 与显式路由的优先级（用 404 handler 方案规避）；SSE 生成器在 Flask dev server 多线程下每连接独立，无共享状态。
