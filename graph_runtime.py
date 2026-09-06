"""
图运行时：在 Flask 进程内编译并持有带持久化 checkpointer 的图，
取代独立 langgraph dev 服务（消除 2024 端口依赖，对话状态跨重启恢复）。

- CHECKPOINT_DB：SqliteSaver 数据文件路径（默认 <项目根>/checkpoints.sqlite）；
  预留 postgres:// DSN 形式，配置后切换 PostgresSaver（需 langgraph-checkpoint-postgres）。
- run_in_thread：单轮对话在线程池执行，RUN_WAIT_LIMIT 超时返回超时降级
  （图调用留在后台完成，状态最终写入 checkpointer）。
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional, Tuple

from langgraph.checkpoint.sqlite import SqliteSaver

import app_logging
import multi_agent_customer_service as svc

_checkpointer = None
_app = None
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=4)


def _checkpoint_db() -> str:
    return os.getenv("CHECKPOINT_DB") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "checkpoints.sqlite"
    )


def get_app():
    """编译并缓存带 checkpointer 的图（线程安全）。"""
    global _checkpointer, _app
    if _app is None:
        with _lock:
            if _app is None:
                dsn = os.getenv("CHECKPOINT_DB", "")
                if dsn.startswith("postgres://") or dsn.startswith("postgresql://"):
                    raise NotImplementedError(
                        "Postgres checkpointer 需安装 langgraph-checkpoint-postgres 并配置连接；"
                        "当前部署使用 SQLite。"
                    )
                import sqlite3
                # 执行器线程会访问连接，必须 check_same_thread=False；
                # 连接随进程存活（不使用 from_conn_string 的 CM——其 GC 会关闭连接）
                conn = sqlite3.connect(_checkpoint_db(), check_same_thread=False)
                _checkpointer = SqliteSaver(conn)
                _checkpointer.setup()
                _app = svc.make_graph(checkpointer=_checkpointer)
    return _app


def new_thread_id() -> str:
    import uuid
    return str(uuid.uuid4())


def run_in_thread(thread_id: str, user_message: str, wait_limit: int,
                  configurable: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """
    在图上同步执行一轮对话；超过 wait_limit 秒返回超时降级信号，
    由调用方决定转人工（图调用在后台继续完成并写入 checkpointer）。
    返回 (ai_text, error_text, http_code)；ai_text 为 None 表示超时未完成。
    """
    cfg = {"configurable": {"thread_id": thread_id, **(configurable or {})}}
    inp = {
        "messages": [{"role": "user", "content": user_message}],
        "customer_query": user_message,
        "session_id": thread_id,
    }
    future = _executor.submit(get_app().invoke, inp, cfg)
    try:
        with app_logging.timed("graph", "chat_run", thread_id=thread_id):
            state = future.result(timeout=max(5, int(wait_limit)))
    except TimeoutError:
        app_logging.log("graph", "chat_run_timeout", thread_id=thread_id, wait_limit=wait_limit)
        return None, "run_timeout", 504
    except Exception as e:
        return None, f"运行失败: {e}", 500

    response = state.get("response") or "抱歉，我无法理解您的问题。"
    return str(response), None, None


def get_thread_values(thread_id: str) -> Dict[str, Any]:
    """读取线程持久化状态（不存在时返回空 dict）。"""
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        snap = get_app().get_state(cfg)
    except Exception:
        return {}
    return dict(snap.values or {})


def update_thread_values(thread_id: str, values: Dict[str, Any], as_node: str = "final_response") -> bool:
    """写回线程状态（人工回复注入等）；成功 True。"""
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        get_app().update_state(cfg, values, as_node=as_node)
        return True
    except Exception as e:
        print(f"❌ 更新线程状态失败: {e}")
        return False


def delete_thread(thread_id: str) -> bool:
    """删除线程检查点；saver 不支持时返回 False（调用方降级）。"""
    saver = _checkpointer
    if saver is not None and hasattr(saver, "delete_thread"):
        try:
            saver.delete_thread(thread_id)
            return True
        except Exception as e:
            print(f"❌ 删除线程检查点失败: {e}")
    return False
