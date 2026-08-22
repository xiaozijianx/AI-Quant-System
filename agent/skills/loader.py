# -*- coding: utf-8 -*-
"""技能加载器 — 对标 Cline skills discovery

扫描 skills/ 目录，解析 SKILL.md 的 YAML frontmatter，
提取 name / description / disabled 等元数据。

SKILL.md 格式:
    ---
    name: write-report
    description: "按照国泰君安五步法撰写深度分析研报。Use when 需要撰写研报时。"
    disabled: false
    ---
    # write-report 技能指南
    ...正文指令...

对标 Cline:
    - skills.mdx: "Every skill is a directory containing a SKILL.md file"
    - "name must exactly match the directory name"
    - "description tells Cline when to use this skill"
    - SkillMetadata 只有 name / description / path / source 4 个字段
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SkillMetadata:
    """技能元数据 — 对标 Cline SkillMetadata

    对标 Cline: name / description / path / source 4 个核心字段。
    Charles 扩展: disabled / scripts / source_dir（合理增强，Cline 也有对应实现）。

    Level 1 加载: 始终在 system prompt 中呈现（~100 tokens/技能）。

    Phase 31.4 新增:
        - disabled: 通过 frontmatter `disabled: true` 禁用技能
          对标 Cline skill-frontmatter-toggle.ts + user-instruction-plugin.ts L123
          禁用的技能不出现在 list_skills() 中，has_skill() 返回 False

    Stage 13.4 (X10) 新增:
        - source_dir: skill 来源目录路径，用于多目录加载时记录来源
          同名 skill 时按目录优先级覆盖（dirs 列表中靠后的优先级高）
          对标 Cline multi-source skills loading + override resolution
    """
    name: str                           # 技能名称（与目录名一致）
    description: str = ""               # 技能描述（LLM 据此判断是否使用，内含"何时使用"语义）
    file_path: str = ""                 # SKILL.md 文件路径
    source: str = "workspace"           # workspace / builtin
    disabled: bool = False              # Phase 31.4: frontmatter disabled 字段
    scripts: list[str] = field(default_factory=list)  # Phase 33.4: 技能脚本完整相对路径列表
    # Stage 13.4 (X10): skill 来源目录路径 — 多目录加载时记录来源
    source_dir: str = ""


def _strip_utf8_bom(content: str) -> str:
    """剥离 UTF-8 BOM — 对标 Cline stripUtf8Bom

    Windows Notepad 保存的 "UTF-8 with BOM" 文件开头是 \\uFEFF，
    会导致 frontmatter 正则不匹配（见 cline/cline#12151）。
    """
    if content.startswith("\ufeff"):
        return content[1:]
    return content


class SkillLoader:
    """技能加载器 — 对标 Cline skills discovery

    扫描指定目录下的 skills/*/SKILL.md 文件，
    解析 frontmatter 提取元数据。

    用法:
        loader = SkillLoader(skills_dir=Path("skills"))
        metadata_list = loader.list_skills()
        instructions = loader.load_instructions("write-report")
    """

    def __init__(self, skills_dir: Path | str | None = None) -> None:
        """初始化技能加载器

        Args:
            skills_dir: 技能目录路径，默认为当前工作目录下的 skills/
        """
        if skills_dir is None:
            skills_dir = Path.cwd() / "skills"
        self.skills_dir = Path(skills_dir)
        # 元数据缓存: name → SkillMetadata
        self._cache: dict[str, SkillMetadata] = {}

    def list_skills(self) -> list[SkillMetadata]:
        """列出所有技能（含 disabled）— 对标 Cline skills discovery

        扫描 skills_dir 下的子目录，找到包含 SKILL.md 的目录。
        返回所有解析成功的技能元数据，包括 disabled=True 的技能。

        Phase 31.4: disabled 过滤由 SkillRegistry.list_skills() 负责，
        此处返回全部技能以便 get_skill() 能查询 disabled 技能用于错误提示。
        """
        if not self.skills_dir.exists():
            return []

        skills: list[SkillMetadata] = []
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            meta = self._parse_skill_file(skill_file)
            if meta is not None:
                skills.append(meta)
                self._cache[meta.name] = meta

        return skills

    def get_skill(self, name: str) -> SkillMetadata | None:
        """获取单个技能的元数据"""
        if name in self._cache:
            return self._cache[name]
        # 尝试加载
        skill_file = self.skills_dir / name / "SKILL.md"
        if skill_file.exists():
            meta = self._parse_skill_file(skill_file)
            if meta is not None:
                self._cache[name] = meta
            return meta
        return None

    def load_instructions(self, name: str) -> str | None:
        """加载技能指令 — Level 2 加载

        读取 SKILL.md 全文并去除 frontmatter，
        返回纯指令内容（<5k tokens）。

        对标 Cline: "When skill is triggered, Cline activates it using
                     the use_skill tool, which loads the full instructions"
        """
        skill_file = self.skills_dir / name / "SKILL.md"
        if not skill_file.exists():
            return None

        content = skill_file.read_text(encoding="utf-8")
        instructions = self._strip_frontmatter(content)

        # Phase 33.4: 自动追加脚本完整路径清单
        # 让 LLM 直接拿到可复制的命令，避免自己拼路径时漏掉 scripts/ 等子目录
        scripts = self._get_skill_scripts(name)
        if scripts:
            scripts_block = self._build_scripts_block(scripts, skill_file.parent)
            if scripts_block:
                instructions = f"{instructions}\n\n{scripts_block}"

        return instructions

    def _get_skill_scripts(self, name: str) -> list[str]:
        """获取技能的脚本路径列表（优先从缓存的 metadata 读取）"""
        if name in self._cache:
            return self._cache[name].scripts
        skill_file = self.skills_dir / name / "SKILL.md"
        if not skill_file.exists():
            return []
        meta = self._parse_skill_file(skill_file)
        if meta is not None:
            self._cache[name] = meta
            return meta.scripts
        return []

    def _build_scripts_block(self, scripts: list[str], skill_dir: Path) -> str | None:
        """构建脚本路径提示块 — Phase 33.4

        输出格式:
            ## 可用脚本（可直接复制执行）
            - `python agent_config/skills/stock-price/scripts/get_kline.py`
        """
        if not scripts:
            return None

        lines = ["## 可用脚本（可直接复制执行）"]
        for script in scripts:
            lines.append(f"- `python {script}`")
        return "\n".join(lines)

    def load_raw(self, name: str) -> str | None:
        """加载技能原始内容（含 frontmatter）"""
        skill_file = self.skills_dir / name / "SKILL.md"
        if not skill_file.exists():
            return None
        return skill_file.read_text(encoding="utf-8")

    def _parse_skill_file(self, skill_file: Path) -> SkillMetadata | None:
        """解析 SKILL.md 文件 — 对标 Cline loadSkillMetadata

        解析 YAML frontmatter 提取元数据。
        对标 Cline: 只解析 name / description / disabled。
        """
        content = skill_file.read_text(encoding="utf-8")
        frontmatter = self._parse_frontmatter(content)
        if frontmatter is None:
            return None

        name = frontmatter.get("name", skill_file.parent.name)
        description = frontmatter.get("description", "")
        # Phase 31.4: 解析 disabled 字段 — 对标 Cline skill-frontmatter-toggle.ts
        # 支持 disabled: true 或 enabled: false 两种写法
        disabled = bool(frontmatter.get("disabled", False))
        if frontmatter.get("enabled", True) is False:
            disabled = True

        # Phase 33.4: 自动发现技能目录下所有 .py 脚本（递归扫描）
        # 如果 frontmatter 中显式声明了 scripts，则优先使用；否则自动扫描
        scripts_raw = frontmatter.get("scripts", None)
        if scripts_raw is not None:
            if isinstance(scripts_raw, str):
                scripts = [s.strip() for s in scripts_raw.split(",") if s.strip()]
            elif isinstance(scripts_raw, list):
                scripts = [str(s).strip() for s in scripts_raw if s]
            else:
                scripts = []
        else:
            scripts = self._discover_scripts(skill_file.parent)

        return SkillMetadata(
            name=name,
            description=description,
            file_path=str(skill_file),
            source="workspace",
            disabled=disabled,
            scripts=scripts,
            # Stage 13.4 (X10): 记录 skill 来源目录
            source_dir=str(self.skills_dir),
        )

    def _discover_scripts(self, skill_dir: Path) -> list[str]:
        """自动发现技能目录下所有可执行 Python 脚本 — Phase 33.4

        递归扫描技能目录下所有 .py 文件（排除 __pycache__ 和隐藏文件），
        返回相对于项目根目录的完整路径。这样 LLM 可直接复制使用，无需自己拼接。

        Args:
            skill_dir: 技能目录路径（如 .../agent_config/skills/stock-price）

        Returns:
            脚本相对路径列表（如 ["agent_config/skills/stock-price/scripts/get_kline.py"]）
        """
        try:
            py_files: list[Path] = []
            for root, dirs, files in os.walk(skill_dir):
                # 排除 __pycache__ 和隐藏目录
                dirs[:] = [
                    d for d in dirs
                    if d != "__pycache__" and not d.startswith(".")
                ]
                for f in files:
                    if f.endswith(".py") and not f.startswith("."):
                        py_files.append(Path(root) / f)

            if not py_files:
                return []

            # 计算项目根目录：向上查找包含 agent_config 的目录
            # 优先从 skill_dir 向上找；找不到则用 cwd
            project_root = self._find_project_root(skill_dir)

            scripts: list[str] = []
            for py_file in sorted(py_files):
                try:
                    rel = py_file.resolve().relative_to(project_root.resolve())
                    scripts.append(str(rel).replace(os.sep, "/"))
                except ValueError:
                    # 不在项目根目录下时保留绝对路径
                    scripts.append(str(py_file.resolve()).replace(os.sep, "/"))

            return scripts
        except Exception:
            return []

    def _find_project_root(self, start_path: Path) -> Path:
        """查找项目根目录 — Phase 33.4

        向上遍历目录，找到包含 agent_config/skills 或 pyproject.toml/setup.py 的目录。
        找不到则返回当前工作目录。
        """
        current = start_path.resolve()
        for _ in range(10):  # 最多向上 10 层
            # 标记 1：包含 agent_config/skills 目录
            if (current / "agent_config" / "skills").is_dir():
                return current
            # 标记 2：常见项目根目录文件
            if any((current / marker).exists() for marker in ("pyproject.toml", "setup.py", ".git")):
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        return Path.cwd()

    def _parse_frontmatter(self, content: str) -> dict[str, Any] | None:
        """解析 YAML frontmatter — 对标 Cline parseMarkdownFrontmatter

        使用 PyYAML 解析 frontmatter。
        对齐 Cline: BOM 剥离 + \\r?\\n 支持 CRLF。
        """
        # Phase 3.5 (I12): 剥离 UTF-8 BOM — 对标 Cline stripUtf8Bom
        content = _strip_utf8_bom(content)

        if not content.startswith("---"):
            return None

        # Phase 3.5 (I12): 正则支持 \r\n (CRLF) 和 \n (LF) — 对标 Cline L202
        match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", content, re.DOTALL)
        if not match:
            return None

        raw = match.group(1)

        import yaml
        result = yaml.safe_load(raw)
        if isinstance(result, dict):
            return result
        return None

    def _strip_frontmatter(self, content: str) -> str:
        """去除 YAML frontmatter

        对齐 Cline: BOM 剥离 + \\r?\\n 支持 CRLF。
        """
        # Phase 3.5 (I12): 剥离 BOM
        content = _strip_utf8_bom(content)
        if content.startswith("---"):
            # Phase 3.5: 正则支持 \r\n (CRLF)
            match = re.match(r"^---\r?\n.*?\r?\n---\r?\n?", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content


# ============================================================================
# Stage 13.4 (X10): 多目录 skills 加载 + override 解析
# 对标 Cline multi-source skills loading (user-level + project-level)
# ============================================================================


def load_skills_multi_dir(
    dirs: list[Path | str],
) -> list[SkillMetadata]:
    """从多个目录加载 skills，后加载的覆盖先加载的 — Stage 13.4 新增

    对标 Cline skills 多目录加载 + override resolution:
        - 用户级 skills（低优先级）
        - 项目级 skills（高优先级）
        - 同名 skill 时按目录优先级覆盖

    优先级规则:
        dirs 列表中**靠后**的目录优先级高（覆盖前面的）。
        例如 dirs=[user_dir, project_dir]，project_dir 中的同名 skill 覆盖 user_dir。

    Args:
        dirs: skills 目录路径列表（优先级升序，后面覆盖前面）

    Returns:
        合并后的 SkillMetadata 列表（同名 skill 仅保留高优先级版本）
    """
    skills_by_name: dict[str, SkillMetadata] = {}

    for d in dirs:
        dir_path = Path(d).expanduser()
        if not dir_path.exists():
            logger.debug("Stage 13.4: skills 目录不存在，跳过: %s", dir_path)
            continue

        loader = SkillLoader(skills_dir=dir_path)
        for skill in loader.list_skills():
            # 记录来源目录（_parse_skill_file 已设置 source_dir，此处确保正确）
            skill.source_dir = str(dir_path)

            if skill.name in skills_by_name:
                # 同名 skill 覆盖，记录 override 日志
                old_source = skills_by_name[skill.name].source_dir
                logger.info(
                    "Stage 13.4: skill override: %s from %s -> %s",
                    skill.name, old_source, dir_path,
                )
            skills_by_name[skill.name] = skill

    return list(skills_by_name.values())


def load_skills_with_dirs(
    primary_dir: Path | str,
    extra_dirs: list[Path | str] | None = None,
) -> list[SkillMetadata]:
    """加载 skills，primary_dir 优先级最高 — Stage 13.4 新增

    便捷封装:
        - extra_dirs 中的目录优先级低（被 primary_dir 覆盖）
        - primary_dir 优先级最高

    Args:
        primary_dir: 主 skills 目录（优先级最高）
        extra_dirs: 额外 skills 目录列表（优先级低，被 primary_dir 覆盖）

    Returns:
        合并后的 SkillMetadata 列表
    """
    extra_dirs = extra_dirs or []
    # 优先级升序: extra_dirs 在前，primary_dir 在后（覆盖前面的）
    all_dirs = list(extra_dirs) + [primary_dir]
    return load_skills_multi_dir(all_dirs)
