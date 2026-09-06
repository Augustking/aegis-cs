# -*- coding: utf-8 -*-
"""T5：质检三维评分（相关性/解答度/可信度），总分加权，维度落库与轨迹"""
import pytest

import ticket_store
from tools.quality_tools import build_judge_messages, parse_judge_dims, parse_judge_output


def test_parse_dims_full():
    raw = '{"score": 5, "reason": "部分解答", "dims": {"relevance": 3, "completeness": 1, "faithfulness": 1}}'
    score, reason = parse_judge_output(raw)
    dims = parse_judge_dims(raw)
    assert score == 5.0 and reason == "部分解答"
    assert dims == {"relevance": 3.0, "completeness": 1.0, "faithfulness": 1.0}


def test_parse_flat_format():
    """扁平 key=value 格式（7B 模型首选，嵌套 JSON 不可靠）"""
    raw = "score=5; reason=部分解答; relevance=3; completeness=1; faithfulness=1"
    assert parse_judge_output(raw) == (5.0, "部分解答")
    assert parse_judge_dims(raw) == {"relevance": 3.0, "completeness": 1.0, "faithfulness": 1.0}


def test_parse_dims_missing_or_garbage():
    """旧格式（无 dims）与垃圾输出都返回 None，主流程不受影响"""
    assert parse_judge_dims('{"score": 8, "reason": "ok"}') is None
    assert parse_judge_dims(None) is None
    assert parse_judge_dims("无法评价") is None


def test_judge_prompt_requires_dims():
    msg = build_judge_messages("q", "a")
    assert "relevance" in msg[0].content
    assert "completeness" in msg[0].content
    assert "faithfulness" in msg[0].content


def test_ticket_stores_quality_dims(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_DB_PATH", str(tmp_path / "t.db"))
    import json as _json
    tid = ticket_store.create_ticket(
        thread_id="th", user_query="q", draft_reply="d",
        quality_score=5.0, quality_reason="部分解答",
        quality_dims={"relevance": 3.0, "completeness": 1.0, "faithfulness": 1.0},
    )
    t = ticket_store.get_ticket(tid)
    assert _json.loads(t["quality_dims"])["relevance"] == 3.0
