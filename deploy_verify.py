# -*- coding: utf-8 -*-
"""端到端部署验证：两轮真实对话（验证分类路由 + 多轮上下文）"""
import json
import requests

BASE = "http://127.0.0.1:5000"

def chat(message, session_id):
    r = requests.post(
        f"{BASE}/api/chat",
        json={"message": message, "session_id": session_id},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()

sid = "deploy-verify-final"

print("=" * 60)
print("第 1 轮（账单场景，应路由到 billing_agent）")
r1 = chat("我上周买的东西申请了退款，帮我查一下退款进度", sid)
print(json.dumps(r1, ensure_ascii=False, indent=2))

print("=" * 60)
print("第 2 轮（追问，验证多轮上下文：'它'指退款）")
r2 = chat("大概什么时候能到账？", sid)
print(json.dumps(r2, ensure_ascii=False, indent=2))
