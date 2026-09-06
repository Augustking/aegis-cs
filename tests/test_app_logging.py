# -*- coding: utf-8 -*-
"""S3=3.7：结构化日志——request_id、PII 脱敏、耗时记录"""
import json

import app_logging


def test_mask_pii():
    assert app_logging.mask_pii("联系我 13812345678 谢谢") == "联系我 138****5678 谢谢"
    assert app_logging.mask_pii("邮箱 zhangsan@example.com 收件") == "邮箱 z***@example.com 收件"
    assert app_logging.mask_pii("不含敏感信息") == "不含敏感信息"


def test_request_id_isolates_and_propagates():
    app_logging.new_request_id()
    rid_main = app_logging.get_request_id()
    assert rid_main and rid_main != "-"
    app_logging.new_request_id()
    assert app_logging.get_request_id() != rid_main


def test_log_outputs_json_line(capsys):
    app_logging.new_request_id()
    app_logging.log("chat", "customer_message", message=app_logging.mask_pii("打电话 13999998888"),
                    thread_id="th-1", outcome="ok")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads(line)
    assert rec["component"] == "chat" and rec["event"] == "customer_message"
    assert rec["thread_id"] == "th-1"
    assert "13999998888" not in rec["message"]  # 已脱敏
    assert rec["request_id"] == app_logging.get_request_id()


def test_timed_logs_duration(capsys):
    with app_logging.timed("graph", "chat_run", thread_id="th-2"):
        pass
    line = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads(line)
    assert rec["event"] == "chat_run" and rec["duration_ms"] >= 0
