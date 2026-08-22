# -*- coding: utf-8 -*-
"""LLM 适配层 — 对标 Cline @cline/llms gateway

每个 provider 实现 AgentModel 协议（stream 方法），
AgentRuntime 通过统一的 AgentModel 接口调用，不感知具体 provider。

当前实现:
    - QwenModel: 通义千问（DashScope OpenAI 兼容模式）
    - OpenAIModel: 通用 OpenAI 兼容 provider（OpenAI / DeepSeek / Moonshot / Zhipu 等）
    - create_model: 工厂函数，按 provider_id 创建对应模型
    - create_model_from_env: 从环境变量创建模型（推荐入口）
"""

from agent.providers.factory import (
    BUILTIN_PROVIDER_DEFAULTS,
    ProviderDefaults,
    create_model,
    create_model_from_env,
    get_provider_defaults,
    list_supported_providers,
)
from agent.providers.openai import OpenAIModel
from agent.providers.qwen import QwenModel

__all__ = [
    "QwenModel",
    "OpenAIModel",
    "create_model",
    "create_model_from_env",
    "get_provider_defaults",
    "list_supported_providers",
    "BUILTIN_PROVIDER_DEFAULTS",
    "ProviderDefaults",
]
