# -*- coding: utf-8 -*-
"""skills 工具 — 对标 Cline createSkillsTool

这是技能系统的核心工具，严格复刻 Cline 原生实现:
    - 工具名: skills
    - 输入: skill(必填), args(可选)
    - 执行: 不创建子 agent，而是在主 agent 上下文中返回 skill 指令文本
    - 返回格式:
        <command-name>{skill.name}</command-name>
        <command-args>{args}</command-args>
        <command-instructions>
        {description}{skill.instructions}
        </command-instructions>

主 agent 收到该 tool_result 后，会在下一轮把 skill 指令纳入上下文，
继续使用主 agent 的完整工具集执行 skill 中的指令。

这与"子 agent 隔离执行"方案有本质区别:
    - Cline skill 是"主上下文内的指令注入"
    - 不创建独立 runtime
    - 不限制工具集
    - 不用 attempt_completion 返回结果

参考:
    - sdk/packages/core/src/extensions/tools/definitions.ts createSkillsTool
    - sdk/packages/core/src/extensions/config/user-instruction-plugin.ts createUserInstructionSkillsExecutor
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent.tools.base import BaseTool
from agent.types import AgentToolContext, AgentToolResult
from agent.skills.registry import SkillRegistry, _normalize_skill_token

logger = logging.getLogger(__name__)


class SkillsTool(BaseTool):
    """skills 工具 — 对标 Cline createSkillsTool

    调用此工具时:
        1. 校验技能存在
        2. 加载技能 SKILL.md 指令
        3. 返回 XML 格式的 skill 指令文本
        4. 主 agent 在后续轮次中使用完整工具集执行该指令

    参数:
        skill: 技能名称（必填，对应 agent_config/skills/ 目录名）
        args: 技能参数/任务描述（可选）
    """

    def __init__(
        self,
        registry: SkillRegistry,
        skills_timeout_ms: int = 30000,
    ) -> None:
        """初始化 skills 工具

        Args:
            registry: 技能注册表，用于加载技能指令
            skills_timeout_ms: 技能加载超时毫秒数，默认 30000
                对标 Cline definitions.ts L721-723:
                    config: Pick<DefaultToolsConfig, "skillsTimeoutMs"> = {},
                    const timeoutMs = config.skillsTimeoutMs ?? 15000;
                runtime 会用 asyncio.wait_for 包裹 execute()，超时后返回 is_error 结果。
                P2-13: 默认值从 15000 提升到 30000，与内部 _execute 的
                asyncio.wait_for 超时（30s）保持一致。
        """
        self._registry = registry
        # Stage 37.2 (S2): 可配置的超时值 — 对标 Cline config.skillsTimeoutMs
        self._skills_timeout_ms = skills_timeout_ms
        # Phase 31.1: 运行中技能去重集合 — 对标 Cline user-instruction-plugin.ts L179
        # `const runningSkills = new Set<string>()`
        # 防止 LLM 重复调用同一技能导致指令重复注入
        self._running_skills: set[str] = set()

    # P2-13: 工具内部 asyncio.wait_for 超时秒数 — 对标 Cline withTimeout
    # 在 _execute 中用 asyncio.wait_for 包裹技能指令加载，超时返回 is_error
    _SKILL_EXECUTE_TIMEOUT_SECONDS = 30

    @property
    def name(self) -> str:
        return "skills"

    @property
    def description(self) -> str:
        return self._build_description()

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill": {
                    "type": "string",
                    "description": "技能名称（如 write-report, financial-analysis, read-pdf）",
                },
                "args": {
                    "type": "string",
                    "description": "技能参数或任务描述（可选）",
                },
            },
            "required": ["skill"],
        }

    @property
    def read_only(self) -> bool:
        return True

    @property
    def timeout_ms(self) -> int | None:
        """Phase 31.2: skills 工具超时 — 对标 Cline skillsTimeoutMs

        防止 SKILL.md 加载卡死（如文件系统挂起），超时后强制返回 is_error 结果。
        对标 Cline definitions.ts L721-723:
            config: Pick<DefaultToolsConfig, "skillsTimeoutMs"> = {},
            const timeoutMs = config.skillsTimeoutMs ?? 15000;
        超时值通过 __init__ 的 skills_timeout_ms 参数注入，默认 30000（P2-13 更新）。
        P2-13: _execute 内部还用 asyncio.wait_for 增加一层显式超时（30s），
        作为防御性设计，对标 Cline withTimeout。
        """
        return self._skills_timeout_ms

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行 skill — 对标 Cline skills tool execute()

        不创建子 agent，直接返回 skill 指令字符串。

        Phase 31.1: 新增 runningSkills 去重，同一技能在运行中时返回提示，
                    防止 LLM 重复调用导致指令重复注入。
                    对标 Cline user-instruction-plugin.ts L188-205
        """
        skill_name = input.get("skill", "").strip()
        args = input.get("args") or ""

        if not skill_name:
            return AgentToolResult(
                output={"error": "skill 名称不能为空"},
                is_error=True,
            )

        # Phase 31.5: Plan 模式下禁止调用产出型技能 write-report
        # 避免 Plan 模式被当作 Act 模式直接生成最终产物
        if skill_name == "write-report" and context.session_id is not None:
            from agent.state import get_mode

            if get_mode(context.session_id) == "plan":
                return AgentToolResult(
                    output={
                        "error": 'Plan 模式下禁止调用 write-report。'
                        '请在 Act 模式下执行此技能，或先切换到 Act 模式。'
                    },
                    is_error=True,
                )

        # 检查技能是否存在
        if not self._registry.has_skill(skill_name):
            available = [s.name for s in self._registry.list_skills()]
            return AgentToolResult(
                output={
                    "error": f"技能不存在: {skill_name}",
                    "available_skills": available,
                },
                is_error=True,
            )

        # Phase 31.4: 检查技能是否被 frontmatter disabled — 对标 Cline
        # user-instruction-plugin.ts L123-127 `if (skill.disabled === true) return {error: ...}`
        skill_meta = self._registry.get_skill(skill_name)
        if skill_meta is not None and skill_meta.disabled:
            return AgentToolResult(
                output={"error": f'Skill "{skill_name}" is configured but disabled.'},
                is_error=True,
            )

        # Phase 31.1: 检查技能是否正在运行 — 对标 Cline L188-190
        # `if (runningSkills.has(id)) return 'Skill "${name}" is already running.'`
        # Phase 3.6 (I6): 去重 key 改用 _normalize_skill_token(skill_name)
        # 确保 "PDF"/"pdf"/"/pdf" 映射到同一 key "pdf"
        skill_id = _normalize_skill_token(skill_name)
        if skill_id in self._running_skills:
            return AgentToolResult(
                output=f'Skill "{skill_name}" is already running.',
                is_error=False,  # Cline 返回的是提示文本，不是 error
            )

        # Phase 31.1: 标记技能为运行中 — 对标 Cline L192 `runningSkills.add(id)`
        # Phase 3.6: 用规范化 id 作 key
        self._running_skills.add(skill_id)
        try:
            # P2-13: 用 asyncio.wait_for 包裹指令加载，超时返回 is_error — 对标 Cline withTimeout
            # load_instructions 是同步文件 IO，用 asyncio.to_thread 卸载到线程池，
            # 使 asyncio.wait_for 能在文件系统挂起时真正超时（而非阻塞事件循环）。
            try:
                instructions = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._registry.load_instructions, skill_name
                    ),
                    timeout=self._SKILL_EXECUTE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "技能指令加载超时 (%ss): %s",
                    self._SKILL_EXECUTE_TIMEOUT_SECONDS, skill_name,
                )
                return AgentToolResult(
                    output={
                        "error": (
                            f"技能指令加载超时"
                            f"（{self._SKILL_EXECUTE_TIMEOUT_SECONDS}s）: {skill_name}"
                        )
                    },
                    is_error=True,
                )

            if instructions is None:
                return AgentToolResult(
                    output={"error": f"无法加载技能指令: {skill_name}"},
                    is_error=True,
                )

            # 构造 Cline 原生的 XML 指令格式
            description = (skill_meta.description or "").strip()
            description_block = f"Description: {description}\n\n" if description else ""

            args_tag = f"\n<command-args>{args}</command-args>" if args else ""

            result_text = (
                f"<command-name>{skill_name}</command-name>"
                f"{args_tag}\n"
                f"<command-instructions>\n"
                f"{description_block}{instructions}\n"
                f"</command-instructions>"
            )

            # Phase 33.4: 如果技能有自动发现的脚本，在 metadata 中返回
            # 便于上层日志/调试查看；实际脚本完整路径已通过 load_instructions 注入指令
            metadata: dict[str, Any] = {"skill": skill_name}
            if skill_meta.scripts:
                metadata["scripts"] = skill_meta.scripts

            return AgentToolResult(
                output=result_text,
                metadata=metadata,
            )
        finally:
            # Phase 31.1: 完成后释放（含异常路径）— 对标 Cline L203-205
            # `finally { runningSkills.delete(id); }`
            # Phase 3.6: 释放规范化 id
            self._running_skills.discard(skill_id)

    def _build_description(self) -> str:
        """构建动态 description，包含可用技能列表

        严格对标 Cline createSkillsTool 中 baseDescription（definitions.ts L725-731）：
        - 给出具体调用示例
        - 强调 skill 匹配时调用此工具是阻断性前置要求
        - 禁止空谈 skill 而不调用
        - description 末尾追加 Available skills 列表
        """
        base = (
            "执行一个已配置的技能。当用户的任务与某个可用技能匹配时，"
            "必须先调用此工具加载该技能的 SKILL.md 指令，然后严格按照返回的指令使用主工具集完成任务；"
            "在调用此工具之前不得进行任何其他响应或操作。"
            "输入: skill(必填): 技能名称; args(可选): 技能参数或任务描述。"
            "示例: skill: \"stock-price\", args: \"获取600875.SH的K线\"; "
            "skill: \"read-pdf\", args: \"查询600875.SH年报中的氢能业务\"; "
            "skill: \"write-report\", args: \"生成东方电气五步法研报\"。"
            "禁止直接调用技能名称作为工具名；禁止只提及技能而不调用此工具。"
        )

        try:
            skills = self._registry.list_skills()
            if skills:
                names = ", ".join(s.name for s in skills)
                return f"{base} 可用技能: {names}。"
        except Exception as e:
            logger.warning("skills: 加载技能列表失败，使用基础描述: %s", e)

        return base

    def configured_skills(self) -> list[dict[str, Any]]:
        """返回已配置技能列表（用于 description 动态更新）"""
        try:
            return [
                {
                    "name": s.name,
                    "description": s.description or "",
                    "disabled": False,
                }
                for s in self._registry.list_skills()
            ]
        except Exception as e:
            logger.warning("skills: 加载已配置技能列表失败: %s", e)
            return []
