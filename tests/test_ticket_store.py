# -*- coding: utf-8 -*-
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
    open_list = ticket_store.list_tickets(status="open")["items"]
    assert [t["id"] for t in open_list] == [t2]
    assert [t["id"] for t in ticket_store.list_tickets()["items"]] == [t2, t1]  # created_at 倒序
