# -*- coding: utf-8 -*-
"""T3：分类护栏——创作/闲聊类请求的规则后校验 + 提示词 few-shot"""
from tools.query_tools import CLASSIFY_SYSTEM_PROMPT, enforce_scope_guard


def test_guard_sends_creation_requests_out_of_scope():
    """创作/闲聊类 + 无业务关键词 → 即使 LLM 误判 general 也强制 out_of_scope"""
    assert enforce_scope_guard("给我写一首关于爱情的诗", "general_inquiry") == "out_of_scope"
    assert enforce_scope_guard("帮我写一篇论文", "general_inquiry") == "out_of_scope"
    assert enforce_scope_guard("今天天气怎么样？推荐几部电影", "general_inquiry") == "out_of_scope"
    assert enforce_scope_guard("讲个笑话听听", "general_inquiry") == "out_of_scope"


def test_guard_never_touches_explicit_labels():
    """LLM 已给出非 general 标签时，规则不覆盖（保留业务/护栏判定）"""
    assert enforce_scope_guard("给我写一首诗", "out_of_scope") == "out_of_scope"
    assert enforce_scope_guard("退款什么时候到账", "billing") == "billing"


def test_guard_does_not_hurt_business_queries():
    """含业务关键词的查询不得被误判为 out_of_scope"""
    business = [
        "你们支持货到付款吗？偏远地区可以配送吗",
        "帮我查一下订单",
        "我的耳机坏了怎么修",
        "商品什么时候发货",
        "我要投诉你们的物流",
        "发票抬头能改吗",
    ]
    for q in business:
        assert enforce_scope_guard(q, "general_inquiry") == "general_inquiry", q


def test_classify_prompt_has_few_shot_examples():
    """提示词包含 out_of_scope 与配送类的 few-shot 示例"""
    assert "写一首" in CLASSIFY_SYSTEM_PROMPT
    assert "货到付款" in CLASSIFY_SYSTEM_PROMPT
