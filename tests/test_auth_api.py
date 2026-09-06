# -*- coding: utf-8 -*-
"""S1=3.2 集成：坐席登录守卫 + 客户访客隔离（Flask test client）"""
import pytest

import auth_store
import web_app


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "tickets.db"))
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    auth_store.ensure_default_agent()  # 隔离库内创建默认坐席
    web_app.app.config["TESTING"] = True
    return tmp_path


@pytest.fixture()
def agent_client():
    c = web_app.app.test_client()
    r = c.post("/api/auth/login", json={"username": "agent", "password": "aegis-demo"})
    assert r.status_code == 200
    return c


def test_agent_endpoints_require_login(isolated):
    for method, path in [("GET", "/api/tickets"), ("GET", "/api/sessions"),
                         ("POST", "/api/chat/stream"), ("DELETE", "/api/sessions/x"),
                         ("GET", "/api/tickets/stream")]:
        resp = web_app.app.test_client().open(path, method=method)
        assert resp.status_code == 401, f"{method} {path} 未守卫"
    assert web_app.app.test_client().get("/api/auth/me").status_code == 401


def test_login_logout_me(agent_client):
    me = agent_client.get("/api/auth/me")
    assert me.get_json() == {"username": "agent", "role": "agent"}
    assert agent_client.post("/api/auth/logout").status_code == 200
    assert agent_client.get("/api/auth/me").status_code == 401


def test_login_rejects_bad_password(isolated):
    resp = web_app.app.test_client().post(
        "/api/auth/login", json={"username": "agent", "password": "wrong"})
    assert resp.status_code == 401


def test_customer_visitor_cookie_and_binding(isolated):
    c = web_app.app.test_client()
    r = c.get("/api/customer/sessions")
    assert r.status_code == 200
    assert "visitor_id" in r.headers.get("Set-Cookie", "")


def test_customer_cannot_read_others_session(isolated):
    # 访客1 绑定 th-mine；访客2 尝试读取 → 403
    auth_store.bind_thread_owner("th-mine", "visitor-1")
    c2 = web_app.app.test_client()
    c2.set_cookie("visitor_id", "visitor-2", domain="localhost")
    resp = c2.get("/api/customer/session/th-mine")
    assert resp.status_code == 403
    c1 = web_app.app.test_client()
    c1.set_cookie("visitor_id", "visitor-1", domain="localhost")
    # 归属校验通过后才进入 langgraph 读取（测试环境无 2024 → 500 属预期，但绝不能是 403）
    resp1 = c1.get("/api/customer/session/th-mine")
    assert resp1.status_code != 403


def test_customer_chat_rejects_foreign_session(isolated):
    auth_store.bind_thread_owner("th-owned", "visitor-1")
    c2 = web_app.app.test_client()
    c2.set_cookie("visitor_id", "visitor-2", domain="localhost")
    resp = c2.post("/api/customer/chat", json={"message": "hi", "session_id": "th-owned"})
    assert resp.status_code == 403


def test_resolve_requires_agent(isolated):
    import ticket_store
    tid = ticket_store.create_ticket("th-x", "q", "d", 1.0, "r")
    resp = web_app.app.test_client().post(f"/api/tickets/{tid}/resolve", json={"human_reply": "x"})
    assert resp.status_code == 401
