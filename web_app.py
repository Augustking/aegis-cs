#!/usr/bin/env python3
"""
多智能体客服系统 - Web 入口
基于 LangGraph API 接口，路由与 Flask 会话；业务逻辑见 chat_web_service.py
"""

import os
import time
from typing import Dict, Any, List

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, g, request, jsonify, session, Response, send_from_directory

from chat_web_service import (
    run_chat_sync,
    stream_chat_events,
    fetch_sessions_list,
    fetch_session_detail,
    delete_remote_thread,
    clear_thread_and_create_new,
    langgraph_connectivity_test,
    get_current_thread_id,
    inject_human_reply,
    ticket_stream_events,
)
from functools import wraps

import app_logging
import auth_store
import ticket_store

# 导入配置（与历史行为保持一致）
from config import *  # noqa: E402,F401,F403

DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")
app = Flask(__name__, static_folder=None)

# Flask 配置
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your-secret-key-here")
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = __import__('datetime').timedelta(hours=12)

auth_store.ensure_default_agent()


@app.before_request
def _assign_request_id():
    app_logging.new_request_id()


@app.after_request
def _access_log(resp):
    app_logging.log("http", "access", method=request.method,
                    path=request.path, status=resp.status_code)
    return resp


def require_agent(fn):
    """坐席接口守卫：未登录返回 401；前端守卫只是体验，后端才是边界。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('agent_user'):
            return jsonify({'error': '需要坐席登录'}), 401
        return fn(*args, **kwargs)
    return wrapper


def get_visitor_id():
    """访客身份：cookie 缺失时生成本请求内固定的新 ID（g 缓存）。
    必须请求内单例——多处调用若各自随机，绑定归属与下发 cookie 会不一致。"""
    if 'visitor_id' in g:
        return g.visitor_id
    vid = request.cookies.get('visitor_id')
    if not vid:
        vid = auth_store.new_visitor_id()
    g.visitor_id = vid
    g.visitor_is_new = not bool(request.cookies.get('visitor_id'))
    return vid


def visitor_response(payload, status=200):
    get_visitor_id()  # 确保本请求已解析访客身份
    resp = jsonify(payload)
    resp.status_code = status
    if getattr(g, 'visitor_is_new', False):
        resp.set_cookie('visitor_id', g.visitor_id, httponly=True, samesite='Lax', max_age=90 * 86400)
    return resp


def derive_service_state(thread_id: str) -> str:
    """客户服务状态：normal / waiting（有 open 工单）/ human（人工已回复）。"""
    t = ticket_store.latest_ticket_for_thread(thread_id)
    if not t:
        return 'normal'
    if t['status'] == 'open':
        return 'waiting'
    if t.get('human_reply'):
        return 'human'
    return 'normal'


# --- Flask session 内的本地对话占位（主页模板可能使用）---

def get_conversation_history(session_id: str) -> List[Dict[str, Any]]:
    if 'conversations' not in session:
        session['conversations'] = {}
    return session['conversations'].get(session_id, [])


def add_conversation_message(session_id: str, role: str, content: str) -> None:
    history = get_conversation_history(session_id)
    history.append({
        'role': role,
        'content': content,
    })
    session['conversations'][session_id] = history


@app.route('/')
def index():
    """SPA 入口；dist 未构建时给出提示"""
    if os.path.isfile(os.path.join(DIST_DIR, "index.html")):
        return send_from_directory(DIST_DIR, "index.html")
    return "前端尚未构建：请在 frontend/ 目录执行 npm install && npm run build", 200, {
        "Content-Type": "text/plain; charset=utf-8"
    }


@app.route('/<path:path>')
def spa_assets_and_fallback(path):
    """静态资源 + history 路由 fallback；显式 /api 路由优先级更高不会进入这里"""
    if path.startswith("api/"):
        return jsonify({'error': 'not found'}), 404
    if os.path.isfile(os.path.join(DIST_DIR, path)):
        return send_from_directory(DIST_DIR, path)
    if os.path.isfile(os.path.join(DIST_DIR, "index.html")):
        return send_from_directory(DIST_DIR, "index.html")
    return jsonify({'error': 'not found'}), 404


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json() or {}
    user = auth_store.verify_login((data.get('username') or '').strip(), data.get('password') or '')
    if not user:
        return jsonify({'error': '用户名或密码错误'}), 401
    session['agent_user'] = user['username']
    session['agent_role'] = user['role']
    session.permanent = True
    return jsonify({'username': user['username'], 'role': user['role']})


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.pop('agent_user', None)
    session.pop('agent_role', None)
    return jsonify({'message': '已退出'})


@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    if not session.get('agent_user'):
        return jsonify({'error': '未登录'}), 401
    return jsonify({'username': session['agent_user'], 'role': session.get('agent_role', 'agent')})


@app.route('/api/customer/chat', methods=['POST'])
def customer_chat():
    """客户咨询：访客身份绑定线程归属；隔离在服务端校验"""
    data = request.get_json() or {}
    message = (data.get('message') or '').strip()
    session_id = (data.get('session_id') or 'default').strip()
    if not message:
        return visitor_response({'error': '消息不能为空'}, 400)
    if session_id != 'default':
        vid = get_visitor_id()
        if not auth_store.visitor_owns_thread(session_id, vid):
            return visitor_response({'error': '会话不存在或无权访问'}, 403)
    ai_text, err_msg, http_code, tid = run_chat_sync(message, session_id if session_id != 'default' else None)
    if not tid:
        return visitor_response({'error': err_msg or '会话创建失败'}, http_code or 500)
    auth_store.bind_thread_owner(tid, get_visitor_id())
    app_logging.log("chat", "customer_message", thread_id=tid,
                    session_state=derive_service_state(tid),
                    message=app_logging.mask_pii(message), outcome=err_msg or "ok")
    if err_msg == 'run_timeout':
        # 超时降级：ai_text 已是转人工话术，工单已落库（handle_run_timeout）
        return visitor_response({'response': ai_text, 'session_id': tid, 'thread_id': tid,
                                 'service_state': 'waiting', 'timeout_handoff': True})
    if err_msg:
        return visitor_response({'error': err_msg}, http_code or 500)
    return visitor_response({
        'response': ai_text,
        'session_id': tid,
        'thread_id': tid,
        'service_state': derive_service_state(tid),
    })


@app.route('/api/customer/sessions', methods=['GET'])
def customer_sessions():
    """客户自己的会话列表（按访客归属过滤）"""
    vid = get_visitor_id()
    result = []
    for tid in auth_store.threads_of_visitor(vid):
        state_data, err = fetch_session_detail(tid)
        if err or not state_data:
            continue
        result.append({
            'session_id': tid,
            'last_message': (state_data.get('conversation_history') or [{}])[-1].get('content', '')[:80],
            'message_count': len(state_data.get('conversation_history') or []),
            'service_state': derive_service_state(tid),
        })
    return visitor_response({'sessions': result})


@app.route('/api/customer/session/<thread_id>', methods=['GET'])
def customer_session_detail(thread_id):
    """客户读取自己的会话（消息 + 服务状态）；无权访问返回 403"""
    if not auth_store.visitor_owns_thread(thread_id, get_visitor_id()):
        return visitor_response({'error': '会话不存在或无权访问'}, 403)
    state_data, err = fetch_session_detail(thread_id)
    if err or not state_data:
        return visitor_response({'error': '会话读取失败'}), 500
    return visitor_response({
        'session_id': thread_id,
        'conversation_history': state_data.get('conversation_history') or [],
        'service_state': derive_service_state(thread_id),
    })


@app.route('/api/chat', methods=['POST'])
@require_agent
def chat():
    """处理聊天请求（坐席调试用）"""
    try:
        data = request.get_json() or {}
        user_message = (data.get('message') or '').strip()
        client_session_id = data.get('session_id') or None
        threshold = data.get('quality_threshold')
        configurable = {'quality_threshold': threshold} if threshold is not None else None
        ai_text, err_msg, http_code, tid = run_chat_sync(user_message, client_session_id, configurable)
        if err_msg == 'run_timeout':
            return jsonify({'response': ai_text, 'session_id': tid, 'thread_id': tid,
                            'timeout_handoff': True})
        if err_msg:
            return jsonify({'error': err_msg}), http_code or 500
        return jsonify({'response': ai_text, 'session_id': tid, 'thread_id': tid})
    except Exception as e:
        print(f"❌ 聊天处理错误: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'内部错误: {str(e)}'}), 500


@app.route('/api/chat/stream', methods=['POST'])
@require_agent
def chat_stream():
    """处理流式聊天请求"""
    try:
        data = request.get_json()
        user_message = (data.get('message') or '').strip()
        client_session_id = data.get('session_id', 'default')

        return Response(
            stream_chat_events(user_message, client_session_id),
            mimetype='text/event-stream'
        )

    except Exception as e:
        print(f"❌ 流式聊天处理错误: {e}")
        return jsonify({'error': f'内部错误: {str(e)}'}), 500


@app.route('/api/sessions', methods=['GET'])
@require_agent
def get_sessions():
    """获取会话列表"""
    sessions, err = fetch_sessions_list()
    if err:
        return jsonify({'error': err}), 500
    return jsonify({'sessions': sessions or []})


@app.route('/api/sessions/<session_id>', methods=['GET'])
@require_agent
def get_session(session_id):
    """获取特定会话详情"""
    session_data, err = fetch_session_detail(session_id)
    if err:
        return jsonify({'error': err}), 500
    return jsonify({'session': session_data})


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
@require_agent
def delete_session(session_id):
    """删除会话"""
    try:
        ok, status = delete_remote_thread(session_id)
        if ok:
            if 'conversations' in session and session_id in session['conversations']:
                del session['conversations'][session_id]
            return jsonify({'message': '会话删除成功'})
        return jsonify({'error': f'删除会话失败: {status}'}), 500
    except Exception as e:
        return jsonify({'error': f'服务器错误: {str(e)}'}), 500


@app.route('/api/sessions/<session_id>/clear', methods=['POST'])
@require_agent
def clear_session(session_id):
    """清空会话"""
    try:
        new_thread_id, err = clear_thread_and_create_new(session_id)
        if err:
            return jsonify({'error': err}), 500

        if 'conversations' in session and session_id in session['conversations']:
            session['conversations'][session_id] = []

        return jsonify({
            'message': '会话清空成功',
            'new_thread_id': new_thread_id
        })
    except Exception as e:
        return jsonify({'error': f'服务器错误: {str(e)}'}), 500


@app.route('/api/new_session', methods=['POST'])
def create_new_session():
    """创建新会话（Flask session 侧）"""
    try:
        import uuid
        new_session_id = str(uuid.uuid4())
        session['current_session_id'] = new_session_id
        if 'conversations' not in session:
            session['conversations'] = {}
        session['conversations'][new_session_id] = []
        return jsonify({
            'session_id': new_session_id,
            'message': '新会话创建成功'
        })
    except Exception as e:
        return jsonify({'error': f'创建会话失败: {str(e)}'}), 500


@app.route('/api/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time()
    })


@app.route('/api/test')
def test_langgraph():
    """测试 LangGraph API 调用"""
    result, err = langgraph_connectivity_test()
    if err:
        return jsonify({'error': err}), 500
    return jsonify(result)


@app.route('/api/tickets', methods=['GET'])
@require_agent
def list_tickets_route():
    """人工工单队列"""
    status = request.args.get('status')
    if status not in ('open', 'resolved', None, ''):
        return jsonify({'error': 'status 仅支持 open/resolved'}), 400
    try:
        limit = min(int(request.args.get('limit', 200)), 500)
        offset = max(int(request.args.get('offset', 0)), 0)
        q = request.args.get('q', '')
        result = ticket_store.list_tickets(status or None, q=q, limit=limit, offset=offset)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'获取工单失败: {e}'}), 500


@app.route('/api/tickets/<ticket_id>', methods=['GET'])
@require_agent
def ticket_detail_route(ticket_id):
    """工单详情（含草稿回复与质检理由）"""
    try:
        ticket = ticket_store.get_ticket(ticket_id)
        if not ticket:
            return jsonify({'error': '工单不存在'}), 404
        return jsonify({'ticket': ticket})
    except Exception as e:
        return jsonify({'error': f'获取工单失败: {e}'}), 500


@app.route('/api/tickets/stream')
@require_agent
def ticket_stream_route():
    """SSE：工单队列变化推送（EventSource 断线自动重连）"""
    return Response(
        ticket_stream_events(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/api/tickets/<ticket_id>/resolve', methods=['POST'])
@require_agent
def resolve_ticket_route(ticket_id):
    """人工处理工单：写回会话并关闭工单；写回失败时降级为仅工单内可见"""
    try:
        data = request.get_json() or {}
        human_reply = (data.get('human_reply') or '').strip()
        if not human_reply:
            return jsonify({'error': 'human_reply 不能为空'}), 400

        ticket = ticket_store.get_ticket(ticket_id)
        if not ticket:
            return jsonify({'error': '工单不存在'}), 404
        if ticket['status'] != 'open':
            return jsonify({'error': f"工单状态为 {ticket['status']}，无法处理"}), 409

        ok, err = inject_human_reply(ticket['thread_id'], human_reply)
        ticket_store.resolve_ticket(ticket_id, human_reply)
        app_logging.log("ticket", "resolved", ticket_id=ticket_id,
                        thread_id=ticket['thread_id'], delivery="ok" if ok else "degraded")
        if not ok:
            return jsonify({
                'message': '工单已处理，但人工回复写回会话失败（仅工单内可见）',
                'degraded': True,
                'detail': err,
            })
        return jsonify({'message': '人工回复已写入会话，AI 恢复接管', 'degraded': False})
    except Exception as e:
        return jsonify({'error': f'处理工单失败: {e}'}), 500


def main():
    """主函数"""
    print("🚀 多智能体客服系统 Web 应用")
    print("=" * 60)
    print("🌐 启动 Web 服务...")
    print("📱 访问地址: http://localhost:5000")
    print("💡 按 Ctrl+C 停止服务")
    print()
    app.run(host='0.0.0.0', port=5000, debug=True)


if __name__ == "__main__":
    main()
