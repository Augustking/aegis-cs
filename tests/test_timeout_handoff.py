# -*- coding: utf-8 -*-
"""T2：运行超时不再 500，降级为落工单 + 返回转人工话术"""
import pytest

import chat_web_service as cws
import ticket_store


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "tickets.db"))


def test_handle_run_timeout_creates_ticket_and_reply():
    reply = cws.handle_run_timeout("th-timeout", "帮我查退款进度")
    assert "人工" in reply
    tickets = ticket_store.list_tickets(status="open")
    assert len(tickets) == 1
    t = tickets[0]
    assert t["thread_id"] == "th-timeout"
    assert t["user_query"] == "帮我查退款进度"
    assert t["quality_reason"] == "run_timeout"
    assert t["quality_score"] == 0.0


def test_handle_run_timeout_deduplicates():
    """超时落单前若已有 open 工单，不重复建"""
    cws.handle_run_timeout("th-dup", "问题一")
    cws.handle_run_timeout("th-dup", "问题二")
    assert len(ticket_store.list_tickets(status="open")) == 1


def test_run_wait_limit_env_override(monkeypatch):
    monkeypatch.setenv("RUN_WAIT_LIMIT", "7")
    import importlib
    importlib.reload(cws)
    assert cws.RUN_WAIT_LIMIT == 7
