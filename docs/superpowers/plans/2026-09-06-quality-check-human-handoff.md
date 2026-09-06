# 质检节点 + 人工接管 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 LangGraph 图上新增质检节点（LLM-as-judge 0-10 打分）与人工接管节点（工单落库 + 线程挂起 + 人工回复写回），形成"低分转人工"闭环。

**Architecture:** 质检与接管是图内节点；工单存 SQLite（图进程与 Flask 进程共用 `ticket_store.py`，WAL 模式）；挂起判定在入口分类节点；恢复走 Flask 新增工单 API + LangGraph 线程状态写回。规格见 `docs/superpowers/specs/2026-09-06-quality-check-human-handoff-design.md`。

**Tech Stack:** Python 3.14 / LangGraph ≥1.0 / Flask 3 / sqlite3（标准库）/ pytest

## Global Constraints

- 质检失败策略必须 fail-open：score=10、reason 说明原因，任何 LLM/解析故障都放行。
- 阈值优先级：run `configurable.quality_threshold` > env `QUALITY_THRESHOLD` > 默认 `6.0`。
- `QUALITY_CHECK_ENABLED=false` 时质检直接放行。
- 质检理由（quality_reason）不得透出给终端用户；用户只见固定转接话术。
- 不修改 5 个业务 Agent（product/tech/billing/complaint/general）与分类提示词。
- 工单库默认路径 `<项目根>/tickets.db`，环境变量 `TICKET_DB_PATH` 可覆盖（测试用 tmp 目录）。
- API key 在 `.env`，已被 .gitignore 覆盖，严禁提交。
- 运行命令一律用虚拟环境：`./.venv/Scripts/python.exe`（Windows + Git Bash）。

---

### Task 1: 工单存储 ticket_store.py（TDD）

**Files:**
- Create: `ticket_store.py`
- Create: `requirements-dev.txt`
- Test: `tests/test_ticket_store.py`

**Interfaces:**
- Produces（后续任务依赖，签名精确到此）:
  - `create_ticket(thread_id: str, user_query: str, draft_reply: str, quality_score: float, quality_reason: str) -> str`（返回工单 id）
  - `has_open_ticket(thread_id: str) -> bool`
  - `get_ticket(ticket_id: str) -> Optional[Dict[str, Any]]`
  - `list_tickets(status: Optional[str] = None) -> List[Dict[str, Any]]`（按 created_at 倒序）
  - `resolve_ticket(ticket_id: str, human_reply: str) -> bool`（仅 open 可 resolve；重复 resolve 返回 False）

- [ ] **Step 1: 写失败测试** `tests/test_ticket_store.py`

```python
# -*- coding: utf-8 -*-
import os

import pytest

import ticket_store


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "tickets.db"))


def _mk_ticket(thread_id="t-1", score=2.0):
    return ticket_store.create_ticket(
        thread_id=thread_id,
        user_query="帮我查退款进度",
        draft_reply="抱歉，处理您的账单问题时遇到系统错误",
        quality_score=score,
        quality_reason="答非所问",
    )


def test_create_and_get():
    tid = _mk_ticket()
    ticket = ticket_store.get_ticket(tid)
    assert ticket["thread_id"] == "t-1"
    assert ticket["status"] == "open"
    assert ticket["human_reply"] is None
    assert ticket["draft_reply"].startswith("抱歉")


def test_has_open_ticket():
    tid = _mk_ticket()
    assert ticket_store.has_open_ticket("t-1") is True
    assert ticket_store.has_open_ticket("t-other") is False
    ticket_store.resolve_ticket(tid, "人工回复：已处理")
    assert ticket_store.has_open_ticket("t-1") is False


def test_resolve_and_idempotency():
    tid = _mk_ticket()
    assert ticket_store.resolve_ticket(tid, "已处理") is True
    ticket = ticket_store.get_ticket(tid)
    assert ticket["status"] == "resolved"
    assert ticket["human_reply"] == "已处理"
    assert ticket["resolved_at"] is not None
    # 第二次 resolve 应失败（幂等保护）
    assert ticket_store.resolve_ticket(tid, "再处理") is False


def test_list_tickets_filter_and_order():
    t1 = _mk_ticket("t-a")
    t2 = _mk_ticket("t-b")
    ticket_store.resolve_ticket(t1, "ok")
    open_list = ticket_store.list_tickets(status="open")
    assert [t["id"] for t in open_list] == [t2]
    assert [t["id"] for t in ticket_store.list_tickets()] == [t2, t1]  # 倒序
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd "E:/mye盘项目/jianli project/customer-service-ai-agent" && ./.venv/Scripts/python.exe -m pip install -q pytest && ./.venv/Scripts/python.exe -m pytest tests/test_ticket_store.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'ticket_store'`）

- [ ] **Step 3: 最小实现** `ticket_store.py`

```python
"""
人工接管工单队列（SQLite）
图进程（langgraph dev）与 Flask 进程共用同一数据文件；WAL + busy_timeout 保证双进程安全。
数据文件路径默认 <项目根>/tickets.db，环境变量 TICKET_DB_PATH 可覆盖（测试指向临时目录）。
"""

import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id             TEXT PRIMARY KEY,
    thread_id      TEXT NOT NULL,
    user_query     TEXT NOT NULL,
    draft_reply    TEXT NOT NULL,
    quality_score  REAL NOT NULL,
    quality_reason TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open',
    created_at     TEXT NOT NULL,
    resolved_at    TEXT,
    human_reply    TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_thread_status ON tickets(thread_id, status);
"""


def _db_path() -> str:
    return os.getenv("TICKET_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "tickets.db"
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_ticket(
    thread_id: str,
    user_query: str,
    draft_reply: str,
    quality_score: float,
    quality_reason: str,
) -> str:
    ticket_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO tickets (id, thread_id, user_query, draft_reply,"
            " quality_score, quality_reason, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'open', ?)",
            (ticket_id, thread_id, user_query, draft_reply,
             float(quality_score), quality_reason, _now()),
        )
    return ticket_id


def has_open_ticket(thread_id: str) -> bool:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        row = conn.execute(
            "SELECT 1 FROM tickets WHERE thread_id=? AND status='open' LIMIT 1",
            (thread_id,),
        ).fetchone()
    return row is not None


def get_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        row = conn.execute(
            "SELECT * FROM tickets WHERE id=?", (ticket_id,)
        ).fetchone()
    return dict(row) if row else None


def list_tickets(status: Optional[str] = None) -> List[Dict[str, Any]]:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        if status:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status=? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tickets ORDER BY created_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def resolve_ticket(ticket_id: str, human_reply: str) -> bool:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        cur = conn.execute(
            "UPDATE tickets SET status='resolved', resolved_at=?, human_reply=?"
            " WHERE id=? AND status='open'",
            (_now(), human_reply, ticket_id),
        )
    return cur.rowcount > 0
```

同时创建 `requirements-dev.txt`：

```
pytest>=8.0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_ticket_store.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add ticket_store.py requirements-dev.txt tests/test_ticket_store.py
git commit -m "feat: 人工接管工单队列 ticket_store（SQLite，双进程安全）"
```

---

### Task 2: 质检提示词与输出解析 tools/quality_tools.py（TDD）

**Files:**
- Create: `tools/quality_tools.py`
- Modify: `tools/__init__.py`（追加导出）
- Test: `tests/test_quality_tools.py`

**Interfaces:**
- Consumes: `langchain_core.messages.SystemMessage/HumanMessage`
- Produces:
  - `build_judge_messages(query: str, response: str, context: str = "") -> list`（[SystemMessage, HumanMessage]，SystemMessage 含评分口径）
  - `parse_judge_output(raw: object) -> Tuple[float, str]`（解析失败一律返回 `(10.0, "parse_failed")`；分数夹在 [0,10]）

- [ ] **Step 1: 写失败测试** `tests/test_quality_tools.py`

```python
# -*- coding: utf-8 -*-
from langchain_core.messages import SystemMessage

from tools.quality_tools import build_judge_messages, parse_judge_output


def test_parse_clean_json():
    score, reason = parse_judge_output('{"score": 3, "reason": "答非所问"}')
    assert score == 3.0
    assert reason == "答非所问"


def test_parse_noisy_json():
    raw = '好的，结果如下：{"score": 2, "reason": "未解答用户问题"} 请参考'
    score, reason = parse_judge_output(raw)
    assert score == 2.0
    assert reason == "未解答用户问题"


def test_parse_garbage_fails_open():
    assert parse_judge_output("无法评价") == (10.0, "parse_failed")
    assert parse_judge_output(None) == (10.0, "parse_failed")
    assert parse_judge_output("") == (10.0, "parse_failed")


def test_parse_score_clamped():
    assert parse_judge_output('{"score": 15, "reason": "x"}')[0] == 10.0
    assert parse_judge_output('{"score": -3, "reason": "x"}')[0] == 0.0


def test_build_judge_messages():
    msgs = build_judge_messages("查退款", "请稍候", context="用户: 你好")
    assert isinstance(msgs[0], SystemMessage)
    assert "质检员" in msgs[0].content
    assert "对话历史上下文" in msgs[1].content
    assert "查退款" in msgs[1].content
    # 无上下文时不出现空段落
    assert "对话历史上下文" not in build_judge_messages("查退款", "回复").content
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_quality_tools.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'tools.quality_tools'`）

- [ ] **Step 3: 实现** `tools/quality_tools.py`

```python
"""
回复质检工具：judge 提示词构建 + LLM 输出解析（纯函数，可单测）。
解析策略：直接 json.loads → 正则抽取带杂讯 JSON → 任意 0-10 整数兜底 → fail-open。
"""

import json
import re
from typing import Tuple

from langchain_core.messages import HumanMessage, SystemMessage

_JUDGE_SYSTEM_PROMPT = """你是客服回复质检员。请对"AI客服回复"严格打分（0-10 分，整数）。

评分维度（综合）：
1. 相关性：是否针对用户的最新问题（0-4 分）
2. 解答度：是否实际解答诉求，还是空泛敷衍（0-3 分）
3. 可信度：是否编造信息、与上下文矛盾、包含明显错误（0-3 分）

判定口径：
- 回答了问题但需要用户补充信息 → 7 分以上
- 空泛套话、答非所问、明显未理解问题 → 3 分以下
- 编造具体承诺（金额/时间/政策）→ 0-2 分

只输出 JSON：{"score": <0-10整数>, "reason": "<20字以内理由>"}，不要输出任何其他内容。"""


def build_judge_messages(query: str, response: str, context: str = "") -> list:
    user_content = f"用户最新问题：{query}\n\nAI客服回复：{response}"
    if context:
        user_content = f"对话历史上下文：\n{context}\n\n{user_content}"
    return [
        SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]


def _clamp(v: float) -> float:
    return max(0.0, min(10.0, v))


def _extract_reason(text: str) -> str:
    m = re.search(r'"reason"\s*[:：]\s*"([^"]{0,100})"', text)
    return m.group(1) if m else ""


def parse_judge_output(raw: object) -> Tuple[float, str]:
    """解析 judge 输出为 (score, reason)；任何失败按 fail-open 返回 (10.0, 'parse_failed')。"""
    if raw is None:
        return 10.0, "parse_failed"
    text = str(raw).strip()
    if not text:
        return 10.0, "parse_failed"
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "score" in data:
            return _clamp(float(data["score"])), str(data.get("reason", ""))[:100]
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    m = re.search(r'"score"\s*[:：]\s*(\d{1,2})', text)
    if m:
        return _clamp(float(m.group(1))), _extract_reason(text) or "parsed_from_noise"
    m = re.search(r"\b(\d{1,2})\b", text)
    if m:
        v = float(m.group(1))
        if 0 <= v <= 10:
            return v, "parsed_fallback"
    return 10.0, "parse_failed"
```

`tools/__init__.py` 末尾追加（保留现有内容）：

```python
from .quality_tools import build_judge_messages, parse_judge_output
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_quality_tools.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add tools/quality_tools.py tools/__init__.py tests/test_quality_tools.py
git commit -m "feat: 质检打分工具（judge 提示词 + 容错解析，fail-open）"
```

---

### Task 3: 图节点接入（AgentState / quality_check / human_handoff / 挂起检查 / 重接线）

**Files:**
- Modify: `config.py`（追加 2 个配置项）
- Modify: `multi_agent_customer_service.py`（AgentState、3 处节点/路由、make_graph）
- Test: `tests/test_graph_quality.py`（进程内构图 + FakeLLM，不依赖 langgraph dev 服务）

**Interfaces:**
- Consumes: Task 1 `ticket_store.*`、Task 2 `build_judge_messages/parse_judge_output`、既有 `get_llm()`（可被 monkeypatch）
- Produces: 图节点 `quality_check`、`human_handoff`；`query_type="suspended"` 路由；`AgentState.quality_score/quality_reason/needs_human/ticket_id`

- [ ] **Step 1: 写失败测试** `tests/test_graph_quality.py`

```python
# -*- coding: utf-8 -*-
"""进程内图行为测试：FakeLLM 按提示词特征返回，覆盖放行/转人工/挂起三条路径。"""
import pytest

import multi_agent_customer_service as svc
import ticket_store


class _FakeResp:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """按 system 提示词特征路由：分类 / 质检 / 业务回答。"""

    def __init__(self, judge_json='{"score": 9, "reason": "正常"}'):
        self.judge_json = judge_json

    def invoke(self, messages):
        system = ""
        for m in messages:
            if getattr(m, "type", "") == "system":
                system = m.content
                break
        if "查询分类专家" in system:
            return _FakeResp("billing")
        if "质检员" in system:
            return _FakeResp(self.judge_json)
        return _FakeResp("您好，已为您登记退款申请，3-5 个工作日到账。")


@pytest.fixture()
def graph_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "tickets.db"))
    monkeypatch.setattr(svc, "get_llm", lambda: FakeLLM())
    return tmp_path


def _invoke(session_id, query="帮我查退款进度", **graph_kwargs):
    app = svc.make_graph()
    return app.invoke(
        {"customer_query": query, "session_id": session_id, **graph_kwargs}
    )


def test_high_score_passes(graph_env):
    state = _invoke("t-pass")
    assert state["query_type"] == "billing"
    assert state["quality_score"] == 9.0
    assert state["needs_human"] is False
    assert "【账单专家" in state["response"]
    assert ticket_store.list_tickets() == []


def test_low_score_goes_handoff(graph_env):
    monkey_judge = '{"score": 2, "reason": "答非所问"}'
    monkeypatch = graph_env  # fixture 返回 tmp_path，供下面 setenv 一致
    import multi_agent_customer_service as s
    s_get_llm = lambda: FakeLLM(judge_json=monkey_judge)
    # 重新 monkeypatch judge 分数
    import contextlib
    app = svc.make_graph()
    # 直接换模块级 get_llm 后再构图（agent_node 每次运行时重新取 LLM）
    svc.get_llm = s_get_llm
    state = app.invoke({"customer_query": "帮我查退款进度", "session_id": "t-low"})
    assert state["needs_human"] is True
    assert state["quality_score"] == 2.0
    assert state["current_agent"] == "人工客服"
    assert "人工工单" in state["response"]
    tickets = ticket_store.list_tickets(status="open")
    assert len(tickets) == 1
    assert tickets[0]["draft_reply"].startswith("您好，已为您登记")
    assert tickets[0]["thread_id"] == "t-low"


def test_suspended_thread_short_circuits(graph_env):
    ticket_store.create_ticket(
        thread_id="t-susp",
        user_query="之前的问题",
        draft_reply="草稿",
        quality_score=1.0,
        quality_reason="低分",
    )
    state = _invoke("t-susp")
    assert state["query_type"] == "suspended"
    assert "转接人工" in state["response"]
    # 不应产生新工单
    assert len(ticket_store.list_tickets()) == 1


def test_out_of_scope_skips_quality_check(graph_env, monkeypatch):
    monkeypatch.setattr(
        svc, "get_llm", lambda: FakeLLM()
    )
    from tools.quality_tools import parse_judge_output  # noqa: F401

    class _OOSLLM(FakeLLM):
        def invoke(self, messages):
            system = ""
            for m in messages:
                if getattr(m, "type", "") == "system":
                    system = m.content
                    break
            if "查询分类专家" in system:
                return _FakeResp("out_of_scope")
            raise AssertionError("out_of_scope 不应再调用任何 LLM")

    monkeypatch.setattr(svc, "get_llm", lambda: _OOSLLM())
    state = _invoke("t-oos", query="给我写一首诗")
    assert state["query_type"] == "out_of_scope"
    assert state.get("quality_score") is None  # 未经过质检节点
```

注意：`test_low_score_goes_handoff` 里对模块属性的二次赋值写法不干净——实现时统一改成 `monkeypatch.setattr(svc, "get_llm", lambda: FakeLLM(judge_json=...))`，本步骤落盘的测试代码按此为准（用 monkeypatch，不要裸赋值）。

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_graph_quality.py -v`
Expected: FAIL（`quality_score` KeyError / 断言失败）

- [ ] **Step 3: 实现**

`config.py` 追加：

```python
# 回复质检与人工接管
QUALITY_CHECK_ENABLED = os.getenv("QUALITY_CHECK_ENABLED", "true").lower() in ("1", "true", "yes")
QUALITY_THRESHOLD = float(os.getenv("QUALITY_THRESHOLD", "6.0"))
```

`multi_agent_customer_service.py`：

3a. 顶部导入与常量（`from tools import classify_query` 行改为）：

```python
from tools import classify_query, build_judge_messages, parse_judge_output
import ticket_store
```

（`OUT_OF_SCOPE_REPLY` 常量后追加）

```python
# 低分回复转人工时给用户的固定话术（质检理由不透出给用户）
HANDOFF_REPLY = (
    "您好，您的问题已升级为人工工单，客服专员将尽快为您跟进处理，请稍候。"
    "您也可以直接留言补充信息，处理结果会同步到本会话。"
)
# 挂起中的会话收到新消息时的固定话术
SUSPENDED_REPLY = (
    "您的问题已转接人工客服，工单正在处理中，请稍候；"
    "如需补充信息请直接留言，客服专员会一并查看。"
)
```

3b. `AgentState` 追加字段：

```python
    # —— 质检与人工接管（quality_check / human_handoff 节点写入）——
    quality_score: float
    quality_reason: str
    needs_human: bool
    ticket_id: str
```

3c. `classify_query_node` 中、`if not customer_query:` 检查之后、`# 使用分类工具` 之前插入：

```python
    # 人工接管挂起检查：该会话存在未处理工单时不走 AI（单一事实来源 = 工单库）
    try:
        if ticket_store.has_open_ticket(str(session_id)):
            state["query_type"] = "suspended"
            state["response"] = SUSPENDED_REPLY
            state["current_agent"] = "智能客服"
            state["tools_used"].append("suspended_for_human")
            pd = list(state.get("persisted_dialogue") or [])
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pd.append({"content": str(customer_query), "is_user": True, "timestamp": now})
            pd.append({"content": SUSPENDED_REPLY, "is_user": False, "timestamp": now})
            state["persisted_dialogue"] = pd
            return state
    except Exception as e:
        print(f"⚠️ 挂起检查失败（忽略并继续 AI 流程）: {e}")
```

3d. `final_response_node` 之前新增两个节点与阈值/路由辅助函数：

```python
def _quality_threshold() -> float:
    """阈值优先级：run configurable.quality_threshold > env QUALITY_THRESHOLD > 6.0。"""
    threshold = QUALITY_THRESHOLD
    try:
        cfg = get_config()
        configurable = (cfg.get("configurable") or {}) if isinstance(cfg, dict) else {}
        v = configurable.get("quality_threshold")
        if v is not None:
            threshold = float(v)
    except RuntimeError:
        pass
    return threshold


def quality_check_node(state: AgentState) -> AgentState:
    """LLM-as-judge 给业务回复打 0-10 分；任何故障 fail-open 放行。"""
    if not QUALITY_CHECK_ENABLED:
        state["quality_score"] = 10.0
        state["quality_reason"] = "quality_check_disabled"
        return state

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
            build_judge_messages(state.get("customer_query", ""), state.get("response", ""), context)
        )
        score, reason = parse_judge_output(getattr(resp, "content", ""))
    except Exception as e:
        print(f"⚠️ 质检失败，fail-open 放行: {e}")

    state["quality_score"] = float(score)
    state["quality_reason"] = str(reason)
    state["tools_used"].append("quality_check")
    print(f"🔍 质检得分 {score}（阈值 {_quality_threshold()}）：{reason}")
    return state


def route_after_quality_check(state: AgentState) -> str:
    return "handoff" if state.get("quality_score", 10.0) < _quality_threshold() else "pass"


def human_handoff_node(state: AgentState) -> AgentState:
    """低分回复转人工：原始回答作为草稿落工单，线程进入挂起，用户收固定话术。"""
    ticket_id = ""
    try:
        ticket_id = ticket_store.create_ticket(
            thread_id=str(state.get("session_id", "")),
            user_query=state.get("customer_query", ""),
            draft_reply=state.get("response", ""),
            quality_score=state.get("quality_score", 0.0),
            quality_reason=state.get("quality_reason", ""),
        )
    except Exception as e:
        print(f"❌ 工单落库失败（转接话术照常回复）: {e}")

    # 被驳回的草稿不下发给用户：从对话记录撤回，只保留在工单里供坐席参考
    pd = list(state.get("persisted_dialogue") or [])
    if pd and not pd[-1].get("is_user", True):
        pd.pop()

    state["ticket_id"] = ticket_id
    state["needs_human"] = True
    state["current_agent"] = "人工客服"
    state["response"] = HANDOFF_REPLY
    state["tools_used"].append("human_handoff")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pd.append({"content": HANDOFF_REPLY, "is_user": False, "timestamp": now})
    state["persisted_dialogue"] = pd
    print(f"🎫 已创建人工工单 {ticket_id}（质检 {state.get('quality_score')} 分）")
    return state
```

3e. `make_graph()` 改造（节点注册区追加 2 行；条件路由 map 追加 suspended；5 条 agent→final_response 边改为 →quality_check；新增质检条件边与 handoff 直连边）：

```python
    workflow.add_node("quality_check", quality_check_node)
    workflow.add_node("human_handoff", human_handoff_node)
```

```python
    workflow.add_conditional_edges(
        "classify_query",
        lambda x: x.get("query_type", ""),
        {
            "product_info": "product_agent",
            "technical_support": "tech_agent",
            "billing": "billing_agent",
            "complaint": "complaint_agent",
            "general_inquiry": "general_agent",
            "out_of_scope": "final_response",
            "suspended": "final_response",
        }
    )
```

```python
    # 所有业务智能体先过质检，再决定放行或转人工
    workflow.add_edge("product_agent", "quality_check")
    workflow.add_edge("tech_agent", "quality_check")
    workflow.add_edge("billing_agent", "quality_check")
    workflow.add_edge("complaint_agent", "quality_check")
    workflow.add_edge("general_agent", "quality_check")
    workflow.add_conditional_edges(
        "quality_check",
        route_after_quality_check,
        {"pass": "final_response", "handoff": "human_handoff"},
    )
    workflow.add_edge("human_handoff", "final_response")
```

- [ ] **Step 4: 跑全部测试确认通过**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -v && ./.venv/Scripts/python.exe multi_agent_customer_service.py`
Expected: 全部 passed；自检打印"✅ LangGraph工作流图构建完成"

- [ ] **Step 5: 提交**

```bash
git add config.py multi_agent_customer_service.py tests/test_graph_quality.py
git commit -m "feat: 图接入质检节点与人工接管节点（含挂起短路、configurable 阈值）"
```

---

### Task 4: 工单 API（Flask 层）

**Files:**
- Modify: `chat_web_service.py`（追加 `inject_human_reply`）
- Modify: `web_app.py`（追加 3 条路由）
- Test: `tests/test_ticket_api.py`（Flask test client + monkeypatch）

**Interfaces:**
- Consumes: Task 1 `ticket_store`；LangGraph REST（`GET/POST /threads/{tid}/state`）
- Produces:
  - `chat_web_service.inject_human_reply(thread_id: str, human_reply: str) -> Tuple[bool, Optional[str]]`
  - `GET /api/tickets?status=open|resolved` → `{"tickets": [...]}`
  - `GET /api/tickets/<id>` → `{"ticket": {...}}`（404 若不存在）
  - `POST /api/tickets/<id>/resolve` body `{"human_reply": "..."}` → `{"message", "degraded"}`；无 human_reply→400；不存在→404；非 open→409

- [ ] **Step 1: 写失败测试** `tests/test_ticket_api.py`

```python
# -*- coding: utf-8 -*-
import pytest

import ticket_store
import web_app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "tickets.db"))
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()


def test_list_and_get_ticket(client):
    tid = ticket_store.create_ticket("th-1", "问题", "草稿", 2.0, "低分")
    resp = client.get("/api/tickets?status=open")
    assert resp.status_code == 200
    assert resp.get_json()["tickets"][0]["id"] == tid
    detail = client.get(f"/api/tickets/{tid}")
    assert detail.status_code == 200
    assert detail.get_json()["ticket"]["draft_reply"] == "草稿"
    assert client.get("/api/tickets/no-such").status_code == 404


def test_resolve_calls_inject(client, monkeypatch):
    tid = ticket_store.create_ticket("th-2", "问题", "草稿", 2.0, "低分")
    calls = {}

    def fake_inject(thread_id, human_reply):
        calls["args"] = (thread_id, human_reply)
        return True, None

    monkeypatch.setattr(web_app, "inject_human_reply", fake_inject)
    resp = client.post(f"/api/tickets/{tid}/resolve", json={"human_reply": "已人工处理，退款 3 天内到账"})
    assert resp.status_code == 200
    assert resp.get_json()["degraded"] is False
    assert calls["args"] == ("th-2", "已人工处理，退款 3 天内到账")
    assert ticket_store.get_ticket(tid)["status"] == "resolved"


def test_resolve_validation_and_degradation(client, monkeypatch):
    tid = ticket_store.create_ticket("th-3", "问题", "草稿", 2.0, "低分")
    assert client.post(f"/api/tickets/{tid}/resolve", json={}).status_code == 400
    assert client.post("/api/tickets/nope/resolve", json={"human_reply": "x"}).status_code == 404

    monkeypatch.setattr(web_app, "inject_human_reply", lambda t, h: (False, "超时"))
    resp = client.post(f"/api/tickets/{tid}/resolve", json={"human_reply": "回复"})
    assert resp.status_code == 200
    assert resp.get_json()["degraded"] is True  # 写回失败降级：工单照常关闭
    assert ticket_store.get_ticket(tid)["status"] == "resolved"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_ticket_api.py -v`
Expected: FAIL（`ImportError: cannot import name 'inject_human_reply'`）

- [ ] **Step 3: 实现**

`chat_web_service.py` 追加（文件末尾）：

```python
def inject_human_reply(thread_id: str, human_reply: str) -> Tuple[bool, Optional[str]]:
    """把人工坐席回复写回线程 persisted_dialogue（作为坐席轮次），恢复 AI 上下文。"""
    try:
        state_resp = requests.get(
            f"{LANGGRAPH_API_URL}/threads/{thread_id}/state", timeout=10
        )
        if state_resp.status_code != 200:
            return False, f"获取线程状态失败: {state_resp.status_code}"
        values = (state_resp.json() or {}).get("values") or {}
        pd = list(values.get("persisted_dialogue") or [])
        pd.append({
            "content": str(human_reply),
            "is_user": False,
            "timestamp": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        update_resp = requests.post(
            f"{LANGGRAPH_API_URL}/threads/{thread_id}/state",
            json={"values": {"persisted_dialogue": pd}, "as_node": "final_response"},
            timeout=10,
        )
        if not (200 <= update_resp.status_code < 300):
            return False, f"写回线程状态失败: {update_resp.status_code}"
        return True, None
    except Exception as e:
        return False, f"写回人工回复异常: {e}"
```

`web_app.py`：顶部 import 区追加

```python
import ticket_store
```

`from chat_web_service import (...)` 追加 `inject_human_reply`。路由区追加：

```python
@app.route('/api/tickets', methods=['GET'])
def list_tickets_route():
    """人工工单队列"""
    status = request.args.get('status')
    if status not in ('open', 'resolved', None, ''):
        return jsonify({'error': 'status 仅支持 open/resolved'}), 400
    try:
        tickets = ticket_store.list_tickets(status or None)
        return jsonify({'tickets': tickets})
    except Exception as e:
        return jsonify({'error': f'获取工单失败: {e}'}), 500


@app.route('/api/tickets/<ticket_id>', methods=['GET'])
def ticket_detail_route(ticket_id):
    """工单详情（含草稿回复与质检理由）"""
    try:
        ticket = ticket_store.get_ticket(ticket_id)
        if not ticket:
            return jsonify({'error': '工单不存在'}), 404
        return jsonify({'ticket': ticket})
    except Exception as e:
        return jsonify({'error': f'获取工单失败: {e}'}), 500


@app.route('/api/tickets/<ticket_id>/resolve', methods=['POST'])
def resolve_ticket_route(ticket_id):
    """人工处理工单：写回会话并关闭工单；写回失败时降级为仅工单内可见"""
    try:
        data = request.get_json() or {}
        human_reply = (data.get('human_reply') or '').strip()
        if not human_reply:
            return jsonify({'error': 'human_reply 不能为空'}), 400

        ticket = ticket_store.get_ticket(ticket_id)
        if not ticket:
            return jsonify({'error': '工单不存在'}), 404
        if ticket['status'] != 'open':
            return jsonify({'error': f"工单状态为 {ticket['status']}，无法处理"}), 409

        ok, err = inject_human_reply(ticket['thread_id'], human_reply)
        ticket_store.resolve_ticket(ticket_id, human_reply)
        if not ok:
            return jsonify({
                'message': '工单已处理，但人工回复写回会话失败（仅工单内可见）',
                'degraded': True,
                'detail': err,
            })
        return jsonify({'message': '人工回复已写入会话，AI 恢复接管', 'degraded': False})
    except Exception as e:
        return jsonify({'error': f'处理工单失败: {e}'}), 500
```

- [ ] **Step 4: 跑全部测试确认通过**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全部 passed（含前序任务）

- [ ] **Step 5: 提交**

```bash
git add chat_web_service.py web_app.py tests/test_ticket_api.py
git commit -m "feat: 工单队列/详情/处理 API（人工回复写回会话，失败降级）"
```

---

### Task 5: 端到端验收（扩展 deploy_verify.py + 真服务验证 + Studio 观测）

**Files:**
- Modify: `deploy_verify.py`（重写为剧本式验收：4 个场景）
- Test: 运行中的 langgraph dev + Flask 真服务

**Interfaces:**
- Consumes: 全部前序任务；运行中的 `langgraph dev`（2024）与 `web_app.py`（5000）

- [ ] **Step 1: 重写** `deploy_verify.py`

```python
# -*- coding: utf-8 -*-
"""
端到端验收剧本（需先启动 langgraph dev 与 web_app.py）：
  场景1  正常两轮对话（Flask /api/chat）：业务路由 + 多轮上下文，不产生工单
  场景2  强制转人工（run config quality_threshold=10）：回复转接话术 + 工单落库
  场景3  挂起中的会话再来消息：固定等待话术，不产生新工单
  场景4  resolve API 人工处理：工单关闭，下一条消息恢复 AI 且上下文完整
"""
import json
import time

import requests

FLASK = "http://127.0.0.1:5000"
LG = "http://127.0.0.1:2024"


def chat(message, session_id):
    r = requests.post(f"{FLASK}/api/chat",
                      json={"message": message, "session_id": session_id}, timeout=180)
    r.raise_for_status()
    return r.json()


def lg_run(thread_id, message, configurable=None):
    """直连 LangGraph API 跑一轮（支持 configurable，供强制转人工用）"""
    assistants = requests.post(f"{LG}/assistants/search",
                               json={"graph_id": "customer_service", "limit": 1}, timeout=10).json()
    resp = requests.post(f"{LG}/threads/{thread_id}/runs", json={
        "assistant_id": assistants[0]["assistant_id"],
        "input": {"messages": [{"role": "user", "content": message}],
                  "customer_query": message, "session_id": thread_id},
        "config": {"configurable": configurable} if configurable else {},
    }, timeout=30)
    resp.raise_for_status()
    run_id = resp.json()["run_id"]
    deadline = time.time() + 150
    while time.time() < deadline:
        time.sleep(0.5)
        status = requests.get(f"{LG}/threads/{thread_id}/runs/{run_id}", timeout=10).json()
        if status.get("status") in ("completed", "success"):
            break
        if status.get("status") in ("failed", "cancelled"):
            raise RuntimeError(f"run 失败: {status}")
    state = requests.get(f"{LG}/threads/{thread_id}/state", timeout=10).json()
    return (state.get("values") or {}).get("response", "")


def open_tickets():
    r = requests.get(f"{FLASK}/api/tickets?status=open", timeout=10)
    return r.json()["tickets"]


def main():
    print("=" * 70)
    print("场景1：正常两轮对话（应无工单产生）")
    r1 = chat("我上周买的东西申请了退款，帮我查一下退款进度", "verify-e2e")
    print("回复1:", r1["response"][:80].replace("\n", " "))
    assert "账单专家" in r1["response"], r1
    r2 = chat("大概什么时候能到账？", "verify-e2e")
    print("回复2:", r2["response"][:80].replace("\n", " "))
    assert "账单专家" in r2["response"], r2
    assert all(t["thread_id"] != "verify-e2e" for t in open_tickets()), "正常对话不应产生工单"

    print("=" * 70)
    print("场景2：强制转人工（quality_threshold=10，同 thread）")
    reply = lg_run("verify-e2e", "帮我查退款进度", configurable={"quality_threshold": 10})
    print("回复:", reply[:80].replace("\n", " "))
    assert "人工工单" in reply, reply
    tickets = open_tickets()
    assert any(t["thread_id"] == "verify-e2e" for t in tickets), tickets
    ticket = [t for t in tickets if t["thread_id"] == "verify-e2e"][0]
    print(f"工单已落库: {ticket['id'][:8]}… 草稿回复: {ticket['draft_reply'][:40]}…")

    print("=" * 70)
    print("场景3：挂起中的会话再来消息（应等待人工，不新增工单）")
    n_before = len(open_tickets())
    reply = lg_run("verify-e2e", "补充一下我的订单号是 12345")
    print("回复:", reply[:80].replace("\n", " "))
    assert "转接人工" in reply, reply
    assert len(open_tickets()) == n_before, "挂起中不应产生新工单"

    print("=" * 70)
    print("场景4：resolve API 人工处理后恢复 AI")
    resp = requests.post(f"{FLASK}/api/tickets/{ticket['id']}/resolve",
                         json={"human_reply": "您好，人工客服已核实：您的退款预计明天 24 小时内到账原路账户。"},
                         timeout=30)
    print("resolve:", resp.json())
    assert resp.status_code == 200 and resp.json()["degraded"] is False, resp.text
    assert all(t["id"] != ticket["id"] for t in open_tickets())
    reply = lg_run("verify-e2e", "那大概什么时候到账？")
    print("恢复后回复:", reply[:100].replace("\n", " "))
    assert "账单专家" in reply, reply  # AI 已恢复接管

    print("=" * 70)
    print("✅ 全部 4 个场景验收通过")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 重启两个真服务（加载新代码）**

停掉旧的 langgraph dev 与 web_app 后台任务，重新启动：

```bash
cd "E:/mye盘项目/jianli project/customer-service-ai-agent"
./.venv/Scripts/langgraph.exe dev --no-browser --port 2024 > langgraph_dev.log 2>&1 &
./.venv/Scripts/python.exe web_app.py > web_app.log 2>&1 &
```

Run: `curl -s http://127.0.0.1:2024/ok && curl -s http://127.0.0.1:5000/api/health`
Expected: `{"ok":true}` + healthy

- [ ] **Step 3: 跑验收剧本**

Run: `./.venv/Scripts/python.exe deploy_verify.py`
Expected: 4 个场景全部通过，最后打印 ✅

- [ ] **Step 4: 清理验证数据并确认 Studio 图可见**

Run: `rm -f tickets.db* && curl -s -X POST http://127.0.0.1:2024/threads/search -H "Content-Type: application/json" -d '{}' | head -c 200`
说明：验证产生的 tickets.db 与 verify-e2e 线程属测试数据，验证完成后删除工单库文件即可（线程随 inmem 服务重启自动清空）。

- [ ] **Step 5: 提交**

```bash
git add deploy_verify.py
git commit -m "test: 端到端验收剧本（放行/转人工/挂起/人工处理四场景）"
```

---

## Self-Review 记录

- 规格覆盖：spec 的图结构（Task 3）、judge（Task 2）、工单库（Task 1）、API 与降级（Task 4）、阈值/开关（Task 3）、错误处理矩阵（Task 2/3/4 分布覆盖）、测试计划（Task 1-5）——无遗漏。
- 占位符：无 TBD/TODO；所有代码步骤给出完整代码。
- 类型一致性：`create_ticket(thread_id, user_query, draft_reply, quality_score, quality_reason)` 与 Task 3 调用一致；`inject_human_reply(thread_id, human_reply) -> (bool, err)` 与 Task 4 路由一致；`parse_judge_output -> (float, str)` 与 Task 3 使用一致。
- 实现时需现场核对的小项：`tools/__init__.py` 现有内容（追加而非覆盖）；langgraph-api 线程状态写回接口的 body 形状（若 `as_node` 不被接受则去掉该字段重试，均失败则走降级路径——spec 已允许）。
