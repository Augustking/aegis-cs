# -*- coding: utf-8 -*-
"""决策轨迹：放行 / 转人工 / 挂起 / 护栏四条路径的轨迹记录。"""
import pytest

import multi_agent_customer_service as svc
from tests.test_graph_quality import FakeLLM, _FakeResp


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
