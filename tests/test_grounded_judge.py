# -*- coding: utf-8 -*-
"""T1/T5 组合验收：接地质检 + 可信度一票否决"""
import pytest

import multi_agent_customer_service as svc
import ticket_store
from tests.test_graph_quality import FakeLLM, _FakeResp, _patch_llm


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "tickets.db"))


class GroundedJudgeLLM(FakeLLM):
    """agent 输出含编造承诺（1小时到账）；质检按证据判定 faithfulness。"""

    def invoke(self, messages):
        system = self._system(messages)
        if "查询分类专家" in system:
            return _FakeResp("billing")  # 分类必须走 billing，才有退款证据
        if "质检员" in system:
            human = ""
            for m in messages:
                if getattr(m, "type", "") == "human":
                    human = m.content
            # 编造承诺"1小时到账"在证据中无依据 → faithfulness 0
            if "1小时" in human:
                return _FakeResp("relevance=4; completeness=3; faithfulness=0; reason=承诺无证据")
            return _FakeResp("relevance=4; completeness=3; faithfulness=3; reason=与证据一致")
        return _FakeResp("您好，您的退款将在1小时内到账。")

    @staticmethod
    def _system(messages):
        for m in messages:
            if getattr(m, "type", "") == "system":
                return m.content
        return ""


def test_faithfulness_zero_forces_handoff(monkeypatch):
    """总分过线但 faithfulness=0 → 一票否决转人工"""
    _patch_llm(monkeypatch, GroundedJudgeLLM())
    app = svc.make_graph()
    state = app.invoke({"customer_query": "退款什么时候到账", "session_id": "t-veto"})
    assert state["needs_human"] is True
    assert "faithfulness_veto" in state["quality_reason"]
    assert len(ticket_store.list_tickets(status="open")) == 1


def test_grounded_evidence_reaches_judge(monkeypatch):
    """业务 Agent 的证据上下文进入 judge 消息（接地质检）"""
    seen = {}

    class Spy(GroundedJudgeLLM):
        def invoke(self, messages):
            if "质检员" in self._system(messages):
                seen["judge_input"] = [m.content for m in messages]
            return super().invoke(messages)

    _patch_llm(monkeypatch, Spy())
    app = svc.make_graph()
    app.invoke({"customer_query": "退款什么时候到账", "session_id": "t-ev"})
    judge_human = [c for c in seen["judge_input"] if "质检员" not in c][0]
    assert "业务数据证据" in judge_human
