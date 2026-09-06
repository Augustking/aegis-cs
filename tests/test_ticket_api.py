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
    resp = client.post(
        f"/api/tickets/{tid}/resolve",
        json={"human_reply": "已人工处理，退款 3 天内到账"},
    )
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
