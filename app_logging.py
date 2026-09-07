"""
结构化日志（3.7）：
- request_id 贯穿一次 HTTP 请求（contextvar，任意层可取）
- JSON 行输出到 stdout，便于采集
- 消息内容脱敏（手机号/邮箱打码），默认对 message/reply 类字段启用

用法：
    from app_logging import log, get_request_id, mask_pii
    log("chat", "customer_message", message=mask_pii(text), thread_id=tid)
"""

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from typing import Any

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_logger = logging.getLogger("aegis")
if not _logger.handlers:
    # 每次写日志时取当前 sys.stdout（兼容测试捕获与重定向）
    class _DynamicStdoutHandler(logging.StreamHandler):
        def emit(self, record):
            self.stream = sys.stdout
            super().emit(record)

    _handler = _DynamicStdoutHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+)")


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    _request_id.set(rid)
    return rid


def get_request_id() -> str:
    return _request_id.get()


def mask_pii(text: str) -> str:
    """手机号 138****1234 / 邮箱 a***@domain 打码。"""
    if not isinstance(text, str):
        return text
    text = _PHONE_RE.sub(r"\1****\2", text)
    text = _EMAIL_RE.sub(r"\1***\2", text)
    return text


def log(component: str, event: str, level: str = "info", **fields: Any) -> None:
    """输出一行 JSON 日志；额外字段值中的字符串做 PII 脱敏。"""
    record = {
        "ts": round(time.time(), 3),
        "level": level,
        "request_id": get_request_id(),
        "component": component,
        "event": event,
    }
    for k, v in fields.items():
        record[k] = mask_pii(v) if isinstance(v, str) else v
    try:
        _logger.info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:
        pass  # 日志失败不影响业务


class timed:
    """耗时记录装饰器/上下文：with timed("graph", "chat_run", thread_id=tid): ..."""

    def __init__(self, component: str, event: str, **fields: Any):
        self.component, self.event, self.fields = component, event, fields

    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        fields = dict(self.fields)
        fields["duration_ms"] = int((time.time() - self.t0) * 1000)
        if exc_type:
            fields["error"] = str(exc)
            log(self.component, self.event + "_failed", level="error", **fields)
        else:
            log(self.component, self.event, **fields)
        return False
