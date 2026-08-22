# -*- coding: utf-8 -*-
"""文件 hook 加载器 — Phase 28.3 新增，对标 Cline hook-factory + templates

扫描 agent_config/hooks/{hook_type}/ 目录下的可执行脚本，
解析 frontmatter 配置，构建 FileHookConfig 列表。

目录结构示例:
    agent_config/hooks/
    ├── PreToolUse/
    │   ├── block-rm.sh          # 拦截 rm -rf 命令
    │   └── log-commands.py      # 记录所有命令调用
    ├── PostToolUse/
    │   └── filter-secrets.py    # 过滤工具输出中的敏感信息
    ├── UserPromptSubmit/
    │   └── sanitize-input.py    # 清理用户输入
    ├── TaskStart/
    │   └── notify-start.sh      # 任务开始通知
    └── TaskComplete/
        └── notify-done.sh       # 任务完成通知

frontmatter 解析使用标准库（无 PyYAML 依赖），仅支持简单 key: value 格式：
    ---
    description: 拦截危险命令
    applyTo: [run_commands, exec]
    blocking: false
    timeout: 30
    ---

兼容性：若脚本无 frontmatter，使用默认配置（blocking=false, timeout=30）。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from agent.file_hooks.types import (
    DEFAULT_HOOK_TIMEOUT,
    FileHookConfig,
    FileHookType,
    SUPPORTED_SCRIPT_EXTENSIONS,
)

logger = logging.getLogger(__name__)


# frontmatter 分隔符
_FRONTMATTER_DELIMITER = "---"
_FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)


def load_hooks_from_dir(hooks_dir: Path) -> list[FileHookConfig]:
    """从 hooks 目录加载所有文件 hook 配置

    扫描 hooks_dir/{hook_type}/ 下的可执行脚本，解析 frontmatter。

    Args:
        hooks_dir: hooks 根目录路径（如 agent_config/hooks/）

    Returns:
        FileHookConfig 列表（按 hook_type 分组，组内按文件名排序）
    """
    if not hooks_dir.exists() or not hooks_dir.is_dir():
        logger.debug("hooks 目录不存在或不是目录: %s", hooks_dir)
        return []

    configs: list[FileHookConfig] = []

    for hook_type in FileHookType:
        type_dir = hooks_dir / hook_type.value
        if not type_dir.is_dir():
            continue

        for script_path in sorted(type_dir.iterdir()):
            if not script_path.is_file():
                continue
            if script_path.suffix.lower() not in SUPPORTED_SCRIPT_EXTENSIONS:
                continue

            config = _parse_hook_script(script_path, hook_type)
            if config is not None:
                configs.append(config)

    logger.info("从 %s 加载了 %d 个文件 hook", hooks_dir, len(configs))
    return configs


def _parse_hook_script(
    script_path: Path,
    hook_type: FileHookType,
) -> FileHookConfig | None:
    """解析单个 hook 脚本的 frontmatter

    Args:
        script_path: 脚本文件路径
        hook_type: hook 类型（由所在目录决定）

    Returns:
        FileHookConfig 或 None（解析失败时）
    """
    try:
        content = script_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("读取 hook 脚本失败 %s: %s", script_path, e)
        return None

    frontmatter = _parse_frontmatter(content)

    # 构建配置
    config = FileHookConfig(
        script_path=script_path.resolve(),
        hook_type=hook_type,
        description=frontmatter.get("description", ""),
        apply_to=_parse_apply_to(frontmatter.get("applyTo")),
        # Stage 5.3 (P4/P18): 默认 False — 对标 Cline fail-open 语义
        blocking=_parse_bool(frontmatter.get("blocking"), default=False),
        timeout=_parse_int(frontmatter.get("timeout"), default=DEFAULT_HOOK_TIMEOUT),
    )

    logger.debug(
        "加载 hook: %s type=%s apply_to=%s blocking=%s timeout=%s",
        script_path.name, hook_type.value, config.apply_to,
        config.blocking, config.timeout,
    )
    return config


def _parse_frontmatter(content: str) -> dict[str, str]:
    """解析 YAML frontmatter（简单实现，无 PyYAML 依赖）

    仅支持 key: value 和 key: [item1, item2] 格式。
    复杂 YAML 请使用 PyYAML（这里不引入依赖）。

    Args:
        content: 脚本文件内容

    Returns:
        frontmatter 字典（无 frontmatter 时返回空字典）
    """
    match = _FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}

    frontmatter_text = match.group(1)
    result: dict[str, str] = {}

    for line in frontmatter_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()

    return result


def _parse_apply_to(value: str | None) -> list[str]:
    """解析 applyTo 字段

    支持格式：
        - "[run_commands, exec]" → ["run_commands", "exec"]
        - "run_commands" → ["run_commands"]
        - "" → []

    Args:
        value: frontmatter 中的原始值

    Returns:
        工具名列表
    """
    if not value:
        return []

    # 去除方括号
    value = value.strip().lstrip("[").rstrip("]")
    if not value:
        return []

    # 按逗号分隔
    parts = [p.strip().strip("'\"") for p in value.split(",")]
    return [p for p in parts if p]


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """解析布尔值"""
    if value is None:
        return default
    return value.lower() in ("true", "yes", "1", "on")


def _parse_int(value: str | None, default: int = 0) -> int:
    """解析整数"""
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
