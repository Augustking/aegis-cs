"""
回复质检工具：judge 提示词构建 + LLM 输出解析（纯函数，可单测）。
解析策略：直接 json.loads → 正则抽取带杂讯 JSON → 任意 0-10 整数兜底 → fail-open。
"""

import json
import re
from typing import Dict, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

_JUDGE_SYSTEM_PROMPT = """你是客服回复质检员。请从三个维度对"AI客服回复"严格打分。

维度定义：
1. relevance（相关性）：是否针对用户的最新问题（0-4 分）
2. completeness（解答度）：是否实际解答诉求，还是空泛敷衍（0-3 分）
3. faithfulness（可信度）：回复中的具体数字、时间、金额、政策条款是否与"业务数据证据"一致（0-3 分）

faithfulness 判定规则（最重要）：
- 业务数据证据中没有依据的具体承诺（到账时间、库存、订单状态等）→ faithfulness 计 0 分
- 回复明确表示"需要人工核实"、未给出无依据的具体信息 → faithfulness 计 3 分
- 引用证据中的政策/流程，且与证据一致 → faithfulness 计 3 分

relevance/completeness 判定口径：
- 回答了问题但需要用户补充信息 → completeness 至少 2 分
- 空泛套话、答非所问、明显未理解问题 → 各维度合计不超过 3 分

只输出一行，格式如下（不要 JSON、不要换行、不要输出总分）：
relevance=<0-4整数>; completeness=<0-3整数>; faithfulness=<0-3整数>; reason=<20字以内理由>"""


def build_judge_messages(query: str, response: str, context: str = "", evidence: str = "") -> list:
    """构建 judge 消息；evidence 为业务 Agent 检索到的数据上下文（接地质检的关键输入）。"""
    user_content = f"用户最新问题：{query}\n\nAI客服回复：{response}"
    if evidence:
        user_content += f"\n\n业务数据证据（faithfulness 必须对照此证据判定）：\n{evidence}"
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


def _clean_reason(val: str) -> str:
    """清洗 reason 捕获：去引号，JSON 场景在闭引号处截断。"""
    val = val.strip().strip('"')
    if '"' in val:
        val = val.split('"')[0]
    return val


def parse_judge_output(raw: object) -> Tuple[float, str]:
    """解析 judge 输出为 (score, reason)。总分 = 三维子分相加（0-4+0-3+0-3），
    维度解析失败再退回历史 score 字段，全部失败按 fail-open 返回 (10.0, 'parse_failed')。"""
    if raw is None:
        return 10.0, "parse_failed"
    text = str(raw).strip()
    if not text:
        return 10.0, "parse_failed"
    # 首选：维度分相加合成总分（7B 模型逐维度打分可靠，自合成总分不可靠）
    dims = parse_judge_dims(text)
    if dims is not None:
        reason_m = re.search(r'reason"?\s*[:=]\s*"?([^;\n]{0,100})', text, re.IGNORECASE)
        reason = _clean_reason(reason_m.group(1)) if reason_m else "dims_parsed"
        total = sum(dims.values())
        return _clamp(total), reason
    # 兼容历史格式：JSON score / 扁平 score 字段
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "score" in data:
            return _clamp(float(data["score"])), str(data.get("reason", ""))[:100]
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    m = re.search(r'"?score"?\s*[:=]\s*(\d{1,2})', text, re.IGNORECASE)
    if m:
        reason_m = re.search(r'reason"?\s*[:=]\s*"?([^;\n]{0,100})', text, re.IGNORECASE)
        reason = _clean_reason(reason_m.group(1)) if reason_m else "score_field_only"
        return _clamp(float(m.group(1))), reason
    m = re.search(r"\b(\d{1,2})\b", text)
    if m:
        v = float(m.group(1))
        if 0 <= v <= 10:
            return v, "parsed_fallback"
    return 10.0, "parse_failed"


# 维度分的合法区间（与 judge 提示词口径一致）
_DIM_RANGES = {"relevance": (0.0, 4.0), "completeness": (0.0, 3.0), "faithfulness": (0.0, 3.0)}


def parse_judge_dims(raw: object) -> Optional[Dict[str, float]]:
    """解析维度分；支持扁平 key=value 与 JSON 两种格式，缺失或非法返回 None。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    dims: Dict[str, float] = {}
    ok = True
    for name, (lo, hi) in _DIM_RANGES.items():
        m = re.search(name + r'\s*[:=]\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
        if not m:
            ok = False
            break
        dims[name] = max(lo, min(hi, float(m.group(1))))
    if ok:
        return dims
    # JSON 兼容（旧版本）
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("dims"), dict):
        return None
    dims = {}
    for name, (lo, hi) in _DIM_RANGES.items():
        try:
            v = float(data["dims"][name])
        except (KeyError, TypeError, ValueError):
            return None
        dims[name] = max(lo, min(hi, v))
    return dims
