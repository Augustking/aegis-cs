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

from flask import Flask, render_template, request, jsonify, session, Response

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
import ticket_store

# 导入配置（与历史行为保持一致）
from config import *  # noqa: E402,F401,F403

app = Flask(__name__)

# Flask 配置
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your-secret-key-here")
app.config['SESSION_TYPE'] = 'filesystem'


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
    """主页"""
    current_session_id = session.get('current_session_id', 'default')
    conversation_history = get_conversation_history(current_session_id)
    return render_template('index.html', conversation_history=conversation_history)


@app.route('/api/chat', methods=['POST'])
def chat():
    """处理聊天请求"""
    try:
        data = request.get_json()
        user_message = (data.get('message') or '').strip()
        client_session_id = data.get('session_id', 'default')

        ai_text, err_msg, http_code = run_chat_sync(user_message, client_session_id)
        if err_msg:
            return jsonify({'error': err_msg}), http_code or 500

        tid = get_current_thread_id()
        return jsonify({
            'response': ai_text,
            'session_id': tid,
            'thread_id': tid,
        })
    except Exception as e:
        print(f"❌ 聊天处理错误: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'内部错误: {str(e)}'}), 500


@app.route('/api/chat/stream', methods=['POST'])
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
def get_sessions():
    """获取会话列表"""
    sessions, err = fetch_sessions_list()
    if err:
        return jsonify({'error': err}), 500
    return jsonify({'sessions': sessions or []})


@app.route('/api/sessions/<session_id>', methods=['GET'])
def get_session(session_id):
    """获取特定会话详情"""
    session_data, err = fetch_session_detail(session_id)
    if err:
        return jsonify({'error': err}), 500
    return jsonify({'session': session_data})


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
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
def list_tickets_route():
    """人工工单队列"""
    status = request.args.get('status')
    if status not in ('open', 'resolved', None, ''):
        return jsonify({'error': 'status 仅支持 open/resolved'}), 400
    try:
        tickets = ticket_store.list_tickets(status or None)
        return jsonify({'tickets': tickets})
    except Exception as e:
        return jsonify({'error': f'获取工单失败: {e}'}), 500


@app.route('/api/tickets/<ticket_id>', methods=['GET'])
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
def ticket_stream_route():
    """SSE：工单队列变化推送（EventSource 断线自动重连）"""
    return Response(
        ticket_stream_events(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/api/tickets/<ticket_id>/resolve', methods=['POST'])
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
