# -*- coding: utf-8 -*-
"""
端到端验收剧本 v2（单服务架构，需先启动 web_app.py）：
  前置  坐席登录（/api/auth/login）
  场景1a 正常放行（quality_threshold=0 确定性放行）：路由 + 质检不误拦
  场景1b 客户轮询：会话详情可读、状态与服务端一致
  场景2  强制转人工（threshold=10）：转接话术 + 工单落库 + 客户状态 waiting
  场景3  挂起中再来消息：固定等待话术，不产生新工单
  场景4  坐席 resolve：工单关闭，客户侧读到人工回复（author=human）+ 状态 human
  隔离  客户 B 访问客户 A 的会话 → 403
"""
import json
import time
import uuid

import requests

FLASK = "http://127.0.0.1:5000"
AGENT = {"username": "agent", "password": "aegis-demo"}


def wait_flask(deadline=60):
    t0 = time.time()
    while time.time() - t0 < deadline:
        try:
            if requests.get(f"{FLASK}/api/test", timeout=5).status_code == 200:
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)
    raise RuntimeError("Flask 未就绪")


def main():
    wait_flask()

    print("=" * 70)
    print("前置：坐席登录")
    agent = requests.Session()
    r = agent.post(f"{FLASK}/api/auth/login", json=AGENT, timeout=15)
    assert r.status_code == 200, r.text
    print("登录:", r.json())

    print("=" * 70)
    print("场景1a：正常放行（坐席调试通道 quality_threshold=0，确定性放行）")
    r = agent.post(f"{FLASK}/api/chat",
                   json={"message": "你们支持哪些支付方式？", "quality_threshold": 0}, timeout=180)
    assert r.status_code == 200, r.text
    d = r.json()
    print("回复:", d["response"][:60].replace("\n", " "))
    assert "人工" not in d["response"], d  # 阈值 0 下不应转人工

    print("=" * 70)
    print("场景1b：客户自建线程咨询（质检结果受模型波动影响，两种结局均合法）+ 详情轮询")
    customer = requests.Session()  # 访客身份由服务端下发 cookie
    r = customer.post(f"{FLASK}/api/customer/chat",
                      json={"message": "你们支持哪些支付方式？"}, timeout=180)
    assert r.status_code == 200, r.text
    d = r.json()
    thread_a = d["thread_id"]
    print("回复:", d["response"][:50].replace("\n", " "), "| 状态:", d["service_state"])
    assert len(d["response"]) > 10, d
    assert d["service_state"] in ("normal", "waiting"), d
    r = customer.get(f"{FLASK}/api/customer/session/{thread_a}", timeout=30)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["service_state"] in ("normal", "waiting", "human")
    assert any(not m["is_user"] for m in detail["conversation_history"])
    # 若被质检拦截转人工，先走 resolve 收尾，保证后续场景干净
    for t in [t for t in agent.get(f"{FLASK}/api/tickets?status=open", timeout=15).json()["items"]
              if t["thread_id"] == thread_a]:
        rr = agent.post(f"{FLASK}/api/tickets/{t['id']}/resolve",
                        json={"human_reply": "场景1b收尾：已人工确认。"}, timeout=60)
        assert rr.status_code == 200, rr.text

    print("=" * 70)
    print("场景2：强制转人工（quality_threshold=10）")
    r = agent.post(f"{FLASK}/api/chat",
                   json={"message": "帮我查退款进度", "session_id": thread_a,
                         "quality_threshold": 10}, timeout=180)
    assert r.status_code == 200, r.text
    d = r.json()
    reply = d.get("response") or ""
    print("回复:", reply[:60].replace("\n", " "))
    assert "人工" in reply, d
    r = customer.get(f"{FLASK}/api/customer/session/{thread_a}", timeout=30)
    assert r.json()["service_state"] == "waiting", r.text[:200]

    print("=" * 70)
    print("场景3：挂起中再来消息（固定等待话术，不新增工单）")
    tickets_before = agent.get(f"{FLASK}/api/tickets?status=open", timeout=15).json()["total"]
    r = customer.post(f"{FLASK}/api/customer/chat",
                      json={"message": "补充一下我的订单号是 12345", "session_id": thread_a}, timeout=60)
    assert r.status_code == 200, r.text
    reply = r.json()["response"]
    print("回复:", reply[:60].replace("\n", " "))
    assert "转接人工" in reply or "转人工" in reply, r.text[:200]
    tickets_after = agent.get(f"{FLASK}/api/tickets?status=open", timeout=15).json()["total"]
    assert tickets_after == tickets_before, "挂起中不应产生新工单"

    print("=" * 70)
    print("场景4：坐席 resolve → 客户自动收到人工回复")
    open_list = agent.get(f"{FLASK}/api/tickets?status=open", timeout=15).json()["items"]
    ticket = [t for t in open_list if t["thread_id"] == thread_a][0]
    human_reply = "您好，人工客服已核实：您的退款预计明天 24 小时内到账原路账户。"
    r = agent.post(f"{FLASK}/api/tickets/{ticket['id']}/resolve",
                   json={"human_reply": human_reply}, timeout=60)
    assert r.status_code == 200 and r.json().get("degraded") is False, r.text
    r = customer.get(f"{FLASK}/api/customer/session/{thread_a}", timeout=30)
    d = r.json()
    assert d["service_state"] == "human", d.get("service_state")
    last = d["conversation_history"][-1]
    assert last.get("author") == "human" and "24 小时内" in last["content"], last
    print("客户侧最后一条:", f"[{last.get('author')}] {last['content'][:50]}")

    print("=" * 70)
    print("隔离：客户 B 访问客户 A 的会话 → 403")
    intruder = requests.Session()
    r = intruder.get(f"{FLASK}/api/customer/session/{thread_a}", timeout=15)
    assert r.status_code == 403, r.status_code
    print("403 OK")

    print("=" * 70)
    print("✅ 全部场景验收通过")


if __name__ == "__main__":
    main()
