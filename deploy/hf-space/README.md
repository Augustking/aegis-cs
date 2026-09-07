---
title: Aegis-CS 智能客服系统
emoji: 🛡️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: true
license: apache-2.0
short_description: 多智能体客服系统——AI 质检 + 人工接管闭环 + 坐席工作台
---

# Aegis-CS 在线 Demo

多智能体客服系统演示：

- **客户咨询**：Space 首页即客户咨询窗（路径 `/chat`）
- **坐席工作台**：路径 `/agent/login`，演示账号见下方说明

## 演示账号

| 用途 | 账号 | 密码 |
|---|---|---|
| 坐席登录 | `agent` | `aegis-demo` |

## 说明

- 本 Space 为公开演示，全部数据为演示数据；请勿输入真实个人信息
- 对话与工单数据存于容器内，Space 重启后重置
- 源码与架构说明：https://github.com/Augustking/aegis-cs
