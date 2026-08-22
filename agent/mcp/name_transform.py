# -*- coding: utf-8 -*-
"""MCP 工具名转换 — 对标 Cline name-transform.ts

将 `serverName__toolName` 格式的 MCP 工具名转换为符合 OpenAI function name
限制的字符串（≤ 64 字符，仅含 [a-zA-Z0-9_-]）。

适用场景:
    - 当 MCP 工具作为独立的 LLM function 暴露时（Cline 模式）
    - server_name 或 tool_name 过长导致组合名超过 64 字符
    - 名称含非法字符（如点号、空格、Unicode）

当前架构说明:
    本系统的 MCP 工具通过 use_mcp_tool(server_name, tool_name, args) 统一调用，
    MCP 工具名不直接作为 LLM function name 暴露，因此不需要在 registry 中
    强制应用此转换。本模块作为工具函数提供，未来若按 Cline 模式将 MCP 工具
    展开为独立 LLM function 时可直接调用 default_mcp_tool_name_transform。

对标 Cline:
    - sdk/packages/core/src/extensions/mcp/name-transform.ts L1-35
"""

from __future__ import annotations

import hashlib
import re

# OpenAI function name 限制：64 字符；Anthropic 允许 128 字符
# 取较小值以保证 OpenAI 兼容 provider 不会拒绝长 MCP 工具名
MAX_MCP_TOOL_NAME_LENGTH = 64

# 非法字符正则：除字母、数字、下划线、短横线外的所有字符
_INVALID_MCP_TOOL_NAME_CHARACTERS = re.compile(r"[^a-zA-Z0-9_-]+")

# hash 长度和分隔符长度
_HASH_LENGTH = 8
_HASH_SEPARATOR_LENGTH = 1

# 当原始名被清理后为空时使用的回退基础名
_FALLBACK_BASE_NAME = "mcp_tool"


def _build_mcp_tool_name_hash(value: str) -> str:
    """计算 SHA1 hash 的前 8 位 — 对标 Cline buildMcpToolNameHash"""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:_HASH_LENGTH]


def _sanitize_mcp_tool_name_candidate(value: str) -> str:
    """将非法字符替换为下划线 — 对标 Cline sanitizeMcpToolNameCandidate"""
    return _INVALID_MCP_TOOL_NAME_CHARACTERS.sub("_", value)


def default_mcp_tool_name_transform(server_name: str, tool_name: str) -> str:
    """默认 MCP 工具名转换 — 对标 Cline defaultMcpToolNameTransform

    转换规则:
        1. 拼接为 `serverName__toolName`
        2. 若原始名合法且长度 ≤ 64，直接返回
        3. 否则：清理非法字符为下划线 → 取前 N 位 → 拼接 _hash
           其中 N = 64 - 1（分隔符）- 8（hash）

    Args:
        server_name: MCP 服务器名
        tool_name: MCP 工具名

    Returns:
        转换后的工具名（保证 ≤ 64 字符，仅含 [a-zA-Z0-9_-]）
    """
    raw_name = f"{server_name}__{tool_name}"
    sanitized_name = _sanitize_mcp_tool_name_candidate(raw_name)

    # 合法且未超长，直接返回
    if sanitized_name == raw_name and len(raw_name) <= MAX_MCP_TOOL_NAME_LENGTH:
        return raw_name

    # 需要截断 + hash 后缀
    hash_value = _build_mcp_tool_name_hash(raw_name)
    max_base_length = MAX_MCP_TOOL_NAME_LENGTH - _HASH_SEPARATOR_LENGTH - _HASH_LENGTH
    base_name = sanitized_name[:max_base_length] or _FALLBACK_BASE_NAME
    return f"{base_name}_{hash_value}"
