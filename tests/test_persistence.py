# -*- coding: utf-8 -*-
"""S2=3.6：图内嵌 + checkpointer 持久化（重启可恢复）+ 超时降级"""
import json

import pytest

import auth_store
import chat_web_service as cws
import graph_runtime
import multi_agent_customer_service as svc
import ticket_store
from tests.test_graph_quality import FakeLLM, _FakeResp, _patch_llm


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "tickets.db"))
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "checkpoints.sqlite"))
    graph_runtime._app = None
    graph_runtime._checkpointer = None
    _patch_llm(monkeypatch, FakeLLM())
    yield
    graph_runtime._app = None
    graph_runtime._checkpointer = None


def test_chat_persists_across_graph_rebuild(tmp_path):
    """对话写入 checkpointer 后，重建图实例（模拟重启）状态仍在。"""
    text, err, code, tid = cws.run_chat_sync("帮我查退款进度", None)
    assert err is None and tid
    assert "账单专家" in text

    # 模拟重启：丢弃内存中的图与 checkpointer，重建后读同一线程
    graph_runtime._app = None
    graph_runtime._checkpointer = None
    values = graph_runtime.get_thread_values(tid)
    pd = values.get("persisted_dialogue") or []
    assert any("帮我查退款进度" in m.get("content", "") for m in pd)
    # AI 轮次 = 业务智能体原始回复（无 final 前缀）
    assert any(not m.get("is_user", True) for m in pd)
    detail, err2 = cws.fetch_session_detail(tid)
    assert err2 is None
    assert len(detail["conversation_history"]) >= 2
    steps = [s["step"] for s in detail["decision_trace"]]
    assert "quality_check" in steps


def test_sessions_list_and_delete(tmp_path):
    _, _, _, tid1 = cws.run_chat_sync("查退款", None)
    _, _, _, tid2 = cws.run_chat_sync("耳机坏了", None)
    sessions, err = cws.fetch_sessions_list()
    assert err is None
    ids = {s["session_id"] for s in sessions}
    assert {tid1, tid2} <= ids

    ok, _ = cws.delete_remote_thread(tid1)
    assert ok is True
    sessions, _ = cws.fetch_sessions_list()
    assert tid1 not in {s["session_id"] for s in sessions}


def test_run_timeout_degrades_to_ticket(tmp_path, monkeypatch):
    """图执行超过 RUN_WAIT_LIMIT → 转人工话术 + run_timeout 工单"""
    import time

    class SlowLLM(FakeLLM):
        def invoke(self, messages):
            time.sleep(3)
            return super().invoke(messages)

    _patch_llm(monkeypatch, SlowLLM())
    monkeypatch.setattr(cws, "RUN_WAIT_LIMIT", 1)
    text, err, code, tid = cws.run_chat_sync("帮我查退款进度", None)
    assert err == "run_timeout"
    assert "转人工" in text
    assert code == 504
    tickets = ticket_store.list_tickets(status="open")
    assert len(tickets) == 1
    assert tickets[0]["quality_reason"] == "run_timeout"
    assert tickets[0]["thread_id"] == tid


def test_inject_human_reply_marks_author(tmp_path):
    _, _, _, tid = cws.run_chat_sync("帮我查退款进度", None)
    ok, err = cws.inject_human_reply(tid, "人工已核实：3-5 个工作日到账。")
    assert ok and err is None
    values = graph_runtime.get_thread_values(tid)
    last = (values.get("persisted_dialogue") or [])[-1]
    assert last["author"] == "human"
    history, _ = cws.fetch_session_detail(tid)
    human_turns = [m for m in history["conversation_history"] if m.get("author") == "human"]
    assert human_turns and "人工已核实" in human_turns[-1]["content"]
