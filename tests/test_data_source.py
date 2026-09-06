# -*- coding: utf-8 -*-
"""T1：业务数据访问层 + 反编造约束"""
import pytest

from multi_agents import (
    BillingAgent, ComplaintAgent, GeneralAgent, ProductAgent, TechAgent,
)
from services.business_data import BUSINESS_DATA, DATA_SOURCE, get_business_data

AGENT_ATTRS = [
    (ProductAgent, "product_database", "product"),
    (TechAgent, "tech_database", "tech"),
    (BillingAgent, "billing_database", "billing"),
    (ComplaintAgent, "complaint_database", "complaint"),
    (GeneralAgent, "service_database", "general"),
]


def test_central_source_has_all_domains():
    assert set(BUSINESS_DATA.keys()) == {"product", "tech", "billing", "complaint", "general"}
    assert DATA_SOURCE == "mock"
    for key, data in BUSINESS_DATA.items():
        assert isinstance(data, dict) and data, f"{key} 数据为空"


def test_get_business_data_and_unknown_key():
    assert get_business_data("billing") == BUSINESS_DATA["billing"]
    with pytest.raises(KeyError):
        get_business_data("no_such_domain")


def test_agents_use_central_data():
    for cls, attr, key in AGENT_ATTRS:
        agent = cls()
        assert getattr(agent, attr) == BUSINESS_DATA[key], f"{cls.__name__} 未接入数据层"


def test_base_prompt_carries_anti_fabrication_constraint():
    """所有 Agent 的系统提示必须包含反编造硬约束"""
    agent = BillingAgent()
    prompt = agent._enhance_system_prompt_with_context("你是账单专家。")
    assert "人工核实" in prompt
    assert "严禁编造" in prompt
    # 数据来源标记注入
    assert DATA_SOURCE in prompt


def test_match_info_still_works_after_migration():
    """迁移后匹配逻辑不受影响"""
    agent = BillingAgent()
    out = agent._match_billing_info("你们支持哪些支付方式")
    assert "支付方式" in out or "在线支付" in out
