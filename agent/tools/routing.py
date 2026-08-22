# -*- coding: utf-8 -*-
"""模型工具路由 — 对标 Cline model-tool-routing.ts

按 provider_id / model_id / mode 动态启用或禁用工具，适配不同模型的工具支持能力。

典型场景:
    1. OpenAI 原生模型（gpt-4o / gpt-5）在 act 模式下用 apply_patch 替代 editor
       （apply_patch 是 OpenAI 原生 function calling 的优化路径）
    2. codex / gpt 系列模型在 act 模式下禁用 editor，统一用 apply_patch
    3. 某些模型不支持 ask_question / submit_and_exit，可通过规则禁用

设计要点:
    - 规则按顺序应用，后匹配的规则覆盖先匹配的（同工具名以最后一次为准）
    - 规则匹配条件: mode + provider_id 子串 + model_id 子串（大小写不敏感）
    - 未提供 rules 时返回空 dict，不修改任何工具开关
    - 应用层（runtime.get_tools）根据返回的开关字典过滤工具列表

对标 Cline:
    - sdk/packages/core/src/extensions/tools/model-tool-routing.ts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# 工具名 → 配置开关字段名的映射（对标 Cline TOOL_NAME_TO_FLAG）
# 在 Cline 中工具开关由 DefaultToolsConfig 的 enable* 字段控制，
# 这里直接用工具名作为 key，不需要再映射到字段名。
ToolName = str
Mode = Literal["act", "plan"]


@dataclass
class ToolRoutingRule:
    """工具路由规则 — 对标 Cline ToolRoutingRule

    Attributes:
        name: 规则标签，仅用于调试和日志
        mode: 规则适用的模式（"act" / "plan" / "any"），默认 "any"
        model_id_includes: 模型 ID 子串匹配列表（大小写不敏感），
                          空列表或 None 表示不限制
        provider_id_includes: provider ID 子串匹配列表（大小写不敏感），
                             空列表或 None 表示不限制
        enable_tools: 命中规则时启用的工具名列表
        disable_tools: 命中规则时禁用的工具名列表
    """
    name: str = ""
    mode: Mode | Literal["any"] = "any"
    model_id_includes: list[str] = field(default_factory=list)
    provider_id_includes: list[str] = field(default_factory=list)
    enable_tools: list[ToolName] = field(default_factory=list)
    disable_tools: list[ToolName] = field(default_factory=list)


# 默认路由规则 — 对标 Cline DEFAULT_MODEL_TOOL_ROUTING_RULES
# 1. openai-native provider 在 act 模式下用 apply_patch 替代 editor
# 2. codex / gpt 系列模型在 act 模式下用 apply_patch 替代 editor
DEFAULT_MODEL_TOOL_ROUTING_RULES: list[ToolRoutingRule] = [
    ToolRoutingRule(
        name="openai-native-use-apply-patch",
        mode="act",
        provider_id_includes=["openai-native"],
        enable_tools=["apply_patch"],
        disable_tools=["editor"],
    ),
    ToolRoutingRule(
        name="codex-and-gpt-use-apply-patch",
        mode="act",
        model_id_includes=["codex", "gpt"],
        enable_tools=["apply_patch"],
        disable_tools=["editor"],
    ),
]


def _matches_id(value: str, includes: list[str] | None) -> bool:
    """子串匹配（大小写不敏感）— 对标 Cline matchesModelId

    Args:
        value: 待匹配的字符串（provider_id 或 model_id）
        includes: 子串列表，空列表或 None 表示不限制（始终匹配）

    Returns:
        是否匹配
    """
    if not includes:
        return True
    normalized = value.lower()
    return any(token.lower() in normalized for token in includes)


def _matches_rule(
    rule: ToolRoutingRule,
    provider_id: str,
    model_id: str,
    mode: Mode,
) -> bool:
    """判断规则是否命中 — 对标 Cline matchesRule"""
    if rule.mode and rule.mode != "any" and rule.mode != mode:
        return False
    return (
        _matches_id(provider_id, rule.provider_id_includes)
        and _matches_id(model_id, rule.model_id_includes)
    )


def resolve_tool_routing(
    provider_id: str,
    model_id: str,
    mode: Mode,
    rules: list[ToolRoutingRule] | None,
) -> dict[ToolName, bool]:
    """解析路由规则，返回工具开关字典 — 对标 Cline resolveToolRoutingConfig

    按规则顺序应用，后命中的覆盖先命中的（同工具名以最后一次为准）。

    Args:
        provider_id: provider 标识（如 "qwen" / "openai-native"）
        model_id: 模型 ID（如 "qwen-plus" / "gpt-4o"）
        mode: 当前模式（"act" / "plan"）
        rules: 路由规则列表，None 或空列表返回空字典

    Returns:
        dict[tool_name, enabled]: 工具名到启用状态的映射，
                                  未出现在字典中的工具保持默认启用
    """
    if not rules:
        return {}

    toggles: dict[ToolName, bool] = {}
    for rule in rules:
        if not _matches_rule(rule, provider_id, model_id, mode):
            continue
        for tool_name in rule.disable_tools:
            toggles[tool_name] = False
        for tool_name in rule.enable_tools:
            toggles[tool_name] = True
    return toggles


def apply_tool_routing(
    tools: list[Any],
    toggles: dict[ToolName, bool],
) -> list[Any]:
    """根据路由开关过滤工具列表

    Args:
        tools: 原始工具列表（应有 name 属性或字典 key "name"）
        toggles: resolve_tool_routing 返回的开关字典

    Returns:
        过滤后的工具列表；toggles 为空时原样返回
    """
    if not toggles:
        return list(tools)

    result: list[Any] = []
    for tool in tools:
        name = getattr(tool, "name", None) or (tool.get("name") if isinstance(tool, dict) else None)
        if name is None:
            result.append(tool)
            continue
        enabled = toggles.get(name, True)
        if enabled:
            result.append(tool)
    return result


def extract_model_info(model: Any) -> tuple[str, str]:
    """从 AgentModel 实例提取 provider_id 和 model_id

    优先使用模型对象显式提供的 provider_id / model_id 属性，
    否则按 model.model 字段推断 provider_id（仅支持已知 provider）。

    Args:
        model: 实现 AgentModel 协议的对象

    Returns:
        (provider_id, model_id)，未知时 provider_id 为空字符串
    """
    model_id = ""
    provider_id = ""

    # 显式属性优先
    explicit_provider = getattr(model, "provider_id", None)
    if isinstance(explicit_provider, str) and explicit_provider:
        provider_id = explicit_provider
    explicit_model = getattr(model, "model", None)
    if isinstance(explicit_model, str) and explicit_model:
        model_id = explicit_model

    # 类名推断 provider_id（兼容 QwenModel 等历史实现）
    if not provider_id:
        cls_name = type(model).__name__.lower()
        if "qwen" in cls_name or "dashscope" in cls_name:
            provider_id = "qwen"
        elif "openai" in cls_name:
            provider_id = "openai"
        elif "anthropic" in cls_name or "claude" in cls_name:
            provider_id = "anthropic"

    return provider_id, model_id
