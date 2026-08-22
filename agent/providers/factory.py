# -*- coding: utf-8 -*-
"""Provider 工厂 — 对标 Cline handler-factory.ts + provider-defaults.ts

按 provider_id 创建对应的 AgentModel 实例。内置常见 OpenAI 兼容 provider 的
默认配置（base_url、推荐模型、能力），用户也可显式覆盖。

支持的内置 provider:
    - qwen: 阿里通义千问（DashScope OpenAI 兼容模式）
    - openai: OpenAI 官方
    - openai-native: OpenAI 官方（用于 model-tool-routing 触发 apply_patch）
    - deepseek: 深度求索
    - moonshot: 月之暗面 Kimi
    - zhipu: 智谱 GLM
    - openai-compatible: 通用 OpenAI 兼容（自定义 base_url）

用法:
    from agent.providers.factory import create_model
    model = create_model(
        provider_id="deepseek",
        model_id="deepseek-chat",
        api_key="sk-...",
    )

对标 Cline:
    - sdk/packages/core/src/services/llms/handler-factory.ts createAgentModelFromConfig
    - sdk/packages/core/src/services/llms/provider-defaults.ts BUILTIN_PROVIDER_MANIFESTS
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from agent.types import AgentModel
from agent.providers.errors import (
    ProviderAuthError,
    ProviderInvalidRequestError,
)


# ============================================================================
# Stage 7.8 (R5): Provider 能力常量 — 对标 Cline ProviderCapability
# ============================================================================


class ProviderCapability:
    """Provider 能力常量 — 对标 Cline ProviderCapability

    Stage 7.8 新增。Cline 有三层 capabilities 体系（ProviderCapability /
    GatewayModelCapability / catalog capability），本仓库仅引入一层常量类，
    避免过度设计。常量字符串与 Cline 保持一致，便于未来跨工具互操作。

    能力常量:
        - REASONING: 支持推理（reasoning_content / thinking 字段）
        - PROMPT_CACHE: 支持 prompt cache（可减少重复请求 token）
        - STREAMING: 支持流式输出
        - TOOLS: 支持工具调用（function calling）
        - IMAGES: 支持图片输入
        - VISION: 支持视觉理解（图标/OCR/截图）
        - STRUCTURED_OUTPUT: 支持结构化输出（response_format=json_schema）
    """
    REASONING = "reasoning"
    PROMPT_CACHE = "prompt-cache"
    STREAMING = "streaming"
    TOOLS = "tools"
    IMAGES = "images"
    VISION = "vision"
    STRUCTURED_OUTPUT = "structured-output"


@dataclass
class ProviderDefaults:
    """内置 provider 默认配置 — 对标 Cline BuiltInProviderManifest

    Attributes:
        provider_id: provider 标识
        base_url: API 端点
        default_model_id: 推荐的默认模型 ID
        supports_reasoning: 是否解析 reasoning_content 字段（向后兼容字段，
                            Stage 7.8 后由 capabilities 派生）
        env_key: 默认 API Key 环境变量名
        capabilities: provider 能力列表（Stage 7.8 新增，对标 Cline capabilities）
    """
    provider_id: str
    base_url: str
    default_model_id: str
    supports_reasoning: bool = True
    env_key: str = "OPENAI_API_KEY"
    # Stage 7.8 新增：capabilities 字段 — 对标 Cline BuiltInProviderManifest.capabilities
    capabilities: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Stage 7.8: supports_reasoning 与 capabilities 双向同步

        - 若 supports_reasoning=True 且 capabilities 不含 REASONING，自动追加
        - 若 supports_reasoning=False 且 capabilities 含 REASONING，自动移除
        这样旧调用方传 supports_reasoning=True 仍能自动获得 capabilities=["reasoning"]
        """
        if self.supports_reasoning and ProviderCapability.REASONING not in self.capabilities:
            self.capabilities.append(ProviderCapability.REASONING)
        elif not self.supports_reasoning and ProviderCapability.REASONING in self.capabilities:
            self.capabilities.remove(ProviderCapability.REASONING)


# 内置 provider 默认配置表 — 对标 Cline BUILTIN_PROVIDER_MANIFESTS
# Stage 7.8: 每个 provider 增加 capabilities 字段
BUILTIN_PROVIDER_DEFAULTS: dict[str, ProviderDefaults] = {
    "qwen": ProviderDefaults(
        provider_id="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model_id="qwen-plus",
        supports_reasoning=True,
        env_key="DASHSCOPE_API_KEY",
        # DashScope 支持 reasoning_content、工具调用、流式输出
        capabilities=[ProviderCapability.REASONING, ProviderCapability.TOOLS, ProviderCapability.STREAMING],
    ),
    "openai": ProviderDefaults(
        provider_id="openai",
        base_url="",  # 空字符串表示使用 openai SDK 默认端点
        default_model_id="gpt-4o",
        supports_reasoning=True,
        env_key="OPENAI_API_KEY",
        # GPT-4o 完整能力
        capabilities=[
            ProviderCapability.REASONING,
            ProviderCapability.TOOLS,
            ProviderCapability.STREAMING,
            ProviderCapability.VISION,
            ProviderCapability.STRUCTURED_OUTPUT,
            ProviderCapability.PROMPT_CACHE,
        ],
    ),
    "openai-native": ProviderDefaults(
        provider_id="openai-native",
        base_url="",
        default_model_id="gpt-4o",
        supports_reasoning=True,
        env_key="OPENAI_API_KEY",
        capabilities=[
            ProviderCapability.REASONING,
            ProviderCapability.TOOLS,
            ProviderCapability.STREAMING,
            ProviderCapability.VISION,
            ProviderCapability.STRUCTURED_OUTPUT,
            ProviderCapability.PROMPT_CACHE,
        ],
    ),
    "deepseek": ProviderDefaults(
        provider_id="deepseek",
        base_url="https://api.deepseek.com/v1",
        default_model_id="deepseek-chat",
        supports_reasoning=True,
        env_key="DEEPSEEK_API_KEY",
        # DeepSeek-R1 支持 reasoning_content
        capabilities=[ProviderCapability.REASONING, ProviderCapability.TOOLS, ProviderCapability.STREAMING],
    ),
    "moonshot": ProviderDefaults(
        provider_id="moonshot",
        base_url="https://api.moonshot.cn/v1",
        default_model_id="moonshot-v1-8k",
        supports_reasoning=False,
        env_key="MOONSHOT_API_KEY",
        # Kimi 不支持 reasoning_content
        capabilities=[ProviderCapability.TOOLS, ProviderCapability.STREAMING],
    ),
    "zhipu": ProviderDefaults(
        provider_id="zhipu",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model_id="glm-4-plus",
        supports_reasoning=False,
        env_key="ZHIPU_API_KEY",
        # GLM-4 不支持 reasoning_content
        capabilities=[ProviderCapability.TOOLS, ProviderCapability.STREAMING],
    ),
    "openai-compatible": ProviderDefaults(
        provider_id="openai-compatible",
        base_url="",  # 必须显式提供
        default_model_id="",
        supports_reasoning=True,
        env_key="OPENAI_API_KEY",
        # 保守默认，调用方可通过 capabilities 选项覆盖
        capabilities=[ProviderCapability.REASONING, ProviderCapability.TOOLS, ProviderCapability.STREAMING],
    ),
}


def get_provider_defaults(provider_id: str) -> ProviderDefaults | None:
    """查询内置 provider 默认配置 — 对标 Cline getProviderConfig"""
    return BUILTIN_PROVIDER_DEFAULTS.get(provider_id)


def list_supported_providers() -> list[str]:
    """列出所有支持的 provider ID"""
    return list(BUILTIN_PROVIDER_DEFAULTS.keys())


def create_model(
    provider_id: str,
    model_id: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    **options: Any,
) -> AgentModel:
    """按 provider_id 创建 AgentModel 实例 — 对标 Cline createAgentModelFromConfig

    Args:
        provider_id: provider 标识（如 "qwen" / "openai" / "deepseek"）
        model_id: 模型名称，None 时使用 provider 默认模型
        api_key: API Key，None 时从 provider 对应的默认环境变量读取
        base_url: API 端点，None 时使用 provider 默认端点
        **options: 其他模型选项（max_tokens / temperature / idle_timeout 等）

    Returns:
        实现 AgentModel 协议的实例

    Raises:
        ProviderInvalidRequestError: provider_id 未知或必要参数缺失
        ProviderAuthError: API Key 未设置
    """
    defaults = BUILTIN_PROVIDER_DEFAULTS.get(provider_id)
    if defaults is None:
        raise ProviderInvalidRequestError(
            f"未知 provider: {provider_id}。"
            f"支持的 provider: {list(BUILTIN_PROVIDER_DEFAULTS.keys())}",
            provider_id=provider_id,
        )

    # 解析最终参数（显式参数 > 环境变量 > provider 默认值）
    final_model = model_id or defaults.default_model_id
    if not final_model:
        raise ProviderInvalidRequestError(
            f"provider {provider_id} 未配置默认模型，请通过 model_id 参数指定",
            provider_id=provider_id,
        )

    final_api_key = api_key or os.environ.get(defaults.env_key, "")
    if not final_api_key:
        raise ProviderAuthError(
            f"API Key 未设置。请通过 api_key 参数传入或设置 {defaults.env_key} 环境变量。",
            provider_id=provider_id,
        )

    final_base_url = base_url or defaults.base_url or None

    # 通用选项默认值
    max_tokens = options.pop("max_tokens", 8192)
    temperature = options.pop("temperature", 0.1)
    idle_timeout = options.pop("idle_timeout", 120)
    supports_reasoning = options.pop("supports_reasoning", defaults.supports_reasoning)
    # Stage 7.8: 提取 capabilities 选项 — 默认使用 provider 默认能力
    capabilities = options.pop("capabilities", list(defaults.capabilities))

    # Qwen 走专用适配器（保持向后兼容，DashScope 的 reasoning_content 字段处理已验证）
    if provider_id == "qwen":
        from agent.providers.qwen import QwenModel
        return QwenModel(
            model=final_model,
            api_key=final_api_key,
            base_url=final_base_url,
            max_tokens=max_tokens,
            temperature=temperature,
            idle_timeout=idle_timeout,
            capabilities=capabilities,
        )

    # 其他 OpenAI 兼容 provider 走通用适配器
    from agent.providers.openai import OpenAIModel
    return OpenAIModel(
        model=final_model,
        api_key=final_api_key,
        base_url=final_base_url,
        max_tokens=max_tokens,
        temperature=temperature,
        idle_timeout=idle_timeout,
        provider_id=provider_id,
        supports_reasoning=supports_reasoning,
        capabilities=capabilities,
    )


def create_model_from_env() -> AgentModel:
    """从环境变量创建模型 — Phase 32.2 新增

    读取的环境变量:
        AGENT_PROVIDER_ID: provider 标识，默认 "qwen"
        AGENT_MODEL_NAME: 模型名称，默认使用 provider 的默认模型
        AGENT_MODEL_API_KEY: API Key，默认回退到 provider 对应的环境变量
        AGENT_MODEL_BASE_URL: API 端点，默认使用 provider 默认端点
        AGENT_MODEL_MAX_TOKENS: 最大输出 token 数，默认 8192
        AGENT_MODEL_TEMPERATURE: 采样温度，默认 0.1

    Returns:
        AgentModel 实例
    """
    provider_id = os.environ.get("AGENT_PROVIDER_ID", "qwen")
    model_id = os.environ.get("AGENT_MODEL_NAME") or None
    api_key = os.environ.get("AGENT_MODEL_API_KEY") or None
    base_url = os.environ.get("AGENT_MODEL_BASE_URL") or None

    options: dict[str, Any] = {}
    max_tokens_env = os.environ.get("AGENT_MODEL_MAX_TOKENS")
    if max_tokens_env:
        try:
            options["max_tokens"] = int(max_tokens_env)
        except ValueError:
            pass
    temperature_env = os.environ.get("AGENT_MODEL_TEMPERATURE")
    if temperature_env:
        try:
            options["temperature"] = float(temperature_env)
        except ValueError:
            pass

    return create_model(
        provider_id=provider_id,
        model_id=model_id,
        api_key=api_key,
        base_url=base_url,
        **options,
    )


def create_model_from_config(config) -> AgentModel:
    """从 ProviderConfig 创建模型 — Stage 13.2 扩展

    用于前端根据 alias 选择 Provider 配置后，按该配置创建模型实例。
    config 中显式配置的字段优先级最高，未配置的字段回退到 provider 默认值或环境变量。

    Args:
        config: ProviderConfig 实例（含 alias / provider_id / model_id / base_url / api_key 等）

    Returns:
        AgentModel 实例
    """
    options: dict[str, Any] = {}
    if config.temperature is not None:
        options["temperature"] = config.temperature
    if config.max_tokens is not None:
        options["max_tokens"] = config.max_tokens

    # 未显式配置 model_id / base_url / api_key 时传 None，让 create_model 回退到默认值/环境变量
    return create_model(
        provider_id=config.provider_id,
        model_id=config.model_id or None,
        api_key=config.api_key or None,
        base_url=config.base_url or None,
        **options,
    )
