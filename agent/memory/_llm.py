# -*- coding: utf-8 -*-
"""Memory 专用 LLM 助手 — 为召回/抽取提供 DeepSeek V4 Flash 模型

独立于主 agent 模型，使用更小/更便宜的模型做记忆抽取与召回选择，
避免占用主模型成本与上下文。

配置（环境变量，显式参数优先，其次内置默认）:
    MEMORY_PROVIDER_ID   provider 标识，默认 deepseek
    MEMORY_MODEL_NAME    模型名称，默认 deepseek-v4-flash
    MEMORY_API_KEY       API Key，默认回退到主 agent 的 AGENT_MODEL_API_KEY
    MEMORY_BASE_URL      API 端点，默认回退到主 agent 的 AGENT_MODEL_BASE_URL

用法:
    from agent.memory._llm import create_memory_model, complete_text
    model = create_memory_model()
    text = await complete_text(model, system_prompt, user_prompt, max_tokens=256)
"""

from __future__ import annotations

import logging
import os

from agent.providers.factory import create_model
from agent.types import (
    AgentMessage,
    AgentModelRequest,
    MessageRole,
    TextPart,
)

logger = logging.getLogger(__name__)


def create_memory_model() -> object:
    """创建 memory 专用模型（DeepSeek V4 Flash）

    配置解析优先级：MEMORY_* 显式变量 > 内置默认（deepseek / deepseek-v4-flash）。
    注意：provider 与 model 固定默认 DeepSeek V4 Flash（用户明确指定的记忆模型），
    不随主 agent 的 provider/model 变化；API Key/BaseURL 缺失时回退到主 agent 的
    AGENT_MODEL_API_KEY / AGENT_MODEL_BASE_URL，便于主 agent 即 DeepSeek 时开箱即用。

    Returns:
        实现 AgentModel 协议的实例（QwenModel 或 OpenAIModel）

    Raises:
        ProviderError: 模型创建失败（如 API Key 未配置）
    """
    provider_id = os.environ.get("MEMORY_PROVIDER_ID") or "deepseek"
    model_id = os.environ.get("MEMORY_MODEL_NAME") or "deepseek-v4-flash"
    api_key = os.environ.get("MEMORY_API_KEY") or os.environ.get("AGENT_MODEL_API_KEY")
    base_url = os.environ.get("MEMORY_BASE_URL") or os.environ.get("AGENT_MODEL_BASE_URL")

    return create_model(
        provider_id=provider_id,
        model_id=model_id,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        max_tokens=1024,
    )


async def complete_text(
    model: object,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 256,
) -> str:
    """调用模型完成一段文本生成（非工具，收集 text-delta）— 对齐 memory 子调用

    Args:
        model: create_memory_model() 返回的模型实例
        system_prompt: 系统提示词
        user_prompt: 用户输入
        max_tokens: 最大输出 token 数

    Returns:
        生成的文本；失败返回空字符串（不抛错，best-effort）
    """
    request = AgentModelRequest(
        system_prompt=system_prompt,
        messages=[
            AgentMessage(
                role=MessageRole.USER,
                content=[TextPart(text=user_prompt)],
            )
        ],
        tools=[],
        options={"max_tokens": max_tokens},
    )

    parts: list[str] = []
    try:
        async for event in model.stream(request):
            if event.type == "text-delta" and event.text:
                parts.append(event.text)
    except Exception as e:
        logger.warning("memory_llm: 文本生成失败: %s", e)
        return ""
    return "".join(parts)