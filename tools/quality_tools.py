"""
回复质检工具：judge 提示词构建 + LLM 输出解析（纯函数，可单测）。
解析策略：直接 json.loads → 正则抽取带杂讯 JSON → 任意 0-10 整数兜底 → fail-open。
"""

import json
import re
from typing import Tuple

from langchain_core.messages import HumanMessage, SystemMessage

_JUDGE_SYSTEM_PROMPT = """你是客服回复质检员。请对"AI客服回复"严格打分（0-10 分，整数）。

评分维度（综合）：
1. 相关性：是否针对用户的最新问题（0-4 分）
2. 解答度：是否实际解答诉求，还是空泛敷衍（0-3 分）
3. 可信度：是否编造信息、与上下文矛盾、包含明显错误（0-3 分）

判定口径：
- 回答了问题但需要用户补充信息 → 7 分以上
- 空泛套话、答非所问、明显未理解问题 → 3 分以下
- 编造具体承诺（金额/时间/政策）→ 0-2 分

只输出 JSON：{"score": <0-10整数>, "reason": "<20字以内理由>"}，不要输出任何其他内容。"""


def build_judge_messages(query: str, response: str, context: str = "") -> list:
    user_content = f"用户最新问题：{query}\n\nAI客服回复：{response}"
    if context:
        user_content = f"对话历史上下文：\n{context}\n\n{user_content}"
    return [
        SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]


def _clamp(v: float) -> float:
    return max(0.0, min(10.0, v))


def _extract_reason(text: str) -> str:
    m = re.search(r'"reason"\s*[:：]\s*"([^"]{0,100})"', text)
    return m.group(1) if m else ""


def parse_judge_output(raw: object) -> Tuple[float, str]:
    """解析 judge 输出为 (score, reason)；任何失败按 fail-open 返回 (10.0, 'parse_failed')。"""
    if raw is None:
        return 10.0, "parse_failed"
    text = str(raw).strip()
    if not text:
        return 10.0, "parse_failed"
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "score" in data:
            return _clamp(float(data["score"])), str(data.get("reason", ""))[:100]
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    m = re.search(r'"score"\s*[:：]\s*(\d{1,2})', text)
    if m:
        return _clamp(float(m.group(1))), _extract_reason(text) or "parsed_from_noise"
    m = re.search(r"\b(\d{1,2})\b", text)
    if m:
        v = float(m.group(1))
        if 0 <= v <= 10:
            return v, "parsed_fallback"
    return 10.0, "parse_failed"
