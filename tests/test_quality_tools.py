# -*- coding: utf-8 -*-
from langchain_core.messages import SystemMessage

from tools.quality_tools import build_judge_messages, parse_judge_output


def test_parse_clean_json():
    score, reason = parse_judge_output('{"score": 3, "reason": "答非所问"}')
    assert score == 3.0
    assert reason == "答非所问"


def test_parse_noisy_json():
    raw = '好的，结果如下：{"score": 2, "reason": "未解答用户问题"} 请参考'
    score, reason = parse_judge_output(raw)
    assert score == 2.0
    assert reason == "未解答用户问题"


def test_parse_garbage_fails_open():
    assert parse_judge_output("无法评价") == (10.0, "parse_failed")
    assert parse_judge_output(None) == (10.0, "parse_failed")
    assert parse_judge_output("") == (10.0, "parse_failed")


def test_parse_score_clamped():
    assert parse_judge_output('{"score": 15, "reason": "x"}')[0] == 10.0
    assert parse_judge_output('{"score": -3, "reason": "x"}')[0] == 0.0


def test_build_judge_messages():
    msgs = build_judge_messages("查退款", "请稍候", context="用户: 你好")
    assert isinstance(msgs[0], SystemMessage)
    assert "质检员" in msgs[0].content
    assert "对话历史上下文" in msgs[1].content
    assert "查退款" in msgs[1].content
    # 无上下文时不出现空段落
    no_context = build_judge_messages("查退款", "回复")
    assert "对话历史上下文" not in no_context[1].content


def test_build_judge_messages_carries_evidence():
    """接地质检：证据随消息下发，无证据时不出现空段落"""
    msgs = build_judge_messages("查退款", "回复", evidence="【退款政策】3-5个工作日到账")
    assert "业务数据证据" in msgs[1].content
    assert "3-5个工作日" in msgs[1].content
    no_ev = build_judge_messages("查退款", "回复")
    assert "业务数据证据" not in no_ev[1].content
