"""
客服 Web 业务逻辑：图直连调用（graph_runtime）、线程状态解析、会话列表拼装等。
S2 起不再依赖独立 langgraph dev 服务（2024），对话状态由 checkpointer 持久化。
与 Flask 路由解耦，便于单测与复用。
"""

from __future__ import annotations

import json
import os
import time
import datetime as _dt
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

import auth_store
import graph_runtime
import ticket_store

load_dotenv()

# -----------------------------------------------------------------------------
# 配置（可被环境变量覆盖）
# -----------------------------------------------------------------------------

LANGGRAPH_API_URL: str = os.getenv("LANGGRAPH_API_URL", "http://127.0.0.1:2024").rstrip("/")
LANGGRAPH_GRAPH_NAME: str = os.getenv("LANGGRAPH_GRAPH_NAME", "customer_service")

# 单轮对话等待上限（秒）；超时不再返回 500，而是降级为落工单 + 转人工话术
RUN_WAIT_LIMIT: int = int(os.getenv("RUN_WAIT_LIMIT", "90"))

# 超时降级时给用户的固定话术（与图内 HANDOFF_REPLY 语义一致）
TIMEOUT_HANDOFF_REPLY = (
    "抱歉，当前咨询量较大，您的问题已转人工客服处理，客服专员会尽快回复，请稍候。"
)

# 兼容旧调用（S2 起线程直连，不再有全局助手/线程缓存）
_assistant_id: Optional[str] = None
_current_thread_id: Optional[str] = None


def get_assistant_id() -> Optional[str]:
    return _assistant_id


def get_current_thread_id() -> Optional[str]:
    """兼容保留：S2 起聊天函数直接返回 thread_id，请优先使用返回值。"""
    return _current_thread_id


# -----------------------------------------------------------------------------
# 线程 values → 对话列表 / 侧栏预览
# -----------------------------------------------------------------------------

def append_turn_from_state(conversation_history: List[Dict[str, Any]], msg: Dict[str, Any]) -> None:
    """从状态中的单条消息追加到会话历史列表；仅在状态里带有 timestamp 时写入条目。"""
    content = msg.get("content", "") or ""
    if not content:
        return
    is_user = bool(msg.get("is_user", False))
    entry: Dict[str, Any] = {
        "is_user": is_user,
        "content": content,
        "role": "user" if is_user else "assistant",
    }
    author = msg.get("author")
    if author:
        entry["author"] = author
    ts = msg.get("timestamp")
    if ts is not None and ts != "":
        entry["timestamp"] = ts
    conversation_history.append(entry)


def conversation_history_from_values(values: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从图线程 values 解析对话列表。"""
    conversation_history: List[Dict[str, Any]] = []
    if not isinstance(values, dict):
        return conversation_history

    source_turns = None
    pd_raw = values.get("persisted_dialogue")
    ch_raw = values.get("conversation_history")
    if isinstance(pd_raw, list) and len(pd_raw) > 0:
        source_turns = pd_raw
    elif isinstance(ch_raw, list) and len(ch_raw) > 0:
        source_turns = ch_raw

    if source_turns is not None:
        for msg in source_turns:
            if isinstance(msg, dict):
                append_turn_from_state(conversation_history, msg)
    elif isinstance(values.get("messages"), list):
        for message in values["messages"]:
            if isinstance(message, dict):
                role = message.get("role", "user")
                content = message.get("content", "")
                if content:
                    conversation_history.append({
                        "is_user": role == "user",
                        "content": content,
                        "role": role,
                    })
    return conversation_history


def last_user_question_from_history(conversation_history: List[Dict[str, Any]]) -> str:
    """取最后一条用户消息的纯文本（用于侧栏预览）。"""
    for msg in reversed(conversation_history):
        if not msg.get("is_user"):
            continue
        s = str(msg.get("content", "")).strip()
        if s:
            return s
    return ""


# -----------------------------------------------------------------------------
# 线程解析
# -----------------------------------------------------------------------------

def resolve_thread_id(client_session_id: Optional[str]) -> str:
    """客户/坐席传入的会话 ID 即线程 ID；default/空则新建。"""
    if client_session_id and client_session_id.strip() and client_session_id != "default":
        tid = client_session_id.strip()
    else:
        tid = graph_runtime.new_thread_id()
    auth_store.record_thread(tid)
    return tid


def fetch_sessions_list() -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """全量会话列表（坐席侧），按线程索引新→旧。"""
    sessions: List[Dict[str, Any]] = []
    for item in auth_store.list_threads():
        tid = item["thread_id"]
        values = graph_runtime.get_thread_values(tid)
        history = conversation_history_from_values(values)
        sessions.append({
            "session_id": tid,
            "created_at": item["created_at"],
            "message_count": len(history),
            "last_user_question": last_user_question_from_history(history),
        })
    return sessions, None


def fetch_session_detail(session_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """会话详情：对话历史 + 决策轨迹。"""
    values = graph_runtime.get_thread_values(session_id)
    return {
        "session_id": session_id,
        "created_at": time.time(),
        "conversation_history": conversation_history_from_values(values),
        "decision_trace": list(values.get("decision_trace") or []),
    }, None


def delete_remote_thread(thread_id: str) -> Tuple[bool, int]:
    """删除线程：检查点 + 索引记录。"""
    ok = graph_runtime.delete_thread(thread_id)
    auth_store.delete_thread_record(thread_id)
    return ok, 200 if ok else 500


def clear_thread_and_create_new(thread_id: str) -> Tuple[Optional[str], Optional[str]]:
    """删除旧线程并新建线程 ID。成功返回 (new_thread_id, None)。"""
    ok, status = delete_remote_thread(thread_id)
    if not ok:
        # 检查点删除失败不阻塞换新会话（旧检查点随 TTL/重启清理）
        print(f"⚠️ 线程 {thread_id} 检查点删除失败（{status}），仍创建新会话")
    new_thread_id = graph_runtime.new_thread_id()
    auth_store.record_thread(new_thread_id)
    return new_thread_id, None


def handle_run_timeout(thread_id: str, user_message: str) -> str:
    """运行超时降级：落工单（幂等）并返回转人工话术，不再向上抛 500。"""
    try:
        if not ticket_store.has_open_ticket(thread_id):
            ticket_store.create_ticket(
                thread_id=thread_id,
                user_query=user_message,
                draft_reply="（运行超时，AI 未在时限内完成应答，无草稿）",
                quality_score=0.0,
                quality_reason="run_timeout",
            )
    except Exception as e:
        print(f"❌ 超时落工单失败（话术照常返回）: {e}")
    return TIMEOUT_HANDOFF_REPLY


# -----------------------------------------------------------------------------
# 一次聊天运行（图直连 + 超时降级）
# -----------------------------------------------------------------------------

def run_chat_sync(user_message: str, client_session_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[str]]:
    """
    在指定线程上执行一轮对话（图直连）。
    返回 (ai_text, error_text, http_status, thread_id)；超时时 ai_text 为降级话术、
    error 为 'run_timeout'、thread_id 仍返回以便前端续用该会话。
    """
    global _current_thread_id
    if not user_message.strip():
        return None, '消息不能为空', 400, None

    thread_id = resolve_thread_id(client_session_id)
    _current_thread_id = thread_id

    ai_text, err, code = graph_runtime.run_in_thread(
        thread_id, user_message.strip(), RUN_WAIT_LIMIT
    )
    if err == "run_timeout":
        return handle_run_timeout(thread_id, user_message.strip()), "run_timeout", 504, thread_id
    if err:
        return None, err, code, thread_id
    return ai_text, None, None, thread_id


def stream_chat_events(user_message: str, client_session_id: Optional[str] = None) -> Iterable[str]:
    """SSE 一次聊天运行（直连版：完成后单事件输出）。"""
    if not user_message.strip():
        yield f"data: {json.dumps({'error': '消息不能为空'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    thread_id = resolve_thread_id(client_session_id)
    ai_text, err, _code = graph_runtime.run_in_thread(
        thread_id, user_message.strip(), RUN_WAIT_LIMIT
    )
    if err == "run_timeout":
        yield f"data: {json.dumps({'content': handle_run_timeout(thread_id, user_message.strip()), 'timeout_handoff': True, 'session_id': thread_id, 'thread_id': thread_id}, ensure_ascii=False)}\n\n"
    elif err:
        yield f"data: {json.dumps({'error': err})}\n\n"
    else:
        yield f"data: {json.dumps({'content': ai_text, 'session_id': thread_id, 'thread_id': thread_id}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def inject_human_reply(thread_id: str, human_reply: str) -> Tuple[bool, Optional[str]]:
    """把人工坐席回复写回线程 persisted_dialogue（作为坐席轮次），恢复 AI 上下文。"""
    values = graph_runtime.get_thread_values(thread_id)
    pd = list(values.get("persisted_dialogue") or [])
    pd.append({
        "content": str(human_reply),
        "is_user": False,
        "author": "human",
        "timestamp": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    ok = graph_runtime.update_thread_values(thread_id, {"persisted_dialogue": pd})
    if not ok:
        return False, "写回线程状态失败"
    return True, None


# -----------------------------------------------------------------------------
# 工单 SSE（坐席队列变化推送）
# -----------------------------------------------------------------------------

def ticket_change_event(last_ids, ids):
    """diff 两次 open 工单 id 列表 → SSE 事件；无变化返回 None。"""
    if last_ids is None:
        return {"type": "init", "open_count": len(ids)}
    if ids == last_ids:
        return None
    return {
        "type": "update",
        "open_count": len(ids),
        "new_ids": [i for i in ids if i not in last_ids],
    }


def ticket_stream_events(poll_interval: float = 2.0):
    """SSE 生成器：轮询共享工单库产出事件；查询异常发 error 事件后继续（不断流）。"""
    last_ids = None
    while True:
        try:
            ids = [t["id"] for t in ticket_store.list_tickets(status="open")]
            event = ticket_change_event(last_ids, ids)
            if event:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            last_ids = ids
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        time.sleep(poll_interval)


def langgraph_connectivity_test() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """健康自检：图编译 + 工单库可用性（嵌入模式）。"""
    try:
        graph_ok = graph_runtime.get_app() is not None
        ticket_ok = isinstance(ticket_store.list_tickets(), list)
        return ({
            'status': 'test_completed',
            'mode': 'embedded',
            'graph': 'ok' if graph_ok else 'failed',
            'tickets_db': 'ok' if ticket_ok else 'failed',
        }, None)
    except Exception as e:
        return None, f'自检失败: {e}'
