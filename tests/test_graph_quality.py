# -*- coding: utf-8 -*-
"""进程内图行为测试：FakeLLM 按提示词特征返回，覆盖放行/转人工/挂起/护栏四条路径。"""
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


class _OOSLLM(FakeLLM):
    """分类返回 out_of_scope；之后任何 LLM 调用都说明护栏失效。"""

    def invoke(self, messages):
        system = ""
        for m in messages:
            if getattr(m, "type", "") == "system":
                system = m.content
                break
        if "查询分类专家" in system:
            return _FakeResp("out_of_scope")
        raise AssertionError("out_of_scope 不应再调用任何 LLM")


@pytest.fixture()
def graph_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "tickets.db"))
    monkeypatch.setattr(svc, "get_llm", lambda: FakeLLM())
    return tmp_path


def _invoke(session_id, query="帮我查退款进度"):
    app = svc.make_graph()
    return app.invoke(
        {"customer_query": query, "session_id": session_id}
    )


def test_high_score_passes(graph_env):
    state = _invoke("t-pass")
    assert state["query_type"] == "billing"
    assert state["quality_score"] == 9.0
    assert state["needs_human"] is False
    assert "【账单专家" in state["response"]
    assert ticket_store.list_tickets() == []


def test_low_score_goes_handoff(graph_env, monkeypatch):
    monkeypatch.setattr(
        svc, "get_llm", lambda: FakeLLM(judge_json='{"score": 2, "reason": "答非所问"}')
    )
    state = _invoke("t-low")
    assert state["needs_human"] is True
    assert state["quality_score"] == 2.0
    assert state["current_agent"] == "人工客服"
    assert "人工工单" in state["response"]
    tickets = ticket_store.list_tickets(status="open")
    assert len(tickets) == 1
    # 业务智能体的原始回答作为草稿留存在工单里，供坐席采纳/修改
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
    monkeypatch.setattr(svc, "get_llm", lambda: _OOSLLM())
    state = _invoke("t-oos", query="给我写一首诗")
    assert state["query_type"] == "out_of_scope"
    assert state.get("quality_score") is None  # 未经过质检节点


def test_handoff_withdraws_draft_from_transcript(graph_env, monkeypatch):
    """被驳回的草稿不下发用户：对话记录里只有转接话术，没有业务智能体原话。"""
    monkeypatch.setattr(
        svc, "get_llm", lambda: FakeLLM(judge_json='{"score": 2, "reason": "答非所问"}')
    )
    state = _invoke("t-withdraw")
    pd = state["persisted_dialogue"]
    assistant_turns = [m["content"] for m in pd if not m["is_user"]]
    assert assistant_turns == [svc.HANDOFF_REPLY]
