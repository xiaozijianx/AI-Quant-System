# -*- coding: utf-8 -*-
"""技能注册表 — 对标 Cline skills registry

SkillRegistry 管理所有已发现的技能，提供:
    1. list_skills(): 返回所有技能元数据（Level 1）
    2. load_instructions(name): 加载技能指令（Level 2）

对标 Cline:
    - skills.mdx: "Cline sees a list of available skills with their descriptions"
    - use_skill 工具触发 Level 2 加载
    - 技能列表通过 tools 的 description 暴露给 LLM，不注入 system prompt
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.skills.loader import SkillLoader, SkillMetadata


def _normalize_skill_token(token: str) -> str:
    """规范化技能名 — 对标 Cline normalizeSkillToken

    小写化并去除前导斜杠，便于白名单匹配。
    """
    return (token or "").strip().lstrip("/").lower()


def _to_allowed_skill_set(
    allowed_skill_names: list[str] | None,
) -> set[str] | None:
    """将 allowed_skill_names 转为 Set — 对标 Cline toAllowedSkillSet

    None 或空列表返回 None（表示全部允许，不过滤）。
    """
    if not allowed_skill_names:
        return None
    normalized = [
        _normalize_skill_token(n) for n in allowed_skill_names
        if _normalize_skill_token(n)
    ]
    return set(normalized) if normalized else None


def _is_skill_allowed(
    skill_id: str,
    skill_name: str,
    allowed_skills: set[str] | None,
) -> bool:
    """检查技能是否在白名单中 — 对标 Cline isSkillAllowed

    allowed_skills 为 None 时全部允许。
    否则检查 4 种形式（对齐 Cline L51-73）:
        1. normalizedId: 规范化的 skill_id
        2. normalizedName: 规范化的 skill_name
        3. bareId: 去 ":" namespace 前缀的 normalizedId
        4. bareName: 去 ":" namespace 前缀的 normalizedName

    当前系统无 namespaced skill，skill_id 与 skill_name 相同，
    4 形式退化为 2 形式（normalized + bare），但为未来 namespace 扩展预留完整检查。

    对标 Cline sdk/packages/core/src/extensions/config/user-instruction-plugin.ts L51-73:
        const normalizedId = normalizeSkillToken(skillId);
        const normalizedName = normalizeSkillToken(skillName);
        const bareId = normalizedId.includes(":") ? normalizedId.split(":").at(-1) : normalizedId;
        const bareName = normalizedName.includes(":") ? normalizedName.split(":").at(-1) : normalizedName;
        return allowedSkills.has(normalizedId) || allowedSkills.has(normalizedName)
            || allowedSkills.has(bareId) || allowedSkills.has(bareName);
    """
    if allowed_skills is None:
        return True

    # 4 形式检查 — 对齐 Cline L59-72
    normalized_id = _normalize_skill_token(skill_id)
    normalized_name = _normalize_skill_token(skill_name)
    bare_id = normalized_id.split(":")[-1] if ":" in normalized_id else normalized_id
    bare_name = normalized_name.split(":")[-1] if ":" in normalized_name else normalized_name

    return (
        normalized_id in allowed_skills
        or normalized_name in allowed_skills
        or bare_id in allowed_skills
        or bare_name in allowed_skills
    )


class SkillRegistry:
    """技能注册表 — 对标 Cline skills registry

    用法:
        registry = SkillRegistry(skills_dir=Path("skills"))
        registry.discover()  # 扫描并加载所有技能元数据

        # 在 system prompt 中注入技能摘要
        summary = registry.build_summary()

        # 在 AgentRuntime 中注册 SkillTool
        skill_tool = SkillTool(registry)
        runtime.register_tool(skill_tool)

    Phase 31.3: 新增 allowed_skill_names 白名单参数 — 对标 Cline
    user-instruction-plugin.ts L39-73 toAllowedSkillSet + isSkillAllowed。
    多 agent 场景下限制可用技能（如子 agent 只能用部分技能）。
    """

    def __init__(
        self,
        skills_dir: Path | str | None = None,
        allowed_skill_names: list[str] | None = None,
    ) -> None:
        self.loader = SkillLoader(skills_dir)
        self._skills: dict[str, SkillMetadata] = {}
        # Phase 31.3: 白名单集合 — None 表示全部允许
        self._allowed_skills: set[str] | None = _to_allowed_skill_set(
            allowed_skill_names
        )

    def discover(self) -> list[SkillMetadata]:
        """扫描技能目录并加载元数据 — 对标 Cline skills discovery

        Returns:
            所有已发现的技能元数据列表
        """
        skills = self.loader.list_skills()
        self._skills = {s.name: s for s in skills}
        return skills

    def list_skills(self) -> list[SkillMetadata]:
        """返回所有技能元数据 — Phase 31.3/31.4: 应用白名单和 disabled 过滤

        对标 Cline getConfiguredSkillsFromWatcher:
            - 过滤非白名单技能（L92 isSkillAllowed）
            - 过滤 disabled=True 的技能（L100 !skill.disabled）
        """
        if not self._skills:
            self.discover()
        all_skills = list(self._skills.values())
        # Phase 31.3: 白名单过滤
        if self._allowed_skills is not None:
            all_skills = [
                s for s in all_skills
                if _is_skill_allowed(s.name, s.name, self._allowed_skills)
            ]
        # Phase 31.4: disabled 过滤 — 不展示禁用技能
        all_skills = [s for s in all_skills if not s.disabled]
        return all_skills

    def get_skill(self, name: str) -> SkillMetadata | None:
        """获取单个技能元数据 — Phase 31.3: 应用白名单过滤

        白名单外的技能返回 None（视为不存在）。
        Phase 31.4: disabled 技能仍可获取（用于 SkillsTool 返回
        "configured but disabled" 错误消息）。
        """
        if not self._skills:
            self.discover()
        # Phase 31.3: 白名单外的技能视为不存在
        if self._allowed_skills is not None and not _is_skill_allowed(
            name, name, self._allowed_skills
        ):
            return None
        return self._skills.get(name)

    def load_instructions(self, name: str) -> str | None:
        """加载技能指令 — Level 2 加载

        对标 Cline: "use_skill tool loads the full instructions from SKILL.md"
        """
        return self.loader.load_instructions(name)

    def has_skill(self, name: str) -> bool:
        """检查技能是否存在 — Phase 31.3: 应用白名单过滤

        白名单外的技能返回 False（视为不存在）。
        """
        return self.get_skill(name) is not None
