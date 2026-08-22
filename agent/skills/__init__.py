# -*- coding: utf-8 -*-
"""技能系统 — 对标 Cline skills

渐进式加载三级机制（对标 Cline skills.mdx）:
    1. Metadata（~100 tokens/技能，始终加载）: name + description
    2. Instructions（<5k tokens，按需加载）: SKILL.md 全文
    3. Resources（按需加载）: scripts/ 文件

核心组件:
    - SkillMetadata: 技能元数据（name, description, keywords, always, capabilities）
    - SkillLoader: 扫描 skills/ 目录，解析 frontmatter
    - SkillRegistry: 管理技能，提供 metadata + instructions + summary
    - SkillTool: use_skill 工具，LLM 通过 tool_call 加载技能指令

关键设计: use_skill 工具解决"agent 不读 SKILL.md"问题
    LLM 只看到技能名称和描述（~100 tokens），
    需要使用技能时通过 use_skill(name) 工具调用加载完整指令。
    这比在 prompt 中要求"先读 SKILL.md"可靠得多。

对标 Cline:
    - docs/customization/skills.mdx: 渐进式加载机制
    - use_skill 工具: LLM 主动加载技能指令
"""

from agent.skills.loader import SkillLoader, SkillMetadata
from agent.skills.registry import SkillRegistry
from agent.skills.skill_tool import SkillsTool

__all__ = [
    "SkillLoader",
    "SkillMetadata",
    "SkillRegistry",
    "SkillsTool",
]
