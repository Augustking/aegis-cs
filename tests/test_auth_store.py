# -*- coding: utf-8 -*-
"""S1=3.2：坐席认证 + 访客会话归属隔离"""
import pytest

import auth_store


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))


def test_default_agent_bootstrap_and_login():
    assert auth_store.ensure_default_agent() is not None  # 首次创建
    assert auth_store.ensure_default_agent() is None      # 幂等
    user = auth_store.verify_login("agent", "aegis-demo")
    assert user == {"username": "agent", "role": "agent"}
    assert auth_store.verify_login("agent", "wrong") is None
    assert auth_store.verify_login("nobody", "aegis-demo") is None


def test_create_user_duplicate_and_roles():
    auth_store.create_user("alice", "pw-agent", role="agent")
    auth_store.create_user("boss", "pw-admin", role="admin")
    assert auth_store.verify_login("alice", "pw-agent")["role"] == "agent"
    assert auth_store.verify_login("boss", "pw-admin")["role"] == "admin"
    with pytest.raises(ValueError):
        auth_store.create_user("alice", "other")


def test_thread_ownership_binding_and_isolation():
    auth_store.bind_thread_owner("th-a", "visitor-1")
    auth_store.bind_thread_owner("th-a", "visitor-1")   # 重复绑定不报错
    auth_store.bind_thread_owner("th-a", "visitor-2")   # 不覆盖已有归属
    assert auth_store.visitor_owns_thread("th-a", "visitor-1") is True
    assert auth_store.visitor_owns_thread("th-a", "visitor-2") is False
    assert auth_store.visitor_owns_thread("th-unknown", "visitor-1") is False
    assert auth_store.threads_of_visitor("visitor-1") == ["th-a"]
    assert auth_store.threads_of_visitor("visitor-2") == []
