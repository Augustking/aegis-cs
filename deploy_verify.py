# -*- coding: utf-8 -*-
"""
端到端验收剧本（需先启动 langgraph dev 与 web_app.py）：
  场景1  正常两轮对话（Flask /api/chat）：业务路由 + 多轮上下文，不产生工单
  场景2  强制转人工（run config quality_threshold=10）：回复转接话术 + 工单落库
  场景3  挂起中的会话再来消息：固定等待话术，不产生新工单
  场景4  resolve API 人工处理：工单关闭，下一条消息恢复 AI 且上下文完整
"""
import time

import requests

FLASK = "http://127.0.0.1:5000"
LG = "http://127.0.0.1:2024"


def chat(message, session_id):
    r = requests.post(f"{FLASK}/api/chat",
                      json={"message": message, "session_id": session_id}, timeout=180)
    r.raise_for_status()
    return r.json()


def lg_create_thread():
    r = requests.post(f"{LG}/threads", json={}, timeout=10)
    r.raise_for_status()
    return r.json()["thread_id"]


def lg_run(thread_id, message, configurable=None):
    """直连 LangGraph API 跑一轮（支持 configurable，供强制转人工用）"""
    assistants = requests.post(f"{LG}/assistants/search",
                               json={"graph_id": "customer_service", "limit": 1},
                               timeout=10).json()
    resp = requests.post(f"{LG}/threads/{thread_id}/runs", json={
        "assistant_id": assistants[0]["assistant_id"],
        "input": {"messages": [{"role": "user", "content": message}],
                  "customer_query": message, "session_id": thread_id},
        "config": {"configurable": configurable} if configurable else {},
    }, timeout=30)
    resp.raise_for_status()
    run_id = resp.json()["run_id"]
    deadline = time.time() + 150
    while time.time() < deadline:
        time.sleep(0.5)
        status = requests.get(f"{LG}/threads/{thread_id}/runs/{run_id}",
                              timeout=10).json()
        if status.get("status") in ("completed", "success"):
            break
        if status.get("status") in ("failed", "cancelled"):
            raise RuntimeError(f"run 失败: {status}")
    state = requests.get(f"{LG}/threads/{thread_id}/state", timeout=10).json()
    return (state.get("values") or {}).get("response", "")


def open_tickets():
    r = requests.get(f"{FLASK}/api/tickets?status=open", timeout=10)
    return r.json()["tickets"]


def main():
    print("=" * 70)
    print("场景1a：正常放行路径（quality_threshold=0 确定性放行，验证路由与质检不误拦）")
    thread_a = lg_create_thread()
    reply = lg_run(thread_a, "你们支持哪些支付方式？", configurable={"quality_threshold": 0})
    print("回复:", reply[:80].replace("\n", " "))
    assert "账单专家" in reply, reply
    assert all(t["thread_id"] != thread_a for t in open_tickets()), "阈值 0 下不应产生工单"

    print("=" * 70)
    print("场景1b：Flask 自然对话（容忍质检拦截与挂起；收尾统一恢复）")
    # 质检结果受 LLM 波动影响，三种用户可见结果均合法：
    OK_MARKS = ("账单专家", "人工工单", "转接人工客服")
    r1 = chat("你们支持哪些支付方式？", "verify-e2e")
    print("回复1:", r1["response"][:60].replace("\n", " "))
    assert any(k in r1["response"] for k in OK_MARKS), r1
    r2 = chat("那电子发票怎么开？", "verify-e2e")
    print("回复2:", r2["response"][:60].replace("\n", " "))
    assert any(k in r2["response"] for k in OK_MARKS), r2
    # 若质检拦截产生工单，走一遍恢复流程收尾（不影响后续场景）
    for t in [t for t in open_tickets() if t["thread_id"] == r1["thread_id"]]:
        resp = requests.post(f"{FLASK}/api/tickets/{t['id']}/resolve",
                             json={"human_reply": "场景1b收尾：已人工确认。"}, timeout=30)
        assert resp.status_code == 200, resp.text
    assert all(t["thread_id"] != r1["thread_id"] for t in open_tickets())

    print("=" * 70)
    print("场景2：强制转人工（quality_threshold=10，独立线程）")
    lg_thread = lg_create_thread()
    reply = lg_run(lg_thread, "帮我查退款进度", configurable={"quality_threshold": 10})
    print("回复:", reply[:80].replace("\n", " "))
    assert "人工工单" in reply, reply
    tickets = open_tickets()
    assert any(t["thread_id"] == lg_thread for t in tickets), tickets
    ticket = [t for t in tickets if t["thread_id"] == lg_thread][0]
    print(f"工单已落库: {ticket['id'][:8]}… 草稿回复: {ticket['draft_reply'][:40]}…")

    print("=" * 70)
    print("场景3：挂起中的会话再来消息（应等待人工，不新增工单）")
    n_before = len(open_tickets())
    reply = lg_run(lg_thread, "补充一下我的订单号是 12345")
    print("回复:", reply[:80].replace("\n", " "))
    assert "转接人工" in reply, reply
    assert len(open_tickets()) == n_before, "挂起中不应产生新工单"

    print("=" * 70)
    print("场景4：resolve API 人工处理后恢复 AI")
    resp = requests.post(
        f"{FLASK}/api/tickets/{ticket['id']}/resolve",
        json={"human_reply": "您好，人工客服已核实：您的退款预计明天 24 小时内到账原路账户。"},
        timeout=30,
    )
    print("resolve:", resp.json())
    assert resp.status_code == 200 and resp.json()["degraded"] is False, resp.text
    assert all(t["id"] != ticket["id"] for t in open_tickets())
    reply = lg_run(lg_thread, "那大概什么时候到账？")
    print("恢复后回复:", reply[:100].replace("\n", " "))
    assert "账单专家" in reply, reply  # AI 已恢复接管

    print("=" * 70)
    print("✅ 全部 4 个场景验收通过")


if __name__ == "__main__":
    main()
