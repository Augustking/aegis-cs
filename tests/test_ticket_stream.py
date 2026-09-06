# -*- coding: utf-8 -*-
import json

import ticket_store
from chat_web_service import ticket_change_event, ticket_stream_events


def test_ticket_change_event_states():
    assert ticket_change_event(None, ["a"]) == {"type": "init", "open_count": 1}
    assert ticket_change_event(["a"], ["a"]) is None
    assert ticket_change_event(["a"], ["b", "a"]) == {
        "type": "update", "open_count": 2, "new_ids": ["b"],
    }
    # 工单被关闭也要推送（数量变化）
    assert ticket_change_event(["a", "b"], ["a"]) == {
        "type": "update", "open_count": 1, "new_ids": [],
    }


def test_ticket_stream_events_init_then_update(monkeypatch, tmp_path):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "t.db"))
    gen = ticket_stream_events(poll_interval=0.05)
    first = json.loads(next(gen).removeprefix("data: ").strip())
    assert first["type"] == "init" and first["open_count"] == 0

    ticket_store.create_ticket("th", "q", "d", 1.0, "r")  # 制造变化
    second = json.loads(next(gen).removeprefix("data: ").strip())
    assert second["type"] == "update"
    assert second["open_count"] == 1 and len(second["new_ids"]) == 1
