# -*- coding: utf-8 -*-
"""T6：分类走轻量模型（CLASSIFY_MODEL 可配），应答/质检走主模型"""
import pytest

import multi_agent_customer_service as svc


@pytest.fixture()
def reset_llm_cache(monkeypatch):
    monkeypatch.setattr(svc, "_classify_llm_instance", None)


def test_classify_llm_uses_env_model(monkeypatch, reset_llm_cache):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(svc, "CLASSIFY_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    client = svc.get_classify_llm()
    assert client.model == "Qwen/Qwen2.5-7B-Instruct"
    assert svc.get_classify_llm() is client  # 缓存复用


def test_classify_llm_defaults_to_main_model(monkeypatch, reset_llm_cache):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(svc, "CLASSIFY_MODEL", "")
    client = svc.get_classify_llm()
    assert client.model == svc.OPENAI_MODEL
