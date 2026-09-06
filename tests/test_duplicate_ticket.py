# -*- coding: utf-8 -*-
"""T4：同一会话已有 open 工单时，human_handoff 不重复建单"""
import pytest

import multi_agent_customer_service as svc
import ticket_store


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "tickets.db"))


def _state(session_id):
    return {
        "session_id": session_id,
        "customer_query": "帮我查退款进度",
        "response": "被驳回的草稿回答",
        "quality_score": 2.0,
        "quality_reason": "答非所问",
        "tools_used": [],
        "persisted_dialogue": [],
    }


def test_handoff_dedupes_open_ticket(tmp_path):
    s1 = svc.human_handoff_node(_state("th-dedup"))
    first_id = s1["ticket_id"]
    assert first_id
    assert len(ticket_store.list_tickets(status="open")) == 1

    # 挂起检查失效等异常场景下，第二次进入 handoff 节点
    s2 = svc.human_handoff_node(_state("th-dedup"))
    assert s2["needs_human"] is True
    assert s2["ticket_id"] == first_id, "应复用已有工单而非新建"
    assert len(ticket_store.list_tickets(status="open")) == 1
