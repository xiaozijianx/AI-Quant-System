# -*- coding: utf-8 -*-
"""系统提示组装 + 上下文压缩 — 对标 Cline buildClineSystemPrompt + compaction

SystemPromptBuilder:
    对齐 Cline 的 base prompt + rules 两层结构:
        1. Base Prompt: DEFAULT_CHARLES_SYSTEM_PROMPT 模板，替换占位符
        2. Rules (effectiveRules): 用户规则 + MODE_TAG + PLAN_MODE + 可选增强层

    对齐 Cline cline.ts buildClineSystemPrompt():
        - effectiveRules = [rules, MODE_TAG_INSTRUCTIONS, PLAN_MODE_INSTRUCTIONS]
        - 占位符: {{CHARLES_RULES}} → {{CHARLES_METADATA}}（rules 在前，metadata 在后）
        - MODE_TAG 和 PLAN_MODE 作为 rule 注入，不硬编码在 base prompt 中

    可选增强层（通过 agent_config/system_prompt.yaml 控制，默认关闭）:
        当 enhancements.enabled=true 时，以下段作为 rule 追加:
            - charles-tools-overview
            - charles-mcp-overview
            - charles-always-skills
            - charles-skills-summary

ContextCompactor:
    当对话历史 token 数超过阈值时，压缩旧消息（对标 Cline compaction）:
        1. 估算消息 token 数（简单估算: chars / 4）
        2. 超过阈值时，保留最近 N 条消息
        3. 旧消息用 LLM 生成摘要替换
        4. 摘要消息 + 最近 N 条消息 = 新的对话历史

对标 Cline:
    - system prompt: sdk/packages/shared/src/prompt/cline.ts buildClineSystemPrompt()
    - base prompt 模板: sdk/packages/shared/src/prompt/system.ts
    - compaction: sdk/packages/core/src/extensions/context/compaction.ts
    - 触发条件: requestInputTokens >= maxInputTokens * COMPACTION_TRIGGER_RATIO (0.8)
    - 策略: agentic（默认）/ basic
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent.hooks import BeforeModelContext, BeforeModelResult
from agent.prompts.charles_system_prompt import DEFAULT_CHARLES_SYSTEM_PROMPT
from agent.rules_loader import (
    RuleLoadResult,
    format_rules_content,
    load_rules_directory,
    synchronize_rule_toggles,
)
from agent.skills.registry import SkillRegistry
# Stage 11.2 (J12): 导入 AbortedError — 对标 Cline compaction-runner.ts 的 abort 处理
from agent.abort import AbortedError
from agent.types import (
    AgentMessage,
    AgentModel,
    AgentModelRequest,
    AgentToolDefinition,
    MessageRole,
    TextPart,
    ToolResultPart,
    create_message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 纯组装器 — 对标 Cline cline.ts buildClineSystemPrompt
# 不加载 rules，不查询 git，只做模板选择 + 占位符替换
# ============================================================================


def build_charles_system_prompt(
    base_template: str,
    platform_name: str,
    current_date: str,
    ide_name: str,
    working_dir: str,
    rules_text: str,
    metadata_text: str,
    provider_id: str | None = None,
) -> str:
    """纯组装器 — 对齐 Cline buildClineSystemPrompt

    与 Cline 的对齐点:
        - 不从磁盘加载 rules（由调用方传入 rules_text）
        - 不查询 git（metadata 由调用方传入 metadata_text）
        - 仅做模板选择 + 占位符替换

    Args:
        base_template: base prompt 模板字符串（DEFAULT 或 YOLO）
        platform_name: 平台名称
        current_date: 当前日期（ISO 8601）
        ide_name: IDE/运行环境名称
        working_dir: 工作目录
        rules_text: rules 文本（已由编排器组装完成）
        metadata_text: metadata 文本（已由编排器构建完成）
        provider_id: LLM provider ID（用于 L4 metadata 条件判断）

    Returns:
        完整的 system prompt 文本
    """
    prompt = base_template

    # 替换 <env> 占位符
    prompt = prompt.replace("{{PLATFORM_NAME}}", platform_name)
    prompt = prompt.replace("{{CURRENT_DATE}}", current_date)
    prompt = prompt.replace("{{IDE_NAME}}", ide_name)
    prompt = prompt.replace("{{CWD}}", working_dir)

    # 替换 rules 占位符
    prompt = prompt.replace("{{CHARLES_RULES}}", rules_text)

    # L4: metadata 条件注入 — 对齐 Cline isCline(providerId) 条件
    # Cline 仅 isCline provider 时注入 metadata；Charles 默认所有 provider 都注入
    # （Charles 合理增强：量化场景所有 provider 都需要 workspaces metadata）
    if should_inject_metadata(provider_id):
        prompt = prompt.replace("{{CHARLES_METADATA}}", metadata_text)
    else:
        prompt = prompt.replace("{{CHARLES_METADATA}}", "")

    return prompt.strip()


def should_inject_metadata(provider_id: str | None) -> bool:
    """判断是否注入 workspaces metadata — 对齐 Cline isCline(providerId)

    Cline 仅 isCline provider 时注入 metadata。
    Charles 仅 is_charles_provider 时注入（所有 Charles 支持的 provider 都注入）。

    对标 Cline cline.ts L124/L160:
        const isCline = isClineProvider(providerId || "");
        isCline ? buildWorkspaceMetadata(...) : ""

    Args:
        provider_id: LLM provider ID

    Returns:
        True 表示注入 metadata
    """
    return is_charles_provider(provider_id)


# Charles 支持的 provider ID 白名单 — 对标 Cline isClineProvider 的 "cline"/"cline-pass"
# Cline 仅官方 provider（cline/cline-pass）注入 metadata；
# Charles 所有支持的 provider 都注入（无第三方 provider 概念）。
# 未来若接入第三方 provider（非 Charles 原生），可从此白名单移除。
_CHARLES_PROVIDER_IDS: frozenset[str] = frozenset({
    "qwen",
    "deepseek",
    "openai",
    "anthropic",
    "charles",
})


def is_charles_provider(provider_id: str | None) -> bool:
    """判断是否是 Charles 支持的 provider — 对标 Cline isClineProvider

    对标 Cline sdk/packages/shared/src/providers/utils.ts L1-3:
        export function isClineProvider(providerId: string): boolean {
            return providerId === "cline" || providerId === "cline-pass";
        }

    Cline 仅 cline/cline-pass 注入 metadata；Charles 所有支持的 provider 都注入。
    None/空字符串视为 Charles 默认 provider（qwen），向后兼容未显式传入的场景。

    Args:
        provider_id: LLM provider ID

    Returns:
        True 表示是 Charles 支持的 provider
    """
    if not provider_id:
        # Charles 默认有 provider（qwen），None/空字符串视为默认 provider
        return True
    return provider_id in _CHARLES_PROVIDER_IDS


def select_base_template(mode: str | None = None) -> str:
    """选择 base prompt 模板 — 对齐 Cline 根据 mode 选择 DEFAULT / YOLO

    对齐 Cline cline.ts:
        - yolo 模式使用 YOLO_CLINE_SYSTEM_PROMPT（后台自动化场景）
        - act/plan 模式使用 DEFAULT_CLINE_SYSTEM_PROMPT（交互场景）

    Args:
        mode: 当前模式（act / plan / yolo）

    Returns:
        对应的 base prompt 模板字符串
    """
    from agent.prompts.charles_system_prompt import (
        DEFAULT_CHARLES_SYSTEM_PROMPT,
        YOLO_CHARLES_SYSTEM_PROMPT,
    )

    if mode == "yolo":
        return YOLO_CHARLES_SYSTEM_PROMPT
    return DEFAULT_CHARLES_SYSTEM_PROMPT


# ============================================================================
# 编排器 — 对标 Cline session-runtime-orchestrator composeSystemPrompt
# 负责: 收集 rules + 构建 metadata + 调用纯组装器
# ============================================================================


class SystemPromptBuilder:
    """系统提示编排器 — 对齐 Cline session-runtime-orchestrator composeSystemPrompt

    A1 重构后的职责分层（对齐 Cline 架构）:
        - 编排器（本类）: 收集 rules + 构建 metadata + 选择模板 + 调用纯组装器
        - 纯组装器（build_charles_system_prompt 函数）: 模板选择 + 占位符替换

    本类不再直接做占位符替换，而是:
        1. _build_rules(): 从磁盘加载 AGENTS.md + rules_dir + 注入 MODE_TAG/PLAN_MODE/enhancements + 动态注册 rules
        2. _build_metadata(): 查询 git 状态构建 workspaces JSON
        3. _get_current_mode(): 查询当前 mode 选择 base 模板（DEFAULT / YOLO）
        4. build(): 调用 build_charles_system_prompt() 纯函数完成组装

    动态 rule 注册（对标 Cline contributionRegistry）:
        通过 register_rule(name, content) 方法在运行时注册额外的 rule，
        build() 时合并到 Rules 段末尾。对标 Cline composeSystemPrompt() 中
        遍历 contributionRegistry.getRegisteredRules() 的逻辑。

    与 Cline 的对齐:
        - Cline buildClineSystemPrompt() 是纯函数，不加载 rules/metadata
        - Cline orchestrator 收集 rules 后调用 builder
        - Charles SystemPromptBuilder 对应 orchestrator，build_charles_system_prompt 对应 builder

    可选增强层（通过 agent_config/system_prompt.yaml 控制）:
        当 enhancements.enabled=true 时，以下段作为 rule 追加到 Rules 末尾:
            - charles-tools-overview
            - charles-mcp-overview
            - charles-always-skills
            - charles-skills-summary

    保留的辅助方法（向后兼容/测试依赖）:
        - _build_mode_tag_instructions(): 返回 mode 标签说明
        - _read_git_state(): 返回 git 元数据
        - _build_tools_section(): 构建工具概览
        - _build_mcp_servers_section(): 构建 MCP 概览
    """

    def __init__(
        self,
        identity: str = "",
        agents_path: Path | str | None = None,
        skills_registry: SkillRegistry | None = None,
        rules_dir: Path | str | None = None,
        session_id: str | None = None,
        tools: list[Any] | None = None,
        working_dir: str | None = None,
        business_modes: list[str] | None = None,
        rule_paths: list[str] | None = None,
        rule_toggles: dict[str, bool] | None = None,
        ide_name: str = "Charles Web",
        config_path: Path | str | None = None,
    ) -> None:
        """初始化系统提示组装器

        Args:
            identity: [已废弃] 身份定义已固定在 DEFAULT_CHARLES_SYSTEM_PROMPT 模板中，
                       此参数保留仅为向后兼容，build() 中不使用。对齐 Cline — Cline
                       的身份定义固定在 system.ts 模板第一行，不接受外部传入。
            agents_path: AGENTS.md 文件路径（保留兼容，新架构下 AGENTS.md 应位于 rules_dir）
            skills_registry: 技能注册表
            rules_dir: 规则文件目录
            session_id: 会话 ID，用于查询当前 mode 注入 PLAN_MODE_PROMPT
            tools: 已注册的工具列表，用于构建 tools_section 增强层
            working_dir: 工作目录路径，用于 <env> 和 metadata
            business_modes: 业务模式列表（如 ["research"]/["trade"]），用于 rules frontmatter mode 过滤
            rule_paths: 候选工作空间路径，用于 rules frontmatter paths 过滤
            rule_toggles: 规则文件启用/禁用开关，{相对路径: bool}
            ide_name: IDE/运行环境名称，对标 Cline {{IDE_NAME}}
            config_path: 增强层配置文件路径，None 时使用默认 agent_config/system_prompt.yaml
        """
        # identity 已废弃：身份定义固定在 base prompt 模板中，此参数仅为向后兼容
        self.identity = identity
        self.agents_path = Path(agents_path) if agents_path else None
        self.skills_registry = skills_registry
        self.rules_dir = Path(rules_dir) if rules_dir else None
        self.session_id = session_id
        self.tools = tools or []
        self.working_dir = working_dir or os.getcwd()
        self.business_modes = business_modes or []
        self.rule_paths = rule_paths or []
        self.rule_toggles = rule_toggles
        self.ide_name = ide_name
        self.config_path = Path(config_path) if config_path else Path("agent_config") / "system_prompt.yaml"
        # 读取增强层配置（默认全部关闭，与 Cline 对齐）
        self._enhancements = self._load_enhancements()
        # 动态注册的 rules — 对标 Cline contributionRegistry.getRegisteredRules()
        # 通过 register_rule() 注册，在 _build_rules 时合并到 Rules 段末尾
        self._registered_rules: list[tuple[str, str]] = []

    def register_rule(self, name: str, content: str) -> None:
        """动态注册 rule — 对标 Cline contributionRegistry.registerRule

        在运行时向 SystemPromptBuilder 注册额外的 rule，下次 build() 时
        会将其合并到 Rules 段末尾（在 AGENTS.md / rules_dir / MODE_TAG /
        PLAN_MODE / enhancements 之后）。

        对标 Cline session-runtime-orchestrator.ts composeSystemPrompt():
            for (const rule of this.contributionRegistry.getRegisteredRules()) {
                const content = await resolveRuleContent(rule);
                if (content) { rules.push(content); }
            }

        用法:
            builder = SystemPromptBuilder(...)
            builder.register_rule("my-custom-rule", "禁止在周末调用买入工具")
            prompt = builder.build()

        Args:
            name: rule 名称（唯一标识，用于去重和路径生成）
            content: rule 正文内容
        """
        if not name or not content or not content.strip():
            return
        # 去重：同名 rule 覆盖旧内容
        self._registered_rules = [
            (n, c) for n, c in self._registered_rules if n != name
        ]
        self._registered_rules.append((name, content.strip()))

    def _load_enhancements(self) -> dict[str, bool]:
        """读取增强层配置 — 默认全部 false，与 Cline 完全对齐

        配置文件格式:
            enhancements:
              enabled: false       # 总开关
              tools_section: true  # 工具概览
              mcp_section: true    # MCP 概览

        Returns:
            增强层开关字典；配置文件不存在或解析失败时返回全部 false
        """
        default = {
            "enabled": False,
            "tools_section": True,
            "mcp_section": True,
        }
        if not self.config_path.exists():
            return default

        try:
            import yaml

            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
            cfg = data.get("enhancements", {})
            if not isinstance(cfg, dict):
                return default

            enabled = bool(cfg.get("enabled", False))
            result: dict[str, bool] = {"enabled": enabled}
            for key in ("tools_section", "mcp_section"):
                # 总开关关闭时，所有子开关强制 false
                result[key] = enabled and bool(cfg.get(key, True))
            return result
        except Exception as e:
            logger.debug("SystemPromptBuilder: 读取增强层配置失败（已忽略）: %s", e)
            return default

    def build(self, task_type: str = "general", provider_id: str | None = None) -> str:
        """编排并组装完整的 system prompt — 对齐 Cline composeSystemPrompt

        A1 重构后的职责分层（对齐 Cline 架构）:
            1. 编排器职责（本方法）: 收集 rules + 构建 metadata
            2. 纯组装器职责（build_charles_system_prompt 函数）: 模板选择 + 占位符替换

        本方法不再直接做占位符替换，而是:
            a. 调用 _build_rules() 收集 rules 文本（AGENTS.md + rules_dir + MODE_TAG + PLAN_MODE + enhancements）
            b. 调用 _build_metadata() 构建 metadata 文本（查询 git 状态）
            c. 查询当前 mode 选择 base 模板（DEFAULT / YOLO）
            d. 调用 build_charles_system_prompt() 纯函数完成组装

        Args:
            task_type: 任务类型，用于兼容层单文件加载（如 "report"）
            provider_id: LLM provider ID，用于 L4 metadata 条件判断

        Returns:
            完整的 system prompt 文本
        """
        from datetime import date
        import platform

        # 编排器: 收集 rules（从磁盘加载 AGENTS.md + rules_dir + 注入 MODE_TAG/PLAN_MODE/enhancements）
        rules_text = self._build_rules(task_type)

        # 编排器: 构建 metadata（查询 git 状态）
        metadata_text = self._build_metadata()

        # 编排器: 查询当前 mode 选择 base 模板（L8: 对齐 Cline DEFAULT/YOLO 双模板）
        mode = self._get_current_mode()
        base_template = select_base_template(mode)

        # 纯组装器: 模板选择 + 占位符替换（不加载任何外部数据）
        return build_charles_system_prompt(
            base_template=base_template,
            platform_name=platform.platform(terse=True),
            current_date=date.today().isoformat(),
            ide_name=self.ide_name,
            working_dir=self.working_dir,
            rules_text=rules_text,
            metadata_text=metadata_text,
            provider_id=provider_id,
        )

    def _get_current_mode(self) -> str | None:
        """查询当前会话模式 — 用于选择 base 模板（L8）

        Returns:
            当前模式（act / plan / yolo），或 None
        """
        if not self.session_id:
            return None
        try:
            from agent.state import get_mode

            return get_mode(self.session_id)
        except Exception:
            return None

    def _build_metadata(self) -> str:
        """构建工作空间元数据块 — 对标 Cline buildWorkspaceMetadata

        对齐 Cline 的 workspaces 嵌套结构 + 标签格式:
            # Workspace Configuration
            {
                "workspaces": {
                    "/path/to/workspace": {
                        "hint": "workspace_name",
                        "latestGitCommitHash": "...",
                        "latestGitBranchName": "..."
                    }
                }
            }

        L5 对齐: 使用 Cline 的 `# Workspace Configuration` 文本标记，
                 不再使用 `<charles_metadata>` XML 标签。

        Returns:
            `# Workspace Configuration` 开头的 JSON 文本
        """
        git_info = self._read_git_state()
        # 对齐 Cline: hint 用 ide_name 或目录名
        workspace_name = self.ide_name or self.working_dir.split("/")[-1] or self.working_dir
        workspace_entry: dict[str, Any] = {
            "hint": workspace_name,
        }
        if git_info.get("commit"):
            workspace_entry["latestGitCommitHash"] = git_info["commit"]
        if git_info.get("branch"):
            workspace_entry["latestGitBranchName"] = git_info["branch"]
        if git_info.get("remote"):
            workspace_entry["associatedRemoteUrls"] = [git_info["remote"]]

        metadata: dict[str, Any] = {
            "workspaces": {
                self.working_dir: workspace_entry,
            },
        }

        # L5: 对齐 Cline WORKSPACE_CONFIGURATION_MARKER
        return (
            "# Workspace Configuration\n"
            f"{json.dumps(metadata, ensure_ascii=False, indent=2)}"
        )

    def _build_rules(self, task_type: str) -> str:
        """构建 Rules 段 — 对齐 Cline effectiveRules

        AGENTS.md 加载顺序（对标 Cline resolveRulesConfigSearchPaths）:
            1. global AGENTS.md（~/.agents/AGENTS.md）
            2. workspace root AGENTS.md（<cwd>/AGENTS.md）
            3. workspace config AGENTS.md（agents_path，如 agent_config/AGENTS.md）
            4. workspace subdirectories rules_dir（agent_config/rules/）

        后加载的规则覆盖先加载的（同名时 workspace 优先于 global）。

        其余 effectiveRules 组装顺序:
            5. MODE_TAG_INSTRUCTIONS（mode 标签说明，始终注入）
            6. PLAN_MODE_INSTRUCTIONS（plan 模式契约，仅 plan 模式注入）
            7. 可选增强层（按配置开关）
            8. 动态注册的 rules（通过 register_rule() 注册，对标 Cline contributionRegistry）

        Args:
            task_type: 任务类型，用于兼容层单文件加载

        Returns:
            拼接后的 Rules 文本（含 # Rules 标题）；无规则时返回空字符串
        """
        results: list[RuleLoadResult] = []

        # 1. 全局 AGENTS.md（~/.agents/AGENTS.md）作为第一个 rule
        # 对标 Cline resolveGlobalAgentsRulesPath(): ~/.agents/AGENTS.md
        global_agents_path = Path.home() / ".agents" / "AGENTS.md"
        if global_agents_path.exists():
            try:
                content = global_agents_path.read_text(encoding="utf-8").strip()
                if content:
                    results.append(RuleLoadResult(
                        path=global_agents_path,
                        body=self._strip_frontmatter(content),
                        activated=True,
                    ))
            except Exception as e:
                logger.debug("context: 加载全局 AGENTS.md 失败（已忽略）: %s", e)

        # 2. workspace root AGENTS.md（<cwd>/AGENTS.md）
        # 对标 Cline resolveRulesConfigSearchPaths 中的 join(workspacePath, AGENTS_RULES_FILE_NAME)
        # 后加载的 workspace 规则覆盖先加载的 global 规则（同名时 workspace 优先）
        workspace_root_agents_path = Path(self.working_dir) / "AGENTS.md"
        if workspace_root_agents_path.exists():
            try:
                content = workspace_root_agents_path.read_text(encoding="utf-8").strip()
                if content:
                    results.append(RuleLoadResult(
                        path=workspace_root_agents_path,
                        body=self._strip_frontmatter(content),
                        activated=True,
                    ))
            except Exception as e:
                logger.debug("context: 加载 workspace root AGENTS.md 失败（已忽略）: %s", e)

        # 3. 兼容旧接口：若显式传入 agents_path 且文件存在，也作为 rule
        # agents_path 通常指向 agent_config/AGENTS.md，属于 workspace 子目录级别配置
        if self.agents_path and self.agents_path.exists():
            try:
                content = self.agents_path.read_text(encoding="utf-8").strip()
                if content:
                    results.append(RuleLoadResult(
                        path=self.agents_path,
                        body=self._strip_frontmatter(content),
                        activated=True,
                    ))
            except Exception as e:
                logger.debug("context: 加载 workspace AGENTS.md 失败（已忽略）: %s", e)

        # 4. workspace rules_dir（子目录级规则）
        if self.rules_dir and self.rules_dir.exists():
            results.extend(self._load_rules_directory(task_type))

        # 5. MODE_TAG_INSTRUCTIONS — 作为 rule 注入（对齐 Cline effectiveRules）
        mode_tag = self._build_mode_tag_instructions()
        if mode_tag:
            results.append(RuleLoadResult(
                path=Path("__mode__/mode_tag_instructions.md"),
                body=mode_tag,
                activated=True,
            ))

        # 6. PLAN_MODE_INSTRUCTIONS — 作为 rule 注入（仅 plan 模式，对齐 Cline effectiveRules）
        plan_prompt = self._load_mode_prompt()
        if plan_prompt:
            results.append(RuleLoadResult(
                path=Path("__mode__/plan_mode_instructions.md"),
                body=plan_prompt,
                activated=True,
            ))

        # 7. 增强层（按配置开关）
        # MCP 服务器概览强制注入：配置了 MCP 服务器就必须让 LLM 知道其存在，
        # 否则 agent 永远不会调用 use_mcp_tool / access_mcp_resource
        mcp_body = self._build_mcp_servers_section()
        if mcp_body:
            results.append(RuleLoadResult(
                path=Path("__enhancements__/charles-mcp-overview.md"),
                body=mcp_body,
                activated=True,
            ))
        if self._enhancements.get("enabled"):
            for title, body in self._build_enhancement_rules():
                if body:
                    results.append(RuleLoadResult(
                        path=Path(f"__enhancements__/{title}.md"),
                        body=body,
                        activated=True,
                    ))

        # 8. 动态注册的 rules — 对标 Cline contributionRegistry.getRegisteredRules()
        # 通过 register_rule() 注册，在所有静态 rules 之后追加
        for name, content in self._registered_rules:
            if content:
                results.append(RuleLoadResult(
                    path=Path(f"__registered__/{name}.md"),
                    body=content,
                    activated=True,
                ))

        return format_rules_content(results)

    def _load_rules_directory(self, task_type: str) -> list[RuleLoadResult]:
        """加载 workspace rules_dir 下的规则文件

        兼容层：先加载 rules/<task_type>.md，再扫描整个目录。
        扫描时通过 toggle 禁用已兼容加载的文件，避免重复。

        Args:
            task_type: 任务类型

        Returns:
            RuleLoadResult 列表
        """
        results: list[RuleLoadResult] = []
        excluded_subdirs = ["workflows", "hooks", "skills"]
        merged_toggles: dict[str, bool] = {}

        # 1. 同步磁盘 toggles（作为默认值）
        try:
            persisted = synchronize_rule_toggles(
                self.rules_dir,
                excluded_subdirs=excluded_subdirs,
            )
            merged_toggles.update(persisted)
        except Exception as e:
            logger.debug("context: synchronize_rule_toggles 失败（已忽略）: %s", e)

        # 2. 应用显式传入的 toggles（用户显式设置优先）
        if self.rule_toggles:
            merged_toggles.update(self.rule_toggles)

        # 3. 兼容层：加载 rules/<task_type>.md，并禁用扫描重复
        rules_file = self.rules_dir / f"{task_type}.md"
        if rules_file.exists():
            content = rules_file.read_text(encoding="utf-8").strip()
            body = self._strip_frontmatter(content)
            if body:
                results.append(RuleLoadResult(
                    path=rules_file,
                    body=body,
                    activated=True,
                ))
                merged_toggles[rules_file.relative_to(self.rules_dir).as_posix()] = False

        # 查询当前 agent mode
        agent_mode = "act"
        if self.session_id:
            try:
                from agent.state import get_mode

                agent_mode = get_mode(self.session_id)
            except Exception as e:
                logger.debug("context: 查询 agent mode 失败 %s: %s", self.session_id, e)

        from agent.rules_loader import RuleEvaluationContext

        context = RuleEvaluationContext(
            agent_mode=agent_mode,
            business_modes=self.business_modes,
            paths=self.rule_paths,
        )

        directory_results = load_rules_directory(
            self.rules_dir,
            context=context,
            toggles=merged_toggles or None,
            excluded_subdirs=excluded_subdirs,
        )
        results.extend(directory_results)
        return results

    def _build_enhancement_rules(self) -> list[tuple[str, str]]:
        """根据配置生成增强层 rule 列表

        增强层内容作为普通 rule 追加到 Rules 末尾，由 format_rules_content
        统一添加 ## 标题，因此这里只返回正文，避免重复标题。

        Returns:
            [(rule_title, rule_body), ...]
        """
        rules: list[tuple[str, str]] = []

        if self._enhancements.get("tools_section"):
            body = self._build_tools_section()
            if body:
                rules.append(("charles-tools-overview", body))

        if self._enhancements.get("mcp_section"):
            body = self._build_mcp_servers_section()
            if body:
                rules.append(("charles-mcp-overview", body))

        return rules

    def _read_git_state(self) -> dict[str, Any]:
        """读取当前工作目录的 git 状态 — Stage 4.6 (L18) 保留

        Returns:
            含 branch/commit/remote 三个键的字典；非 git 仓库或读取失败时返回空字典
        """
        import subprocess

        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.working_dir,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).decode().strip()
        except Exception:
            return {}

        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.working_dir,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).decode().strip()
        except Exception:
            commit = ""

        try:
            remote = subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                cwd=self.working_dir,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).decode().strip()
        except Exception:
            remote = ""

        return {"branch": branch, "commit": commit, "remote": remote}

    def _build_tools_section(self) -> str:
        """构建工具列表 + 使用指引段 — 作为可选增强层保留

        Returns:
            工具列表文本，如果无工具则返回空字符串
        """
        if not self.tools:
            return ""

        lines = ["# 工具", "", "可用工具:"]
        for tool in self.tools:
            name = getattr(tool, "name", "")
            desc = getattr(tool, "description", "")
            if name == "skills":
                desc = (
                    "加载技能详细指令（SKILL.md）。"
                    "当任务匹配某个技能时，必须先调用此工具加载指令，"
                    "然后按返回指令使用 read_files/run_commands 等主工具执行。"
                    "可用技能目录见上方《技能目录》段"
                )
            elif len(desc) > 150:
                desc = desc[:150] + "..."
            if name:
                lines.append(f"- {name}: {desc}")

        lines.extend([
            "",
            "## 工具使用指引",
            "- 一次回复中可调用多个独立工具（并行），如多个 read_files / search_codebase",
            "- 依赖的工具调用需分多轮（如先 read_files 再 editor）",
            "- 当任务与某个专业技能（如 stock-price、read-pdf、write-report）匹配时，必须先调用 skills 工具加载该技能指令，再按返回的指令执行",
            "- 工具调用前先规划，调用后根据结果调整下一步",
            "",
            "## 工具 vs 技能 决策树（重要）",
            "遇到用户任务时，按以下顺序决策:",
            "1. 任务匹配某个技能（财务分析/RAG读年报/K线行情/写研报/...）?",
            "    → 是: 先调用 skills(skill=\"...\") 加载该技能 SKILL.md 指令，",
            "      然后按返回指令调用 read_files / run_commands / use_mcp_tool 等工具",
            "2. 任务是通用文件操作（读代码/搜索/编辑）?",
            "    → 是: 直接调用 read_files / search_codebase / editor 等工具，无需 skills",
            "3. 任务是临时命令执行（git status / ls / 跑独立脚本）?",
            "    → 是: 直接调用 run_commands 工具",
            "4. 任务需要联网搜索新闻/公告?",
            "    → 是: 调用 MCP 搜索工具（如 tavily_search）进行网络搜索（但股价/财报等本地已有数据禁止网络搜索）",
            "",
            "**禁止行为**:",
            "- 禁止不调用 skills 工具而直接 run_commands 调用技能目录下的脚本",
            "  （如 agent_config/skills/stock-price/scripts/get_kline.py）",
            "- 禁止把技能名当作工具名直接调用（如 stock-price(...) 是错误的，应 skills(skill=\"stock-price\")）",
            "- 禁止在 skills 工具返回指令前就假定知道脚本参数格式",
        ])
        return "\n".join(lines)

    def _build_mcp_servers_section(self) -> str:
        """构建 MCP 服务器概览段 — 作为可选增强层保留

        Returns:
            MCP 服务器概览文本
        """
        try:
            from agent.mcp.registry import get_registry
        except ImportError:
            return ""

        try:
            registry = get_registry()
            servers = registry.list_servers()
            if not servers:
                return ""

            lines = [
                "# MCP 服务器",
                "",
                "通过以下工具调用 MCP 服务器能力:",
                "- use_mcp_tool(server_name, tool_name, args): 调用 MCP 工具",
                "- access_mcp_resource(server_name, uri): 读取 MCP 资源",
                "",
            ]

            for srv in servers:
                transport_note = f" ({srv.transport})" if srv.transport != "stdio" else ""
                lines.append(f"## {srv.name}{transport_note}")
                if srv.description:
                    lines.append(srv.description)

                cached_tools = registry._tools_cache.get(srv.name, [])
                if cached_tools:
                    lines.append("工具:")
                    for tool in cached_tools:
                        desc = (tool.description or "").split("\n")[0][:80]
                        lines.append(f"- {tool.name}: {desc}")
                else:
                    lines.append(
                        "(工具列表未加载，调用 use_mcp_tool 时会自动连接并加载)"
                    )
                lines.append("")

            return "\n".join(lines)
        except Exception:
            return ""

    def _build_mode_tag_instructions(self) -> str:
        """构建 <user_input mode> 标签说明段 — 保留方法供测试/外部调用

        L7 对齐: 移除具体工具名列举，工具限制由 tool_policies 硬禁用，
                 不在 MODE_TAG 说明中重复（对齐 Cline — Cline 不列举具体工具名）。

        Returns:
            标签说明文本
        """
        return (
            "# 用户消息模式标签\n\n"
            "用户消息会被 `<user_input mode=\"...\">` 标签包裹，mode 取值:\n"
            "- `act`: 执行模式，可直接调用工具完成任务\n"
            "- `plan`: 规划模式，只读不写，先制定计划待用户批准后再执行。"
            "plan 模式下写入或执行类工具由 tool_policies 硬禁用\n"
            "- `yolo`: 自动执行模式（如启用），与 act 等价但无需逐步确认\n\n"
            "若连续消息的 mode 标签不同，说明用户切换了模式 — "
            "以最新消息的 mode 为准，无论之前消息允许什么操作。"
            "消息内可能出现 `<mode_notice>` 块，标记模式切换的确切时刻。\n\n"
            "各模式的具体行为约束见系统提示的 Plan Mode 段（仅 plan 模式注入）。"
        )

    def _load_mode_prompt(self) -> str | None:
        """加载模式提示 — Phase 12 保留

        Returns:
            Plan 模式提示词，或 None
        """
        if not self.session_id:
            return None

        from agent.tools.plan_mode import get_mode_prompt

        try:
            return get_mode_prompt(self.session_id)
        except Exception:
            return None

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """移除 Markdown 文件的 YAML frontmatter（若存在）

        Args:
            content: Markdown 文件原始内容

        Returns:
            移除 frontmatter 后的主体内容
        """
        if not content.startswith("---"):
            return content
        second_fence = content.find("\n---", 3)
        if second_fence == -1:
            return content
        return content[second_fence + 4:].lstrip()


# ============================================================================
# Token 估算 — 对标 Cline createTokenEstimator
# ============================================================================


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数 — 对标 Cline estimateMessageTokens

    采用混合估算策略，对中文更友好:
        - 中文字符: 约 1.5 tokens/字（实际通常 1~2 tokens/字）
        - 其他字符（英文/数字/标点）: 约 4 字符/token
    这不是精确的 token 计算，但比单纯的 len/4 更适合中文内容。
    """
    if not text:
        return 0
    # 统计中文字符数（CJK 统一表意文字范围）
    cn_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other_chars = len(text) - cn_chars
    return max(1, int(cn_chars * 1.5 + other_chars / 4))


def estimate_message_tokens(message: AgentMessage) -> int:
    """估算单条消息的 token 数"""
    total = 0
    for part in message.content:
        if isinstance(part, TextPart):
            total += estimate_tokens(part.text)
        else:
            # ToolCallPart / ToolResultPart / ReasoningPart
            import json
            data = {
                "type": type(part).__name__,
                "content": getattr(part, "__dict__", str(part)),
            }
            total += estimate_tokens(json.dumps(data, ensure_ascii=False, default=str))
    return total


def estimate_messages_tokens(messages: list[AgentMessage]) -> int:
    """估算消息列表的总 token 数"""
    return sum(estimate_message_tokens(msg) for msg in messages)


# ============================================================================
# 上下文压缩 — 对标 Cline compaction.ts
# ============================================================================


# 压缩触发比例 — 对标 Cline COMPACTION_TRIGGER_RATIO
_DEFAULT_COMPACTION_TRIGGER_RATIO = 0.9

# 默认最大输入 token 数 — 对标 Cline DEFAULT_MAX_INPUT_TOKENS
_DEFAULT_MAX_INPUT_TOKENS = 128000

# 压缩后保留的最近 token 数 — 对标 Cline DEFAULT_PRESERVE_RECENT_TOKENS
_DEFAULT_PRESERVE_RECENT_TOKENS = 20000

# 压缩后保留的最近消息数（向后兼容，优先用 preserve_recent_tokens）
_DEFAULT_KEEP_RECENT = 6

# 压缩摘要最大 token 数 — 对标 Cline DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS
_DEFAULT_SUMMARY_MAX_TOKENS = 1024

# Phase 29.4: budget-projection 默认配置 — 对标 Cline budget-projection
# 提前压缩触发比例（与 trigger_ratio 相乘，0.8 表示 0.9*0.8=0.72 时触发提前压缩）
_DEFAULT_PROJECTION_RATIO = 0.8
# 估算 tool_result 均值时保留的最近样本数
_DEFAULT_TOOL_RESULT_HISTORY_MAX = 10

# tool_result 内容截断字符数 — 对标 Cline TOOL_RESULT_CHAR_LIMIT
TOOL_RESULT_CHAR_LIMIT = 2000

# 文件内容截断字符数 — 对标 Cline FILE_CONTENT_CHAR_LIMIT
FILE_CONTENT_CHAR_LIMIT = 2000

# 保留最近 N 条 assistant 文本内容 — 对标 Cline PRESERVED_ASSISTANT_TEXT_COUNT
PRESERVED_ASSISTANT_TEXT_COUNT = 3

# 命令摘要截断字符数 — 对标 Cline COMMAND_SUMMARY_CHAR_LIMIT
COMMAND_SUMMARY_CHAR_LIMIT = 100

# Stage 11.4 (J18): file/image 数据截断阈值 — 对标 Cline compaction-truncator.ts
# 阈值基于 base64 字符数（base64 后约为原大小 1.33 倍）
# file: 100KB；image: 50KB
MAX_FILE_DATA_LENGTH = 100_000
MAX_IMAGE_DATA_LENGTH = 50_000


@dataclass
class CompactionState:
    """压缩状态 — 持久化保存已生成的摘要，避免每次都从完整历史重新压缩"""

    summary_message: AgentMessage
    compacted_count: int  # 被该摘要替代的原始消息数量
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class CompactionStateManager:
    """压缩状态管理器 — 对标 Cline createCompactionStateAwarePrepareTurn 中的 getState/saveState

    将每个会话的压缩状态持久化到 agent_data/compaction_states/<session_id>.json，
    服务重启后仍可基于上次摘要继续累积压缩。

    Stage 11.3 (J13) 增强:
        - 增加 system_prompt 字段，记录压缩时的 system prompt（不参与压缩）
        - 增加 project() 方法，返回 CompactionStateSnapshot 供前端显示压缩进度
        - 增加 start_compaction() / finish_compaction() / fail_compaction() 生命周期方法
          跟踪当前压缩状态（pending / running / completed / failed）和耗时
        - 持久化 system_prompt，rollback 后能恢复
    """

    def __init__(self, base_dir: Path | str | None = None) -> None:
        if base_dir is None:
            base_dir = Path("agent_data") / "compaction_states"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # Stage 11.3 (J13): 运行时压缩状态（非持久化，进程级）
        # 用于 project() 投影当前压缩活动给前端
        self._current_status: str = "pending"  # pending / running / completed / failed
        self._current_start_time: float = 0.0  # time.time()，用于计算 elapsed_ms
        self._current_elapsed_ms: int = 0
        self._current_original_count: int = 0
        self._current_compacted_count: int = 0
        self._current_discarded_count: int = 0
        # Stage 11.3 (J13): system_prompt 保留（不参与压缩）
        # 由 start_compaction 保存，finish_compaction 后保留供 runtime 读取
        self.system_prompt: str = ""

    def load(self, session_id: str) -> CompactionState | None:
        """加载指定会话的压缩状态"""
        path = self.base_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            from agent.session import _dict_to_message

            data = json.loads(path.read_text(encoding="utf-8"))
            summary = _dict_to_message(data["summary_message"])
            # Stage 11.3 (J13): 加载持久化的 system_prompt（若有）
            self.system_prompt = data.get("system_prompt", "")
            return CompactionState(
                summary_message=summary,
                compacted_count=data["compacted_count"],
                created_at=data.get("created_at", datetime.now().isoformat()),
            )
        except Exception as e:
            logger.warning("CompactionStateManager: 加载状态失败 %s: %s", session_id, e)
            return None

    def save(self, session_id: str, state: CompactionState) -> None:
        """保存指定会话的压缩状态"""
        path = self.base_dir / f"{session_id}.json"
        try:
            from agent.session import _message_to_dict

            data = {
                "summary_message": _message_to_dict(state.summary_message),
                "compacted_count": state.compacted_count,
                "created_at": state.created_at,
                # Stage 11.3 (J13): 持久化 system_prompt，重启后保持不变
                "system_prompt": self.system_prompt,
            }
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("CompactionStateManager: 保存状态失败 %s: %s", session_id, e)

    def clear(self, session_id: str) -> None:
        """清除指定会话的压缩状态（rollback 等场景使用）"""
        path = self.base_dir / f"{session_id}.json"
        if path.exists():
            try:
                path.unlink()
            except Exception as e:
                logger.warning("CompactionStateManager: 清除状态失败 %s: %s", session_id, e)
        # Stage 11.3 (J13): 清除运行时状态
        self._current_status = "pending"
        self._current_elapsed_ms = 0
        self._current_original_count = 0
        self._current_compacted_count = 0
        self._current_discarded_count = 0
        self.system_prompt = ""

    # ========================================================================
    # Stage 11.3 (J13): 压缩生命周期管理 + 状态投影
    # 对标 Cline compaction-state-manager.ts 的 startCompaction/project
    # ========================================================================

    def start_compaction(
        self,
        original_count: int,
        system_prompt: str = "",
    ) -> None:
        """开始压缩 — 记录起始时间和原始消息数

        对标 Cline CompactionStateManager.startCompaction()。
        由 ContextCompactor.before_model 在触发压缩时调用。

        Args:
            original_count: 原始消息数（压缩前）
            system_prompt: 当前的 system prompt（不参与压缩，仅保存供恢复）
        """
        import time as _time

        self._current_status = "running"
        self._current_start_time = _time.time()
        self._current_elapsed_ms = 0
        self._current_original_count = original_count
        self._current_compacted_count = 0
        self._current_discarded_count = 0
        # 保存 system_prompt（不参与压缩，始终保留）
        self.system_prompt = system_prompt

    def finish_compaction(
        self,
        compacted_count: int,
        discarded_count: int,
    ) -> None:
        """压缩完成 — 记录最终状态和耗时

        对标 Cline CompactionStateManager.finishCompaction()。
        由 ContextCompactor.before_model 在压缩成功后调用。

        Args:
            compacted_count: 压缩后消息数（含摘要消息）
            discarded_count: 被丢弃的消息数
        """
        import time as _time

        self._current_status = "completed"
        self._current_elapsed_ms = int((_time.time() - self._current_start_time) * 1000)
        self._current_compacted_count = compacted_count
        self._current_discarded_count = discarded_count

    def fail_compaction(self) -> None:
        """压缩失败 — 记录失败状态和耗时

        对标 Cline CompactionStateManager.failCompaction()。
        由 ContextCompactor.before_model 在压缩异常时调用。
        """
        import time as _time

        self._current_status = "failed"
        if self._current_start_time > 0:
            self._current_elapsed_ms = int((_time.time() - self._current_start_time) * 1000)

    def project(self):
        """返回压缩状态快照 — 对标 Cline CompactionStateManager.project()

        快照是只读的，前端可定期查询显示进度。
        返回 CompactionStateSnapshot，包含:
            - original_count: 原始消息数
            - compacted_count: 压缩后消息数
            - discarded_count: 被丢弃的消息数
            - elapsed_ms: 压缩耗时（毫秒）
            - status: 压缩状态（pending / running / completed / failed）
            - system_prompt_preserved: system_prompt 是否被保留

        Returns:
            CompactionStateSnapshot 实例（frozen，不可变）
        """
        from agent.types import CompactionStateSnapshot

        return CompactionStateSnapshot(
            original_count=self._current_original_count,
            compacted_count=self._current_compacted_count,
            discarded_count=self._current_discarded_count,
            elapsed_ms=self._current_elapsed_ms,
            status=self._current_status,
            system_prompt_preserved=bool(self.system_prompt),
        )


def is_compaction_summary_message(message: AgentMessage) -> bool:
    """判断消息是否是压缩摘要消息 — Stage 4.7 (J6) 新增

    对标 Cline compaction-shared.ts:197-203 isCompactionSummaryMessage。

    基于 message.metadata.kind == "compaction_summary" 识别，
    用于 _is_safe_cut_boundary / _find_cut_index 排除 summary 消息作为切割边界，
    以及 state-aware 重新压缩时跳过已有 summary。

    Args:
        message: 待检测的消息

    Returns:
        True 如果是压缩摘要消息
    """
    return message.metadata.get("kind") == "compaction_summary"


class ContextCompactor:
    """上下文压缩器 — 对标 Cline compaction.ts

    当对话历史的 token 数超过阈值时，压缩旧消息:
        1. 估算消息 token 数
        2. 用 _find_cut_index 找安全切割边界（不 orphan tool_use/tool_result）
        3. 旧消息生成摘要替换（含工具活动摘要 + LLM 结构化摘要）
        4. 保留最近 N 条 assistant 文本

    Phase 16 改造（修复 B2/B3）:
        - 参数对齐 Cline: max_input_tokens=128000, trigger_ratio=0.9, preserve_recent_tokens=20000
        - 补齐 _truncate_tool_results: 截断 tool_result 内容防止撑爆上下文
        - 补齐 _is_safe_cut_boundary: 安全切割边界检测（assistant 或 turn_start）
        - 补齐 _find_cut_index: 找安全切割点（不 orphan tool_use/tool_result）
        - 补齐 _summarize_tool_activity: 提取 readFiles/editedFiles/commands 摘要
        - 补齐 _build_dropped_work_summary_block: 构建 <SYSTEM_NOTICE> 摘要块
        - 补齐 _build_summary_request: 构建结构化 LLM 摘要 prompt（Goal/State/Highlights/Next/Files）
        - 补齐 _ensure_files_section: 确保摘要含 Files 段
        - PRESERVED_ASSISTANT_TEXT_COUNT = 3: 保留最近 3 条 assistant 文本

    Phase 13 改造点:
        1. 接入 Qwen 实现 LLM 摘要（替代 _simple_summary 作为默认策略）
        2. 实现 before_model hook，自动接入 runtime（无需手动调用 compact）
        3. 保留 _simple_summary 作为 fallback（agentic 失败时使用）

    对标 Cline:
        - 触发条件: requestInputTokens >= maxInputTokens * COMPACTION_TRIGGER_RATIO
        - 策略: agentic（用 LLM 生成摘要），失败时 fallback 到 basic
        - 接入方式: createContextCompactionPrepareTurn → before_model hook
        - state-aware: 通过 CompactionStateManager 持久化摘要，避免每次都从完整历史重新压缩

    用法（Phase 13 推荐方式 — 作为 before_model hook 自动触发）:
        compactor = ContextCompactor(model=qwen_model)
        runtime.register_hooks(AgentHooks(before_model=compactor.before_model))

    用法（手动调用，兼容旧代码）:
        compactor = ContextCompactor(model=qwen_model)
        if compactor.should_compact(messages):
            messages = await compactor.compact(messages)
    """

    def __init__(
        self,
        model: AgentModel | None = None,
        max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS,
        trigger_ratio: float = _DEFAULT_COMPACTION_TRIGGER_RATIO,
        keep_recent: int = _DEFAULT_KEEP_RECENT,
        summary_max_tokens: int = _DEFAULT_SUMMARY_MAX_TOKENS,
        preserve_recent_tokens: int = _DEFAULT_PRESERVE_RECENT_TOKENS,
        state_manager: CompactionStateManager | None = None,
        enable_budget_projection: bool = True,
        projection_ratio: float = _DEFAULT_PROJECTION_RATIO,
        tool_result_history_max: int = _DEFAULT_TOOL_RESULT_HISTORY_MAX,
        emit_event: Callable[[Any], Awaitable[None]] | None = None,
    ) -> None:
        """初始化上下文压缩器

        Args:
            model: LLM 适配器（Phase 13 新增），用于生成 agentic 摘要。
                   None 时退化为 basic 策略（仅用 _simple_summary）。
            max_input_tokens: 最大输入 token 数（对应模型的 context window），Phase 16 对齐 Cline 默认 128000
            trigger_ratio: 压缩触发比例（0-1），Phase 16 对齐 Cline 默认 0.9
            keep_recent: 压缩后保留的最近消息数（向后兼容，优先用 preserve_recent_tokens）
            summary_max_tokens: 摘要最大 token 数，Phase 16 对齐 Cline 默认 1024
            preserve_recent_tokens: 压缩后保留的最近 token 数，Phase 16 新增，对标 Cline DEFAULT_PRESERVE_RECENT_TOKENS
            state_manager: 压缩状态管理器，None 时每次从完整历史重新压缩
            enable_budget_projection: Phase 29.4 新增，是否启用提前压缩（基于未来 token 投影）
            projection_ratio: Phase 29.4 新增，提前压缩触发比例（与 trigger_ratio 相乘）
            tool_result_history_max: Phase 29.4 新增，估算 tool_result 均值时保留的最近样本数
            emit_event: Stage 4.8 (J20) 新增，压缩事件 emit 回调（async），
                        None 时退化为仅日志输出；传入时在压缩生命周期 emit 对应事件。
                        对标 Cline context.emitStatusNotice?.(...)
        """
        self.model = model
        self.max_input_tokens = max_input_tokens
        self.trigger_ratio = trigger_ratio
        self.keep_recent = keep_recent
        self.summary_max_tokens = summary_max_tokens
        self.preserve_recent_tokens = preserve_recent_tokens
        self._trigger_tokens = int(max_input_tokens * trigger_ratio)
        self.state_manager = state_manager
        # Phase 29.4: budget-projection 配置
        self.enable_budget_projection = enable_budget_projection
        self.projection_ratio = projection_ratio
        self.tool_result_history_max = tool_result_history_max
        self._projection_trigger_tokens = int(self._trigger_tokens * projection_ratio)
        # 最近一次压缩的原因（用于日志和调试）
        self._last_compaction_reason: str = ""
        # Stage 4.8 (J20): 压缩事件 emit 回调 — 对标 Cline emitStatusNotice
        self.emit_event = emit_event

    def should_compact(
        self,
        messages: list[AgentMessage],
        tools: list[AgentToolDefinition] | None = None,
        intent: Any = None,
        system_prompt: str | None = None,
    ) -> bool:
        """判断是否需要压缩 — 对标 Cline shouldCompact + Phase 29.4 budget-projection

        两级触发策略:
            1. 常规压缩: 当前消息 token >= trigger_tokens（保持向后兼容）
            2. 提前压缩: 启用 budget_projection 时，若投影总 token >= projection_trigger_tokens，
               也触发压缩（避免下一轮注入 tool_result 后立即超限）

        Phase 33.3 增强:
            - 新增 intent 参数（BudgetPolicyIntent），允许调用方按场景选择投影策略
            - 默认 None 时使用 NORMAL_PROVIDER_REQUEST（保守估算，保留 thinking 块），
              因为投影目的是预判"下一轮请求（未压缩状态）是否会超限"，
              应按未压缩的真实占用估算，避免"该压缩时不压缩"

        Stage 4.1 (J4) 增强:
            - 新增 system_prompt 参数，对齐 Cline estimateRequestInputTokens 语义
            - 常规触发路径的阈值比较改用 request_tokens = total_tokens + system_prompt_tokens
            - system_prompt 为 None 时退化为原行为（request_tokens = total_tokens）
            - budget_projection 分支的 current_tokens 仍传 total_tokens（仅 messages），
              因为投影公式 projected = current + tools + avg_tool_result 已单独处理 tools，
              避免重复计入 system prompt

        Args:
            messages: 消息列表
            tools: 当前请求的工具定义列表（Phase 29.4 新增），
                   None 时不做提前压缩（仅用常规阈值）
            intent: Phase 33.3 新增，BudgetPolicyIntent 枚举值，控制投影时是否丢弃 thinking 块。
                    None 时默认 NORMAL_PROVIDER_REQUEST（保守估算，保留所有内容）。
                    调用方可传入 BASIC_COMPACTION_PROJECTION / AGENTIC_SUMMARY 做"压缩后"
                    占用估算（更激进，可能延迟触发压缩）。
            system_prompt: Stage 4.1 新增，当前请求的 system prompt 文本。
                           对标 Cline estimateRequestInputTokens({systemPrompt, messages, tools})，
                           常规阈值比较纳入 system prompt token 估算，避免长 system prompt
                           导致延迟触发压缩。

        Returns:
            True 表示需要压缩
        """
        # 至少要有 keep_recent 条消息才考虑压缩
        if len(messages) <= self.keep_recent:
            return False

        total_tokens = estimate_messages_tokens(messages)

        # Stage 4.1 (J4): 常规触发路径纳入 system prompt token 估算
        # 对标 Cline requestInputTokens = estimateRequestInputTokens({systemPrompt, messages, tools})
        # system_prompt 为 None 时退化为原行为
        if system_prompt:
            system_prompt_tokens = estimate_tokens(system_prompt)
            request_tokens = total_tokens + system_prompt_tokens
        else:
            request_tokens = total_tokens

        # 1. 常规压缩触发
        if request_tokens >= self._trigger_tokens:
            self._last_compaction_reason = "threshold_exceeded"
            return True

        # 2. Phase 29.4: budget-projection 提前压缩触发
        if self.enable_budget_projection and tools is not None:
            # Phase 33.3: 默认 NORMAL_PROVIDER_REQUEST（保守估算，保留 thinking 块）
            # 投影目的是预判"下一轮请求（未压缩）是否超限"，应用未压缩状态估算
            effective_intent = intent
            if effective_intent is None:
                try:
                    from agent.budget_policy import BudgetPolicyIntent
                    effective_intent = BudgetPolicyIntent.NORMAL_PROVIDER_REQUEST
                except Exception:
                    effective_intent = None
            # 注: current_tokens 仍传 total_tokens（仅 messages），
            # 投影公式 projected = current + tools + avg_tool_result 已单独处理 tools
            projected_total = self._project_future_usage(
                messages, tools, total_tokens, intent=effective_intent,
            )
            if projected_total >= self._projection_trigger_tokens:
                logger.info(
                    "ContextCompactor: budget_projection 触发提前压缩 "
                    "(current=%d, projected=%d, projection_trigger=%d, trigger=%d, intent=%s)",
                    total_tokens, projected_total,
                    self._projection_trigger_tokens, self._trigger_tokens,
                    getattr(effective_intent, "value", "none"),
                )
                self._last_compaction_reason = "budget_projection"
                return True

        return False

    def _project_future_usage(
        self,
        messages: list[AgentMessage],
        tools: list[AgentToolDefinition],
        current_tokens: int | None = None,
        intent: Any = None,
    ) -> int:
        """估算未来一轮的 token 占用 — Phase 29.4 新增，对标 Cline project

        Phase 33.3 增强：接受 BudgetPolicyIntent 参数，按意图调整投影策略。
        - intent=None 或 normal-provider-request: 仅估算 token，不修改消息
        - intent=agentic-summary / basic-compaction-projection:
          先按策略丢弃 thinking 块，再估算（更贴近压缩后的真实占用）

        投影公式:
            projected = current_tokens
                      + tools_description_tokens      # 工具描述占用
                      + expected_next_tool_result_tokens  # 预期下一轮 tool_result

        tool_result 均值从最近 N 个 tool_result 消息估算（N=tool_result_history_max）。
        无历史 tool_result 时使用保守默认值（0，避免误触发）。

        Args:
            messages: 当前消息列表（用于提取历史 tool_result）
            tools: 当前请求的工具定义列表
            current_tokens: 已计算的当前消息 token 数，None 时重新计算
            intent: Phase 33.3 新增，BudgetPolicyIntent 枚举值。
                    为 agentic-summary / basic-compaction-projection 时，
                    先丢弃 thinking 块再估算（更贴近压缩后真实占用）；
                    None 或 normal-provider-request 时保留所有内容。

        Returns:
            预计下一轮总 token 数
        """
        # Phase 33.3: 按意图应用预算策略（丢弃 thinking 块等）
        effective_messages = messages
        if intent is not None:
            try:
                from agent.budget_policy import (
                    BudgetPolicyIntent,
                    apply_budget_policy,
                )
                # 仅在压缩意图下应用策略（normal-provider-request 不修改消息）
                if intent in (
                    BudgetPolicyIntent.AGENTIC_SUMMARY,
                    BudgetPolicyIntent.BASIC_COMPACTION_PROJECTION,
                ):
                    effective_messages = apply_budget_policy(messages, intent)
            except Exception as e:
                logger.debug("budget_projection: apply_budget_policy 失败，使用原始消息: %s", e)
                effective_messages = messages

        if current_tokens is None:
            current_tokens = estimate_messages_tokens(effective_messages)
        elif effective_messages is not messages:
            # 调用方传入了 current_tokens 但策略调整了消息，需重新计算
            current_tokens = estimate_messages_tokens(effective_messages)

        # 工具描述 token: 估算每个 tool 的 name + description + input_schema JSON 字符数
        tools_tokens = 0
        for tool in tools:
            # name + description
            tools_tokens += estimate_tokens(tool.name or "")
            tools_tokens += estimate_tokens(tool.description or "")
            # input_schema 序列化为 JSON 字符串后估算
            try:
                schema_json = json.dumps(tool.input_schema or {}, ensure_ascii=False)
                tools_tokens += estimate_tokens(schema_json)
            except Exception:
                pass

        # 历史 tool_result 平均 token 数
        tool_result_samples: list[int] = []
        for msg in reversed(effective_messages):
            for part in msg.content:
                if isinstance(part, ToolResultPart):
                    # 提取 tool_result 的 output 文本估算 token
                    output = part.output
                    if isinstance(output, str):
                        sample = estimate_tokens(output)
                    elif isinstance(output, dict):
                        try:
                            sample = estimate_tokens(json.dumps(output, ensure_ascii=False))
                        except Exception:
                            sample = 0
                    else:
                        sample = estimate_tokens(str(output or ""))
                    tool_result_samples.append(sample)
                    if len(tool_result_samples) >= self.tool_result_history_max:
                        break
            if len(tool_result_samples) >= self.tool_result_history_max:
                break

        if tool_result_samples:
            avg_tool_result = sum(tool_result_samples) // len(tool_result_samples)
        else:
            # 无历史样本时不假设 tool_result 占用（保守策略）
            avg_tool_result = 0

        projected = current_tokens + tools_tokens + avg_tool_result
        logger.debug(
            "budget_projection: current=%d + tools=%d + avg_tool_result=%d = projected=%d "
            "(samples=%d, projection_trigger=%d)",
            current_tokens, tools_tokens, avg_tool_result, projected,
            len(tool_result_samples), self._projection_trigger_tokens,
        )
        return projected

    async def before_model(self, ctx: BeforeModelContext) -> BeforeModelResult | None:
        """before_model hook — Phase 13 新增，对标 Cline createContextCompactionPrepareTurn

        每轮调 LLM 前自动检查:
            1. 加载上次保存的压缩状态（state-aware）
            2. 估算 messages token 数
            3. 超过阈值则压缩
            4. 保存新的压缩状态
            5. 返回修改后的 messages

        策略:
            - model 存在时优先用 LLM 生成摘要（agentic，对标 runAgenticCompaction）
            - LLM 失败或 model 为 None 时回退到 basic 策略（_simple_summary）

        Stage 11.2 (J12) 增强:
            - 接收 ctx.abort_signal 并透传到 compact 方法
            - AbortedError 不触发 fallback（用户中止应立即生效，不浪费时间走 fallback）
            - fallback 路径在关键步骤前检查 abort_signal，触发时抛 AbortedError

        Args:
            ctx: before_model 钩子上下文，包含 request / session_id / abort_signal

        Returns:
            BeforeModelResult(messages=compacted) 或 None（无需压缩）
        """
        messages = list(ctx.request.messages)
        session_id = ctx.session_id
        # Stage 11.2 (J12): 获取 abort_signal — None 时 fallback 不检查中止
        abort_signal = ctx.abort_signal

        # state-aware: 加载并应用上次保存的摘要状态
        state: CompactionState | None = None
        if self.state_manager and session_id:
            state = self.state_manager.load(session_id)
            # 防御性校验：summary_message 必须非空，compacted_count 必须合法
            if (
                state
                and state.summary_message is not None
                and isinstance(state.compacted_count, int)
                and 0 < state.compacted_count < len(messages)
            ):
                messages = [state.summary_message] + messages[state.compacted_count:]
                logger.info(
                    "ContextCompactor: 应用已有摘要状态，%d 条原始消息已被摘要替代",
                    state.compacted_count,
                )
            elif state:
                logger.warning(
                    "ContextCompactor: 忽略不合法的摘要状态 "
                    "(compacted_count=%s, messages=%d)",
                    state.compacted_count, len(messages),
                )

        # Phase 29.4: should_compact 接受 tools 参数，支持 budget-projection 提前压缩
        # Phase 33.3: should_compact 默认用 NORMAL_PROVIDER_REQUEST（保守估算，保留 thinking 块）
        # 投影目的是预判"下一轮请求（未压缩状态）是否超限"，应用未压缩状态估算
        # Stage 4.1 (J4): 传入 system_prompt，对齐 Cline estimateRequestInputTokens 语义
        tools = list(ctx.request.tools) if ctx.request.tools else None
        if not self.should_compact(
            messages, tools=tools, system_prompt=ctx.request.system_prompt,
        ):
            # Stage 4.8 (J20): emit skipped 事件 — 对标 Cline compaction-skipped
            if self.emit_event is not None:
                from agent.events import make_compaction_skipped
                try:
                    await self.emit_event(make_compaction_skipped(
                        snapshot=ctx.snapshot,
                        reason="below-threshold",
                        max_input_tokens=self.max_input_tokens,
                    ))
                except Exception as e:
                    logger.warning("ContextCompactor: emit compaction-skipped 失败: %s", e)
            return None

        # Phase 29.4: 日志带上 compaction_reason，便于调试
        compaction_reason = self._last_compaction_reason or "unknown"
        logger.info(
            "ContextCompactor: 触发上下文压缩 (messages=%d, tokens~%d, reason=%s)",
            len(messages),
            estimate_messages_tokens(messages),
            compaction_reason,
        )

        # Stage 4.8 (J20): emit started 事件 — 对标 Cline compacting/auto-compacting
        # Stage 11.3 (J13): 附加 CompactionStateSnapshot（若 state_manager 可用）
        if self.emit_event is not None:
            from agent.events import make_compaction_started
            try:
                await self.emit_event(make_compaction_started(
                    snapshot=ctx.snapshot,
                    reason="auto-compaction",
                    trigger_tokens=self._trigger_tokens,
                    # 压缩后目标约 70%（保留 30% 余量给后续对话）
                    target_tokens=int(self.max_input_tokens * self.trigger_ratio * 0.7),
                    max_input_tokens=self.max_input_tokens,
                    compaction_snapshot=(
                        self.state_manager.project() if self.state_manager is not None else None
                    ),
                ))
            except Exception as e:
                logger.warning("ContextCompactor: emit compaction-started 失败: %s", e)

        # Stage 11.3 (J13): 压缩生命周期管理 — 对标 Cline CompactionStateManager
        # 记录压缩开始时间和原始消息数，project() 投影给前端
        if self.state_manager is not None:
            self.state_manager.start_compaction(
                original_count=len(messages),
                system_prompt=ctx.request.system_prompt or "",
            )

        try:
            if self.model is not None:
                # 优先用 LLM 生成摘要 — 对标 runAgenticCompaction
                # Phase 29.3: 用 partial 绑定 session_id，让 _llm_summarize 能取 tracker 数据
                # Stage 11.2 (J12): 透传 abort_signal 到 compact，让 fallback 路径能检查中止
                import functools
                summarize_func = functools.partial(self._llm_summarize, session_id=session_id)
                compacted = await self.compact(
                    messages,
                    summarize_func=summarize_func,
                    session_id=session_id,
                    abort_signal=abort_signal,
                )
            else:
                # 无 model 时退化为 basic 策略
                compacted = await self.compact(
                    messages, summarize_func=None, session_id=session_id,
                    abort_signal=abort_signal,
                )
        except AbortedError as abort_err:
            # Stage 11.2 (J12): 用户中止不触发 fallback，直接向上抛出
            # 对标 Cline compaction-runner.ts: AbortedError 不走 fallback 路径
            # runtime 主循环会捕获并设置 status="aborted"
            logger.info("ContextCompactor: 压缩被用户中止，不走 fallback")
            # Stage 11.3 (J13): 记录失败状态并 emit failed 事件
            if self.state_manager is not None:
                self.state_manager.fail_compaction()
            if self.emit_event is not None:
                from agent.events import make_compaction_failed
                try:
                    await self.emit_event(make_compaction_failed(
                        snapshot=ctx.snapshot,
                        reason="aborted",
                        error=str(abort_err),
                        max_input_tokens=self.max_input_tokens,
                        compaction_snapshot=(
                            self.state_manager.project()
                            if self.state_manager is not None else None
                        ),
                    ))
                except Exception as e:
                    logger.warning("ContextCompactor: emit compaction-failed 失败: %s", e)
            raise
        except Exception as e:
            logger.warning(
                "ContextCompactor: LLM 摘要失败，回退到 basic 策略: %s", e,
            )
            # 对标 Cline: agentic 失败时 fallback 到 basic
            # Stage 11.2 (J12): fallback 也接收 abort_signal，关键步骤前检查
            try:
                compacted = await self.compact(
                    messages, summarize_func=None, session_id=session_id,
                    abort_signal=abort_signal,
                )
            except Exception as fallback_err:
                # Stage 11.3 (J13): fallback 也失败时记录状态并 emit failed 事件
                if self.state_manager is not None:
                    self.state_manager.fail_compaction()
                if self.emit_event is not None:
                    from agent.events import make_compaction_failed
                    try:
                        await self.emit_event(make_compaction_failed(
                            snapshot=ctx.snapshot,
                            reason="fallback-failed",
                            error=str(fallback_err),
                            max_input_tokens=self.max_input_tokens,
                            compaction_snapshot=(
                                self.state_manager.project()
                                if self.state_manager is not None else None
                            ),
                        ))
                    except Exception as emit_err:
                        logger.warning("ContextCompactor: emit compaction-failed 失败: %s", emit_err)
                raise

        # Stage 11.3 (J13): 压缩完成 — 记录最终状态和耗时
        if self.state_manager is not None:
            discarded_count = max(0, len(messages) - len(compacted))
            self.state_manager.finish_compaction(
                compacted_count=len(compacted),
                discarded_count=discarded_count,
            )

        # state-aware: 保存新的压缩状态
        if self.state_manager and session_id:
            # compacted = [summary_message] + recent_messages
            # recent_messages 长度 = len(compacted) - 1
            # cut_index = len(messages) - len(recent_messages)
            recent_len = len(compacted) - 1
            cut_index = len(messages) - recent_len
            base_count = state.compacted_count if state else 0
            # 若已存在旧摘要，compacted[0] 会替代它，需减 1 避免重复计数
            new_compacted_count = base_count + cut_index - (1 if state else 0)
            new_compacted_count = max(new_compacted_count, 0)

            new_state = CompactionState(
                summary_message=compacted[0],
                compacted_count=new_compacted_count,
            )
            self.state_manager.save(session_id, new_state)
            logger.info(
                "ContextCompactor: 保存摘要状态，累计 %d 条原始消息被摘要替代",
                new_compacted_count,
            )

        logger.info(
            "ContextCompactor: 压缩完成 (messages=%d → %d)",
            len(messages), len(compacted),
        )

        # Stage 4.8 (J20): emit completed 事件 — 对标 Cline compacted/auto-compacted
        # Stage 11.3 (J13): 附加 CompactionStateSnapshot
        if self.emit_event is not None:
            from agent.events import make_compaction_completed
            try:
                await self.emit_event(make_compaction_completed(
                    snapshot=ctx.snapshot,
                    reason="auto-compaction",
                    tokens_before=estimate_messages_tokens(messages),
                    tokens_after=estimate_messages_tokens(compacted),
                    messages_before=len(messages),
                    messages_after=len(compacted),
                    max_input_tokens=self.max_input_tokens,
                    compaction_snapshot=(
                        self.state_manager.project() if self.state_manager is not None else None
                    ),
                ))
            except Exception as e:
                logger.warning("ContextCompactor: emit compaction-completed 失败: %s", e)

        return BeforeModelResult(messages=compacted)

    async def compact(
        self,
        messages: list[AgentMessage],
        summarize_func=None,
        session_id: str | None = None,
        abort_signal: Any = None,
    ) -> list[AgentMessage]:
        """压缩对话历史 — 对标 Cline compaction

        Phase 16 重构（修复 B3）:
            1. 用 _find_cut_index 找安全切割边界（不 orphan tool_use/tool_result）
            2. 对旧消息调用 _summarize_tool_activity 提取工具活动摘要
            3. 保留最近 PRESERVED_ASSISTANT_TEXT_COUNT 条 assistant 文本
            4. 用 _build_dropped_work_summary_block 构建 <SYSTEM_NOTICE> 摘要块
            5. 如果有 LLM，用 _build_summary_request 生成结构化摘要（Goal/State/Highlights/Next/Files）

        Phase 29.3 增强:
            - 若 session_id 已知，优先从 FileContextTracker 获取文件列表（跨压缩周期保留）
            - tracker 无数据时回退到 _summarize_tool_activity 从消息扫描

        Stage 11.2 (J12) 增强:
            - 新增 abort_signal 参数，让 fallback 路径能响应中止信号
            - 在关键步骤前（截断、切割、摘要生成）检查 abort_signal
            - 触发时抛 AbortedError，与 agentic 路径行为一致
            - None 时保持原行为（向后兼容，无 abort 检查）

        Args:
            messages: 原始消息列表
            summarize_func: 摘要生成函数 (old_messages: list[AgentMessage]) -> str
                           如果为 None，使用简单的文本拼接摘要
            session_id: 会话 ID（Phase 29.3 新增），用于从 FileContextTracker 取文件状态
            abort_signal: 中止信号（Stage 11.2 新增），asyncio.Event，
                         None 时不检查中止（向后兼容）

        Returns:
            压缩后的消息列表: [摘要消息] + 最近消息
        """
        if len(messages) <= self.keep_recent:
            return messages

        # Stage 11.2 (J12): 关键步骤前检查 abort_signal
        # 对标 Cline compaction-runner.ts fallback 路径订阅 abort
        if abort_signal is not None and abort_signal.is_set():
            raise AbortedError("compaction aborted by user")

        # Phase 16: 先截断过长的 tool_result 内容 — 对标 Cline _truncate_tool_results
        messages = self._truncate_tool_results(messages)

        # Stage 11.2 (J12): 截断后再次检查（截断可能耗时）
        if abort_signal is not None and abort_signal.is_set():
            raise AbortedError("compaction aborted by user")

        # Phase 16: 用安全切割边界找分割点 — 对标 Cline findCutIndex
        cut_index = self._find_cut_index(messages)
        if cut_index <= 0:
            # 无法找到安全切割点，返回原消息
            return messages

        old_messages = messages[:cut_index]
        recent_messages = messages[cut_index:]

        # Stage 11.2 (J12): 切割后检查（find_cut_index 可能遍历大量消息）
        if abort_signal is not None and abort_signal.is_set():
            raise AbortedError("compaction aborted by user")

        # Stage 4.2 (J15): 计算压缩前 token 数 — 用于 metadata.tokensBefore
        # 对标 Cline buildSummaryMessage 的 tokensBefore 字段
        tokens_before = estimate_messages_tokens(old_messages)

        # Phase 29.3: 优先从 FileContextTracker 获取文件活动摘要
        # tracker 跨压缩周期保留文件状态，比临时扫消息更准确
        tool_activity = self._summarize_tool_activity_v2(old_messages, session_id)

        # Phase 16: 保留最近 N 条 assistant 文本内容 — 对标 Cline PRESERVED_ASSISTANT_TEXT_COUNT
        preserved_responses = self._extract_preserved_assistant_texts(old_messages)

        # 生成摘要
        if summarize_func:
            try:
                summary_text = await summarize_func(old_messages)
                # Phase 16: 确保摘要含 Files 段 — 对标 Cline ensureFilesSection
                summary_text = self._ensure_files_section(summary_text, tool_activity)
            except AbortedError:
                # Stage 11.2 (J12): agentic 摘要被中止，不退化为 simple_summary
                # 直接向上抛出，让 before_model 的 except AbortedError 处理
                raise
            except Exception as e:
                logger.warning(f"摘要生成失败，使用简单摘要: {e}")
                summary_text = self._simple_summary(old_messages)
        else:
            # Stage 11.2 (J12): fallback 路径（无 summarize_func）关键步骤前检查 abort
            # _simple_summary 遍历所有消息生成文本，可能耗时，需检查中止
            if abort_signal is not None and abort_signal.is_set():
                raise AbortedError("compaction fallback aborted by user")
            summary_text = self._simple_summary(old_messages)

        # Stage 11.2 (J12): 摘要生成后检查（agentic 摘要可能耗时较长）
        if abort_signal is not None and abort_signal.is_set():
            raise AbortedError("compaction aborted by user")

        # Phase 16: 构建 <SYSTEM_NOTICE> 摘要块 — 对标 Cline buildDroppedWorkSummaryBlock
        dropped_work_block = self._build_dropped_work_summary_block(
            tool_activity, preserved_responses,
        )

        # 创建摘要消息
        # Stage 4.2 (J15): 添加 metadata.kind = "compaction_summary" 标记
        # 对标 Cline compaction-shared.ts:720-740 buildSummaryMessage 的 metadata 结构
        # 下游通过 is_compaction_summary_message() 识别（关联 J6 切割边界、J13 状态投影）
        import time as _time
        summary_message = AgentMessage(
            role=MessageRole.USER,
            content=[TextPart(text=(
                "# 对话历史摘要\n\n"
                f"{summary_text}\n\n"
                f"{dropped_work_block}\n\n"
                "--- 以上为之前的对话摘要，以下是最近的对话 ---"
            ))],
            metadata={
                "kind": "compaction_summary",
                "summary": summary_text,
                "details": {
                    "readFiles": tool_activity.get("readFiles", []),
                    "editedFiles": tool_activity.get("editedFiles", []),
                    "commands": tool_activity.get("commands", []),
                },
                "tokensBefore": tokens_before,
                # 毫秒时间戳，对齐 Cline Date.now()
                "generatedAt": int(_time.time() * 1000),
            },
        )

        compacted = [summary_message] + recent_messages

        # P1-8: build_budget_projection 安全阀 — 对标 Cline basic-compaction.ts L606-619
        # 主压缩路径（_find_cut_index + summary）已保留语义，此处仅做 token 预算降级：
        # 当压缩后总 token 仍超过 trigger_tokens 时，调用 4 步流水线（drop_thinking +
        # drop_unsafe + truncate_text + remove_closure）确保最终消息 ≤ trigger_tokens，
        # 避免"压缩后仍超限"的边缘情况。status=="failed" 时仅记录 debug 日志，
        # 使用 best-effort 降级结果（与 Cline basic-compaction.ts 行为一致）。
        try:
            from agent.budget_policy import (
                BudgetPolicyIntent,
                build_budget_projection,
            )

            compacted_tokens = estimate_messages_tokens(compacted)
            # 仅当压缩后 token 超过 trigger_tokens 时才触发安全阀
            # （与 Cline 一致：已达标时直接跳过，避免不必要的裁剪）
            if compacted_tokens > self._trigger_tokens:
                # projection_target_tokens 上限 = trigger_tokens（硬性天花板）
                # 对齐 Cline: min(max(totalTargetTokens, totalTokens), triggerTokens)
                # Charles 简化：mandatory 内容即 compacted 本身，target 取 trigger_tokens
                projection_target_tokens = max(1, self._trigger_tokens)
                budgeted = build_budget_projection(
                    messages=compacted,
                    target_tokens=projection_target_tokens,
                    intent=BudgetPolicyIntent.BASIC_COMPACTION_PROJECTION,
                )
                if budgeted.status == "failed":
                    # 对标 Cline: failed 时仅记录 debug 日志，仍使用 best-effort 降级结果
                    logger.debug(
                        "ContextCompactor: budget_projection 安全阀返回 best-effort 降级 "
                        "(warnings=%s, projected_tokens=%d, target=%d, trigger=%d)",
                        [w.code for w in budgeted.warnings],
                        budgeted.estimated_tokens,
                        projection_target_tokens,
                        self._trigger_tokens,
                    )
                else:
                    logger.debug(
                        "ContextCompactor: budget_projection 安全阀生效 "
                        "(tokens_before=%d, tokens_after=%d, target=%d)",
                        compacted_tokens,
                        budgeted.estimated_tokens,
                        projection_target_tokens,
                    )
                # 使用安全阀处理后的消息（即使 failed 也是 best-effort 降级结果）
                if budgeted.messages and len(budgeted.messages) > 0:
                    compacted = budgeted.messages
        except Exception as e:
            # 安全阀失败不影响主压缩流程，仅记录告警
            logger.warning(
                "ContextCompactor: budget_projection 安全阀调用失败（已忽略，使用主压缩结果）: %s", e,
            )

        return compacted

    def _truncate_tool_results(self, messages: list[AgentMessage]) -> list[AgentMessage]:
        """截断过长的 tool_result 内容 — Phase 16 新增，对标 Cline truncateToolResultContentForCompaction

        防止长 tool_result 撑爆上下文。对每条消息中的 ToolResultPart，
        将 output 截断到 TOOL_RESULT_CHAR_LIMIT 字符。

        Stage 11.4 (J18) 增强:
            - 处理 content 中的 FilePart / ImagePart 类型
            - file: content 超过 MAX_FILE_DATA_LENGTH 时清空，保留 path
            - image: image 数据超过 MAX_IMAGE_DATA_LENGTH 时清空，保留 alt_text
            - 截断后在 content 末尾追加 [truncated] 标记，让 LLM 知道部分内容被截断

        Args:
            messages: 原始消息列表

        Returns:
            截断后的消息列表（浅拷贝，不修改原消息）
        """
        from agent.types import (
            FilePart,
            ImagePart,
            TextPart,
            ToolResultPart,
            clone_messages,
        )

        truncated = clone_messages(messages)
        for msg in truncated:
            for i, part in enumerate(msg.content):
                if not isinstance(part, ToolResultPart):
                    continue

                output = part.output
                # 1. 截断 string 类型 output（原有逻辑）
                if isinstance(output, str) and len(output) > TOOL_RESULT_CHAR_LIMIT:
                    msg.content[i] = ToolResultPart(
                        tool_call_id=part.tool_call_id,
                        tool_name=part.tool_name,
                        output=output[:TOOL_RESULT_CHAR_LIMIT] + f"\n...[truncated {len(output) - TOOL_RESULT_CHAR_LIMIT} chars]",
                        is_error=part.is_error,
                        metadata=part.metadata,
                    )
                    continue

                # Stage 11.4 (J18): 2. 处理 list[MessagePart] 类型 output
                # 对标 Cline compaction-truncator.ts 对 file/image 类型的专门处理
                if isinstance(output, list):
                    new_parts: list = []
                    any_truncated = False
                    for sub in output:
                        if isinstance(sub, FilePart):
                            content_str = sub.content if isinstance(sub.content, str) else ""
                            if len(content_str) > MAX_FILE_DATA_LENGTH:
                                any_truncated = True
                                new_parts.append(FilePart(
                                    path=sub.path,
                                    content="",
                                    truncated=True,
                                    truncate_reason="file_data_exceeds_limit",
                                ))
                            else:
                                new_parts.append(sub)
                        elif isinstance(sub, ImagePart):
                            # image 可能是 str（base64）或 bytes
                            if isinstance(sub.image, (str, bytes)):
                                img_len = len(sub.image)
                            else:
                                img_len = 0
                            if img_len > MAX_IMAGE_DATA_LENGTH:
                                any_truncated = True
                                new_parts.append(ImagePart(
                                    image=b"",
                                    media_type=sub.media_type,
                                    alt_text=sub.alt_text or "[image truncated]",
                                    truncated=True,
                                    truncate_reason="image_data_exceeds_limit",
                                ))
                            else:
                                new_parts.append(sub)
                        else:
                            new_parts.append(sub)

                    if any_truncated:
                        # 追加截断标记，让 LLM 知道部分内容被截断
                        new_parts.append(TextPart(
                            text="[truncated: file/image data exceeds limit]",
                        ))
                        msg.content[i] = ToolResultPart(
                            tool_call_id=part.tool_call_id,
                            tool_name=part.tool_name,
                            output=new_parts,
                            is_error=part.is_error,
                            metadata=part.metadata,
                        )
        return truncated

    def _is_safe_cut_boundary(self, message: AgentMessage) -> bool:
        """安全切割边界检测 — Phase 16 新增，对标 Cline isSafeCutBoundary

        一个切割边界是安全的，当从该边界开始保留尾部时，
        不会 orphan 一半的 tool_use/tool_result 对。

        规则（对标 Cline compaction-shared.ts:313-315）:
            - assistant 消息：安全（tool_use 和它的 tool_result 在同侧）
            - turn_start 消息（非 tool_result-only 的 user 消息）：安全
            - tool_result-only 的 user 消息：不安全（它的 tool_use 在前一条 assistant 中）

        Stage 4.7 (J6) 增强:
            - compaction_summary 消息不是 turn_start，不应作为安全切割边界
            - 对标 Cline isTurnStartMessage 中的 !isCompactionSummaryMessage
            - 依赖 4.2 给 summary_message 添加 metadata.kind = "compaction_summary"

        Args:
            message: 待检测的消息

        Returns:
            True 如果是安全切割边界
        """
        from agent.types import ToolCallPart, ToolResultPart

        # assistant 消息总是安全的
        if message.role == MessageRole.ASSISTANT:
            return True

        # user 消息：检查是否是 tool_result-only
        if message.role == MessageRole.USER:
            # 空内容视为安全
            if not message.content:
                return True
            # Stage 4.7 (J6): 压缩摘要消息不是 turn_start，不应作为安全切割边界
            # 对标 Cline isTurnStartMessage 中的 !isCompactionSummaryMessage
            if is_compaction_summary_message(message):
                return False
            # 如果所有 part 都是 ToolResultPart，则不安全
            all_tool_result = all(
                isinstance(part, ToolResultPart) for part in message.content
            )
            return not all_tool_result

        return False

    def _find_cut_index(self, messages: list[AgentMessage]) -> int:
        """找安全切割点 — Phase 16 新增，对标 Cline findCutIndex

        从尾部向前累计 token 数，找到满足 preserve_recent_tokens 的切割点，
        然后向前调整到最近的安全切割边界。

        规则（对标 Cline compaction-shared.ts:317-350）:
            1. 从尾部累计 token，直到达到 preserve_recent_tokens
            2. 切割点不能 orphan tool_use/tool_result 对
            3. 切割点不能在最后一个 typed user message 之后（保留完整 turn）

        Args:
            messages: 消息列表

        Returns:
            安全切割点索引，0 表示无法安全切割
        """
        if not messages:
            return 0

        # 从尾部累计 token
        total = 0
        candidate = len(messages)
        for index in range(len(messages) - 1, -1, -1):
            total += estimate_message_tokens(messages[index])
            candidate = index
            if total >= self.preserve_recent_tokens:
                break

        if candidate < 0:
            return 0

        # Stage 4.7 (J6): candidate=0 时仍要检查 messages[0] 是否是安全切割边界
        # 若 messages[0] 是 compaction_summary（非安全边界），返回 -1 表示无法切割，
        # 调用者会因 cut_index <= 0 而保留原消息，避免把 summary 当作切割点
        if candidate == 0:
            if not self._is_safe_cut_boundary(messages[0]):
                return -1
            return 0

        # 找最后一个 typed user message（非 tool_result-only）
        last_turn_start = -1
        for index in range(len(messages) - 1, -1, -1):
            msg = messages[index]
            if msg.role == MessageRole.USER and self._is_safe_cut_boundary(msg):
                last_turn_start = index
                break

        # 切割点不能在最后一个 typed user message 之后
        if last_turn_start > 0:
            cut = min(candidate, last_turn_start)
        else:
            cut = candidate

        # 向前调整到最近的安全切割边界
        while cut > 0 and not self._is_safe_cut_boundary(messages[cut]):
            cut -= 1

        # Stage 4.7 (J6): 调整后若 cut=0 但 messages[0] 不是安全边界（如 compaction_summary），
        # 返回 -1 表示无法找到安全切割点
        if cut == 0 and not self._is_safe_cut_boundary(messages[0]):
            return -1

        return cut

    def _summarize_tool_activity_v2(
        self,
        messages: list[AgentMessage],
        session_id: str | None = None,
    ) -> dict[str, list[str]]:
        """提取工具活动摘要（v2）— Phase 29.3 新增

        优先从 FileContextTracker 取文件列表（跨压缩周期保留），
        tracker 无数据时回退到消息扫描（_summarize_tool_activity）。

        Args:
            messages: 旧消息列表（用于 commands 提取和 fallback）
            session_id: 会话 ID，None 时直接走 fallback

        Returns:
            {"readFiles": [...], "editedFiles": [...], "commands": [...]}
            注：commands 始终从消息扫描（tracker 不记录命令）
        """
        # 始终从消息提取 commands（tracker 不记录命令）
        from_messages = self._summarize_tool_activity(messages)
        commands = from_messages.get("commands", [])

        # 优先从 tracker 取文件列表
        if session_id:
            try:
                from agent.file_context_tracker import get_tracker

                tracker = get_tracker(session_id)
                state = tracker.get_state()
                # tracker 中 created 也归入 editedFiles（压缩摘要不分 created/edited）
                edited = []
                for p in state.get("edited", []):
                    if p not in edited:
                        edited.append(p)
                for p in state.get("created", []):
                    if p not in edited:
                        edited.append(p)

                read_files = state.get("read", [])
                if read_files or edited:
                    logger.debug(
                        "ContextCompactor: 从 FileContextTracker 取文件状态 "
                        "(read=%d, edited=%d, session=%s)",
                        len(read_files), len(edited), session_id,
                    )
                    return {
                        "readFiles": read_files,
                        "editedFiles": edited,
                        "commands": commands,
                    }
            except Exception as e:
                logger.debug(
                    "ContextCompactor: 从 tracker 取文件失败，回退到消息扫描: %s", e,
                )

        # fallback: 用消息扫描结果
        return from_messages

    def _summarize_tool_activity(self, messages: list[AgentMessage]) -> dict[str, list[str]]:
        """提取工具活动摘要 — Phase 16 新增，对标 Cline summarizeToolActivity

        从消息列表中提取:
            - readFiles: 读取过的文件路径
            - editedFiles: 编辑过的文件路径
            - commands: 执行过的命令

        Stage 11.1 (J7) 增强: 路径后追加行号范围
            - read_files: path/to/file.py#L10-50（从 output 的 cat -n 行号提取）
            - editor: path/to/file.py#L100-150（从 output 的 diff @@ 提取）
            - apply_patch: path/to/file.py#L10-50（同 editor）
            - run_commands: 无行号（保留命令本身）

        Args:
            messages: 消息列表

        Returns:
            {"readFiles": [...], "editedFiles": [...], "commands": [...]}
        """
        from agent.types import ToolCallPart, ToolResultPart

        read_files: list[str] = []
        edited_files: list[str] = []
        commands: list[str] = []

        def push_unique(lst: list[str], value: str) -> None:
            v = value.strip()
            if v and v not in lst:
                lst.append(v)

        def collect_paths(value: Any) -> list[str]:
            """递归收集路径字段"""
            paths: list[str] = []
            if isinstance(value, str) and value.strip():
                paths.append(value)
            elif isinstance(value, list):
                for item in value:
                    paths.extend(collect_paths(item))
            elif isinstance(value, dict):
                for key in ("path", "file_path", "target_file", "new_file_path", "old_file_path"):
                    if key in value:
                        paths.extend(collect_paths(value[key]))
                if "files" in value and isinstance(value["files"], list):
                    for item in value["files"]:
                        if isinstance(item, dict) and "path" in item:
                            paths.extend(collect_paths(item["path"]))
                        elif isinstance(item, str):
                            paths.extend(collect_paths(item))
                if "file_paths" in value:
                    paths.extend(collect_paths(value["file_paths"]))
            return paths

        # Stage 11.1 (J7): 构建 tool_call_id → output 字符串映射，用于行号提取
        # 对标 Cline compaction-summarizer.ts 从工具结果解析行号范围
        tool_outputs: dict[str, str] = {}
        for msg in messages:
            for part in msg.content:
                if isinstance(part, ToolResultPart) and part.tool_call_id:
                    output = part.output
                    if isinstance(output, str):
                        tool_outputs[part.tool_call_id] = output
                    elif isinstance(output, dict):
                        # output 可能是 dict（如 {"content": "...", "path": "..."}）
                        for v in output.values():
                            if isinstance(v, str) and len(v) > len(tool_outputs.get(part.tool_call_id, "")):
                                tool_outputs[part.tool_call_id] = v
                                break

        def extract_line_range_from_read(output: str) -> str | None:
            """从 read_files 的 cat -n 风格输出提取行号范围 — Stage 11.1 新增

            output 格式: "     1\tcontent\n     2\tcontent\n..."
            或 LINE_NUMBER→content 格式

            Returns:
                "L{start}-{end}" 或 None（解析失败时）
            """
            import re
            # 匹配 cat -n 风格: 行首空格 + 数字 + tab/箭头
            line_pattern = re.compile(r"^\s*(\d+)[\t→]", re.MULTILINE)
            matches = line_pattern.findall(output)
            if not matches:
                return None
            line_nums = [int(m) for m in matches]
            return f"L{min(line_nums)}-{max(line_nums)}"

        def extract_line_range_from_diff(output: str) -> str | None:
            """从 editor/apply_patch 的 diff 输出提取行号范围 — Stage 11.1 新增

            output 格式: "@@ -start,len +start,len @@"

            Returns:
                "L{start}-{end}"（用 new chunk 的行号）或 None
            """
            import re
            # 匹配 @@ -old_start,old_len +new_start,new_len @@
            hunk_pattern = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
            matches = hunk_pattern.findall(output)
            if not matches:
                return None
            # 用 new chunk 的 start 和 len 计算末行
            starts = []
            ends = []
            for _old_start, new_start, new_len in matches:
                start = int(new_start)
                length = int(new_len) if new_len else 1
                starts.append(start)
                ends.append(start + length - 1)
            if not starts:
                return None
            return f"L{min(starts)}-{max(ends)}"

        for msg in messages:
            for part in msg.content:
                if not isinstance(part, ToolCallPart):
                    continue
                tool_name = part.tool_name
                tool_input = part.input or {}
                tool_output = tool_outputs.get(part.tool_call_id, "")

                if tool_name == "read_files" or tool_name == "file_read":
                    for p in collect_paths(tool_input):
                        # Stage 11.1: 追加行号范围
                        line_range = extract_line_range_from_read(tool_output) if tool_output else None
                        path_with_range = f"{p}#{line_range}" if line_range else p
                        push_unique(read_files, path_with_range)
                elif tool_name in ("editor", "apply_patch", "file_write"):
                    for p in collect_paths(tool_input):
                        # Stage 11.1: 追加行号范围（editor/apply_patch 用 diff 格式）
                        line_range = None
                        if tool_output:
                            if tool_name == "file_write":
                                line_range = extract_line_range_from_read(tool_output)
                            else:
                                line_range = extract_line_range_from_diff(tool_output)
                        path_with_range = f"{p}#{line_range}" if line_range else p
                        push_unique(edited_files, path_with_range)
                elif tool_name in ("run_commands", "exec"):
                    cmd_list = tool_input.get("commands") or tool_input.get("command") or ""
                    if isinstance(cmd_list, str):
                        cmd_list = [cmd_list]
                    if isinstance(cmd_list, list):
                        for cmd in cmd_list:
                            if isinstance(cmd, str) and cmd.strip():
                                truncated = cmd.strip()[:COMMAND_SUMMARY_CHAR_LIMIT]
                                if len(cmd.strip()) > COMMAND_SUMMARY_CHAR_LIMIT:
                                    truncated += "..."
                                push_unique(commands, truncated)

        return {
            "readFiles": read_files,
            "editedFiles": edited_files,
            "commands": commands,
        }

    def _extract_preserved_assistant_texts(self, messages: list[AgentMessage]) -> list[str]:
        """提取最近 N 条 assistant 文本内容 — Phase 16 新增，对标 Cline PRESERVED_ASSISTANT_TEXT_COUNT

        从消息列表尾部向前找最近的 PRESERVED_ASSISTANT_TEXT_COUNT 条 assistant 文本，
        用于在摘要中保留 agent 的最近回答。

        Args:
            messages: 消息列表

        Returns:
            最近 N 条 assistant 文本内容列表（按时间顺序，最旧在前）
        """
        preserved: list[str] = []
        for msg in reversed(messages):
            if msg.role != MessageRole.ASSISTANT:
                continue
            text = _extract_message_text(msg)
            if text.strip():
                preserved.insert(0, text)
            if len(preserved) >= PRESERVED_ASSISTANT_TEXT_COUNT:
                break
        return preserved

    def _build_dropped_work_summary_block(
        self,
        tool_activity: dict[str, list[str]],
        preserved_responses: list[str],
    ) -> str:
        """构建 <SYSTEM_NOTICE> 摘要块 — Phase 16 新增，对标 Cline buildDroppedWorkSummaryBlock

        格式（对标 Cline basic-compaction.ts:80-92）:
            <SYSTEM_NOTICE>
            Earlier context was compacted. Summary of your actions after the request above:
            Files read:
            - path1
            - path2

            Files edited:
            - path1

            Commands ran:
            - cmd1
            - cmd2

            Your recent responses:
            response1
            ---
            response2
            </SYSTEM_NOTICE>

        Args:
            tool_activity: _summarize_tool_activity 的返回值
            preserved_responses: _extract_preserved_assistant_texts 的返回值

        Returns:
            <SYSTEM_NOTICE> 摘要块文本
        """
        parts: list[str] = [
            "<SYSTEM_NOTICE>",
            "Earlier context was compacted. Summary of your actions after the request above:",
        ]

        # Files read
        read_files = tool_activity.get("readFiles", [])
        parts.append("Files read:")
        if read_files:
            for p in read_files:
                parts.append(f"- {p}")
        else:
            parts.append("- none")

        # Files edited
        edited_files = tool_activity.get("editedFiles", [])
        parts.append("\nFiles edited:")
        if edited_files:
            for p in edited_files:
                parts.append(f"- {p}")
        else:
            parts.append("- none")

        # Commands ran
        commands = tool_activity.get("commands", [])
        parts.append("\nCommands ran:")
        if commands:
            for c in commands:
                parts.append(f"- {c}")
        else:
            parts.append("- none")

        # Preserved responses
        if preserved_responses:
            parts.append("\nYour recent responses:")
            parts.append("\n---\n".join(preserved_responses))

        parts.append("</SYSTEM_NOTICE>")
        return "\n".join(parts)

    def _build_summary_request(
        self,
        previous_summary: str,
        conversation_text: str,
        file_ops: dict[str, list[str]],
    ) -> str:
        """构建结构化 LLM 摘要 prompt — Phase 16 新增，对标 Cline buildSummaryRequest

        格式（对标 Cline compaction-shared.ts:643-677）:
            Summarize this session for continuation. Be concise and factual.

            ## Goal
            One sentence: what is being built or fixed.

            ## State
            - Done: completed steps
            - In Progress: current work
            - Blocked: blockers or open questions

            ## Highlights
            Key technical choices or notable findings (omit if none).

            ## Next
            Immediate next steps.

            ## Files
            Read: file1, file2
            Edited: file1

            [Previous summary:]
            ...

            [Conversation:]
            ...

        Args:
            previous_summary: 之前的摘要文本（如有）
            conversation_text: 对话历史文本
            file_ops: {"readFiles": [...], "editedFiles": [...]}

        Returns:
            结构化摘要 prompt 文本
        """
        read_files_str = ", ".join(file_ops.get("readFiles", [])) or "none"
        edited_files_str = ", ".join(file_ops.get("editedFiles", [])) or "none"

        parts: list[str] = [
            "Summarize this session for continuation. Be concise and factual.",
            "",
            "## Goal",
            "One sentence: what is being built or fixed.",
            "",
            "## State",
            "- Done: completed steps",
            "- In Progress: current work",
            "- Blocked: blockers or open questions",
            "",
            "## Highlights",
            "Key technical choices or notable findings (omit if none).",
            "",
            "## Next",
            "Immediate next steps.",
            "",
            "## Files",
            f"Read: {read_files_str}",
            f"Edited: {edited_files_str}",
        ]

        if previous_summary.strip():
            parts.append("")
            parts.append(f"Previous summary:\n{previous_summary.strip()}")

        parts.append("")
        parts.append(f"Conversation:\n{conversation_text or '(empty)'}")

        return "\n".join(parts)

    def _ensure_files_section(
        self,
        summary: str,
        file_ops: dict[str, list[str]],
    ) -> str:
        """确保摘要含 Files 段 — Phase 16 新增，对标 Cline ensureFilesSection

        如果摘要中已含 ## Files 段，直接返回；否则追加 Files 段。

        Args:
            summary: LLM 生成的摘要文本
            file_ops: {"readFiles": [...], "editedFiles": [...]}

        Returns:
            含 Files 段的摘要文本
        """
        import re
        if re.search(r"^## Files$", summary, re.MULTILINE):
            return summary.strip()

        read_lines = file_ops.get("readFiles", [])
        edited_lines = file_ops.get("editedFiles", [])

        read_section = "\n".join(f"- {p}" for p in read_lines) if read_lines else "- none"
        edited_section = "\n".join(f"- {p}" for p in edited_lines) if edited_lines else "- none"

        files_section = (
            "## Files\n"
            f"Read:\n{read_section}\n"
            f"Modified:\n{edited_section}"
        )
        return f"{summary.strip()}\n\n{files_section}".strip()

    async def _llm_summarize(
        self,
        old_messages: list[AgentMessage],
        session_id: str | None = None,
    ) -> str:
        """用 LLM 生成结构化摘要 — Phase 13 新增，Phase 16 增强，对标 Cline runAgenticCompaction

        Phase 16 增强:
            - 使用 _build_summary_request 构建结构化摘要 prompt（Goal/State/Highlights/Next/Files）
            - 对标 Cline agentic-compaction.ts

        Phase 29.3 增强:
            - 接受 session_id 参数，优先从 FileContextTracker 取文件列表

        Args:
            old_messages: 需要被摘要的旧消息列表
            session_id: 会话 ID（Phase 29.3 新增），用于从 tracker 取文件状态

        Returns:
            LLM 生成的摘要文本，失败时回退到 _simple_summary
        """
        if self.model is None:
            return self._simple_summary(old_messages)

        # 构造对话历史文本
        history_text = self._format_messages_for_summary(old_messages)

        # Phase 29.3: 优先从 tracker 取文件操作（与 compact() 保持一致）
        tool_activity = self._summarize_tool_activity_v2(old_messages, session_id)
        file_ops = {
            "readFiles": tool_activity.get("readFiles", []),
            "editedFiles": tool_activity.get("editedFiles", []),
        }

        # Phase 16: 构建结构化摘要 prompt — 对标 Cline buildSummaryRequest
        summary_prompt = self._build_summary_request(
            previous_summary="",  # 暂无 previous summary 链
            conversation_text=history_text,
            file_ops=file_ops,
        )

        # 构造 LLM 请求
        request = AgentModelRequest(
            system_prompt="你是对话摘要助手，生成保留关键信息的简洁摘要。必须保留所有具体数字（股价、财务指标、日期）、关键结论和决策。",
            messages=[create_message(MessageRole.USER, [TextPart(text=summary_prompt)])],
            options={"max_tokens": self.summary_max_tokens},
        )

        # 流式消费 LLM 输出
        summary_text = ""
        try:
            stream = self.model.stream(request)
            if hasattr(stream, "__aiter__"):
                pass
            else:
                stream = await stream

            async for event in stream:
                if event.type == "text-delta":
                    summary_text += event.text or ""
        except Exception as e:
            logger.warning("ContextCompactor: LLM 流式调用失败: %s", e)
            return self._simple_summary(old_messages)

        summary_text = summary_text.strip()
        if not summary_text:
            logger.warning("ContextCompactor: LLM 返回空摘要，回退到 basic 策略")
            return self._simple_summary(old_messages)

        return summary_text

    def _format_messages_for_summary(self, messages: list[AgentMessage]) -> str:
        """格式化消息列表为摘要 prompt 文本 — Phase 13 新增

        每条消息保留前 500 字符（避免 prompt 过长），格式为:
            [role] content

        Args:
            messages: 消息列表

        Returns:
            格式化后的文本
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.role.value
            text = _extract_message_text(msg)
            if text:
                # 每条消息保留前 500 字符（避免 prompt 过长）
                if len(text) > 500:
                    text = text[:500] + "..."
                parts.append(f"[{role}] {text}")
        return "\n".join(parts)

    def _simple_summary(self, messages: list[AgentMessage]) -> str:
        """简单摘要 — 不使用 LLM，提取关键信息

        当没有 summarize_func 或 summarize_func 失败时使用。
        保留每条消息的角色和前 200 字符。
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.role.value
            text = _extract_message_text(msg)
            if text:
                # 截断过长的文本
                if len(text) > 200:
                    text = text[:200] + "..."
                parts.append(f"[{role}] {text}")

        if not parts:
            return "(无有效内容)"

        result = "\n".join(parts)
        # 如果摘要本身太长，截断
        if len(result) > self.summary_max_tokens * 4:
            result = result[:self.summary_max_tokens * 4] + "\n...(摘要已截断)"

        return result

    def get_stats(
        self,
        messages: list[AgentMessage],
        tools: list[AgentToolDefinition] | None = None,
    ) -> dict[str, Any]:
        """获取上下文统计信息 — Phase 33.3 增强 budget-projection 统计

        Args:
            messages: 消息列表
            tools: 工具定义列表（Phase 33.3 新增），传入时返回 budget_projection 统计

        Returns:
            统计字典，包含 message_count / estimated_tokens / trigger_threshold /
            preserve_recent_tokens / needs_compaction；
            tools 非空时额外返回 budget_projection 字段（current/projected/trigger/
            protected_tokens/available_for_truncation 等预算策略信息）
        """
        total_tokens = estimate_messages_tokens(messages)
        stats: dict[str, Any] = {
            "message_count": len(messages),
            "estimated_tokens": total_tokens,
            "trigger_threshold": self._trigger_tokens,
            "preserve_recent_tokens": self.preserve_recent_tokens,
            "needs_compaction": self.should_compact(messages, tools=tools),
        }
        # Phase 33.3: 返回 budget-projection 统计信息
        if tools is not None and self.enable_budget_projection:
            try:
                from agent.budget_policy import (
                    BudgetPolicyIntent,
                    estimate_protected_token_budget,
                )
                intent = BudgetPolicyIntent.BASIC_COMPACTION_PROJECTION
                projected = self._project_future_usage(
                    messages, tools, total_tokens, intent=intent,
                )
                budget_info = estimate_protected_token_budget(
                    messages, intent, self._projection_trigger_tokens,
                )
                stats["budget_projection"] = {
                    "intent": intent.value,
                    "current_tokens": total_tokens,
                    "projected_tokens": projected,
                    "projection_trigger": self._projection_trigger_tokens,
                    "protected_tokens": budget_info["protected_tokens"],
                    "available_for_truncation": budget_info["available_for_truncation"],
                    "latest_typed_user_index": budget_info["latest_typed_user_index"],
                    "protected_tail_start_index": budget_info["protected_tail_start_index"],
                    "last_compaction_reason": self._last_compaction_reason,
                }
            except Exception as e:
                logger.debug("get_stats: budget_projection 统计失败: %s", e)
        return stats


# ============================================================================
# 辅助函数
# ============================================================================


def _extract_message_text(message: AgentMessage) -> str:
    """从消息中提取文本内容"""
    parts = []
    for part in message.content:
        if isinstance(part, TextPart):
            parts.append(part.text)
    return "".join(parts)
