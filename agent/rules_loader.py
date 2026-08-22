# -*- coding: utf-8 -*-
"""规则文件加载器 — 对标 Cline frontmatter + rule-conditionals + rule-helpers

支持按 frontmatter 条件加载规则文件（.md），实现:
    1. YAML frontmatter 解析（fail-open，解析失败保留原文）
    2. 按 agent mode（act / plan）过滤 — 对标 Cline applyTo
    3. 按业务 mode（自定义字符串列表，如 research / trade）过滤
    4. 按工作空间路径 glob 匹配过滤 — 对标 Cline paths
    5. enabled 开关（默认 True）

frontmatter 字段示例:
    ---
    description: 交易场景规则
    applyTo: [plan, act]            # 可选，agent 模式过滤；省略=应用到所有模式
    mode: [trade]                   # 可选，业务模式过滤；省略=应用到所有业务模式
    paths: [src/**/*.py, tests/]    # 可选，工作空间路径 glob 匹配；省略=无条件
    enabled: true                   # 可选，是否启用；默认 true
    ---

    # 规则正文

加载策略:
    - 无 frontmatter 的文件：整体加载（向后兼容 AGENTS.md 单文件模式）
    - 有 frontmatter 但解析失败：fail-open，整体加载原文
    - 有 frontmatter 且解析成功：按条件过滤，过滤通过时仅加载 body（去掉 frontmatter）

对标 Cline 参考位置:
    - third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/frontmatter.ts
    - third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts
    - third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# 常量
# ============================================================================

# frontmatter 正则 — 对标 Cline frontmatter.ts L44
# 匹配 `---\n...\n---\n` 开头的 YAML 块，支持 \r\n
_FRONTMATTER_REGEX = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$")

# BOM 标记
_UTF8_BOM = "\ufeff"


# Stage 7.4 (L6/X12): 模块级 mtime 缓存 — 对标 Cline UnifiedConfigFileWatcher 的增量更新
# key: 文件绝对路径（str）
# value: (mtime_ns, raw_text, FrontmatterParseResult) 元组
# 缓存语义：仅缓存"文件内容 + frontmatter 解析结果"，不缓存"条件评估结果"
# （条件评估每次都需基于当前 context 重算，因此 RuleLoadResult 不进缓存）
# 设计说明：Cline 通过 fs.watch + 75ms debounce 实现事件驱动增量更新；
# 本项目是 Web 请求-响应模型，每次 build 重读已等价"热重载"，
# mtime 缓存仅用于减少无变更文件的重复 I/O 与解析开销
_RULES_MTIME_CACHE: dict[str, tuple[int, str, "FrontmatterParseResult"]] = {}


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class FrontmatterParseResult:
    """frontmatter 解析结果 — 对标 Cline FrontmatterParseResult

    Attributes:
        data: 解析后的 YAML 数据（dict），无 frontmatter 或解析失败时为空 dict
        body: 去掉 frontmatter 后的正文内容
        had_frontmatter: 是否检测到 frontmatter 块
        parse_error: 解析错误信息（fail-open 时保留原文，但记录错误）
    """

    data: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    had_frontmatter: bool = False
    parse_error: str | None = None


@dataclass
class RuleLoadResult:
    """单个规则文件加载结果

    Attributes:
        path: 规则文件路径
        body: 实际加载的正文内容（无 frontmatter）
        frontmatter: 解析出的 frontmatter 数据
        activated: 是否被激活（条件过滤通过）
        matched_conditions: 命中的条件（用于日志/UI 展示）
        skip_reason: 未激活时的原因（便于调试）
    """

    path: Path
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    activated: bool = False
    matched_conditions: dict[str, list[str]] = field(default_factory=dict)
    skip_reason: str = ""


@dataclass
class RuleEvaluationContext:
    """规则评估上下文 — 对标 Cline RuleEvaluationContext

    Attributes:
        agent_mode: 当前 agent 模式（act / plan），None 表示不按此条件过滤
        business_modes: 当前业务模式列表（如 ["research"] / ["trade"]），空列表表示不按此过滤
        paths: 候选工作空间相对路径（POSIX 风格），空列表表示无路径上下文
    """

    agent_mode: str | None = None
    business_modes: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


# ============================================================================
# frontmatter 解析 — 对标 Cline parseYamlFrontmatter
# ============================================================================


def parse_yaml_frontmatter(markdown: str) -> FrontmatterParseResult:
    """解析 YAML frontmatter — 对标 Cline parseYamlFrontmatter

    行为策略（fail-open）:
        - 无 frontmatter：返回 data={} + body=原文 + had_frontmatter=False
        - 解析失败：返回 data={} + body=原文 + had_frontmatter=True + parse_error=msg
        - 解析成功：返回 data=dict + body=去 frontmatter 后正文 + had_frontmatter=True

    Args:
        markdown: 原始 markdown 文本

    Returns:
        FrontmatterParseResult
    """
    if not markdown:
        return FrontmatterParseResult(body="")

    # 剥离 UTF-8 BOM — 对标 Cline stripUtf8Bom
    normalized = markdown
    if normalized.startswith(_UTF8_BOM):
        normalized = normalized[len(_UTF8_BOM):]

    match = _FRONTMATTER_REGEX.match(normalized)
    if not match:
        return FrontmatterParseResult(body=normalized, had_frontmatter=False)

    yaml_content, body = match.group(1), match.group(2)

    try:
        # 延迟导入 yaml，避免硬依赖（虽然 PyYAML 是常见库）
        import yaml

        data = yaml.safe_load(yaml_content) or {}
        if not isinstance(data, dict):
            # 顶层非 dict（如纯字符串/列表）视为解析失败，fail-open
            return FrontmatterParseResult(
                body=normalized,
                had_frontmatter=True,
                parse_error=f"frontmatter top-level must be a mapping, got {type(data).__name__}",
            )
        return FrontmatterParseResult(
            data=data,
            body=body,
            had_frontmatter=True,
        )
    except Exception as e:
        return FrontmatterParseResult(
            body=normalized,
            had_frontmatter=True,
            parse_error=str(e),
        )


# ============================================================================
# 条件评估 — 对标 Cline evaluateRuleConditionals
# ============================================================================


def _is_non_empty_string_array(value: Any) -> bool:
    """判断是否为非空字符串数组 — 对标 Cline isNonEmptyStringArray"""
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(v, str) and v for v in value)
    )


def _to_posix(p: str) -> str:
    """路径转 POSIX 风格 — 对标 Cline toPosix"""
    return p.replace("\\", "/")


# Stage 7.1 (X4): wcmatch 标志常量 — 对标 Cline picomatch(pattern, { dot: true })
# 延迟导入 wcmatch.glob 避免未安装时影响模块加载
_WCMATCH_FLAGS = None  # 延迟初始化


def _get_wcmatch_flags():
    """延迟获取 wcmatch glob flags — Stage 7.1 新增

    flags 组合对标 Cline picomatch(pattern, { dot: true })：
        - GLOBSTAR: 支持 ** 跨目录
        - DOTGLOB: 让 * 显式匹配 . 开头文件（等价 picomatch dot: true）
        - BRACE: 支持 brace expansion（{a,b}）
        - EXTGLOB: 支持 extglob（+(a) / ?(a) / *(a)）
        - NEGATE: 支持 negation（!pattern）
    """
    global _WCMATCH_FLAGS
    if _WCMATCH_FLAGS is not None:
        return _WCMATCH_FLAGS
    try:
        from wcmatch import glob as wcglob
        _WCMATCH_FLAGS = (
            wcglob.GLOBSTAR
            | wcglob.DOTGLOB
            | wcglob.BRACE
            | wcglob.EXTGLOB
            | wcglob.NEGATE
        )
    except ImportError:
        _WCMATCH_FLAGS = False  # 标记 wcmatch 不可用
    return _WCMATCH_FLAGS


def _match_glob_regex(pattern: str, candidate: str) -> bool:
    """简化版 glob 匹配（原实现）— 保留作为 wcmatch 不可用时的等价语义实现

    支持:
        - * 匹配单层任意字符（不含 /）
        - ** 匹配多层任意字符（含 /）
        - ? 匹配单个字符
        - 其他字符精确匹配

    不支持 picomatch 的高级特性（如 brace expansion / extglob / negation），
    保持轻量无依赖。Stage 7.1 后仅作为 wcmatch 不可用时的备选实现。
    """
    if not pattern:
        return False

    # 把 pattern 转为正则
    regex_parts: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            # 检查是否是 **
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                regex_parts.append(".*")
                i += 2
                # 处理 **/ 中的 /
                if i < len(pattern) and pattern[i] == "/":
                    regex_parts.append("/")
                    i += 1
            else:
                # 单 * 不匹配 /
                regex_parts.append("[^/]*")
                i += 1
        elif ch == "?":
            regex_parts.append("[^/]")
            i += 1
        else:
            regex_parts.append(re.escape(ch))
            i += 1

    regex = "^" + "".join(regex_parts) + "$"
    return re.match(regex, candidate) is not None


def _match_glob(pattern: str, candidate: str) -> bool:
    """glob 匹配 — 对标 Cline picomatch(pattern, { dot: true })

    Stage 7.1 (X4) 升级: 优先使用 wcmatch.glob.globmatch，支持完整 glob 语义:
        - brace expansion: src/{lib,bin}/**/*.py
        - negation: !**/*.test.ts（独立 negation pattern）
        - extglob: +(a).py
        - ** 跨目录
        - dot: true 显式匹配 . 开头文件（DOTGLOB）

    wcmatch 不可用时回退到 _match_glob_regex 简化正则实现（保留原逻辑），
    在日志中记录 warning 提示安装 wcmatch 以获得完整 glob 语义。

    注意（picomatch vs wcmatch 语义差异）:
        picomatch 对独立 negation pattern `!foo` 的语义为"匹配不满足 foo 的路径"，
        即 picomatch('!foo')('bar') 返回 True。而 wcmatch 的 NEGATE 标志在
        globmatch 单 pattern 场景下行为不同（在 pattern list 中才生效）。为对齐
        picomatch 语义，本函数对以 `!` 开头的 pattern 单独处理：剥离 `!` 后
        匹配剩余 pattern，结果取反。

    Args:
        pattern: glob 模式（POSIX 风格）
        candidate: 候选路径（POSIX 风格）

    Returns:
        是否匹配
    """
    if not pattern:
        return False

    # picomatch 独立 negation pattern 处理：以 `!` 开头时取反匹配
    # 对标 Cline rule-conditionals.ts 中 picomatch(pattern, { dot: true }) 行为
    is_negated = False
    effective_pattern = pattern
    if pattern.startswith("!"):
        is_negated = True
        effective_pattern = pattern[1:]
        if not effective_pattern:
            # `!` 单独出现 → 匹配所有（取反空 = 匹配所有）
            return True

    flags = _get_wcmatch_flags()
    if flags is not False:
        # wcmatch 可用 — 使用完整 glob 语义
        from wcmatch import glob as wcglob
        matched = wcglob.globmatch(candidate, effective_pattern, flags=flags)
        return (not matched) if is_negated else matched

    # wcmatch 不可用 — 回退到简化正则实现（保留原逻辑作为等价语义的另一实现）
    logger.warning(
        "wcmatch 未安装，回退到简化正则 glob 匹配。"
        "建议 pip install wcmatch 以获得 brace expansion / negation / extglob 支持"
    )
    matched = _match_glob_regex(effective_pattern, candidate)
    return (not matched) if is_negated else matched


def _evaluate_paths_conditional(
    frontmatter_value: Any,
    context: RuleEvaluationContext,
) -> tuple[bool, list[str]]:
    """评估 paths 条件 — 对标 Cline evaluatePathsConditional

    Returns:
        (passed, matched_patterns)
    """
    if not _is_non_empty_string_array(frontmatter_value):
        # 类型无效 → 忽略此条件（fail-open）
        return True, []

    patterns = [p.strip() for p in frontmatter_value if p.strip()]
    if not patterns:
        # paths: [] → 匹配空（fail-closed）
        return False, []

    candidate_paths = [_to_posix(p) for p in context.paths if p]
    if not candidate_paths:
        # 无候选路径 → 不激活路径限定规则（fail-closed）
        return False, []

    matched: list[str] = []
    for pattern in patterns:
        for candidate in candidate_paths:
            if _match_glob(pattern, candidate):
                matched.append(pattern)
                break

    return len(matched) > 0, matched


def _evaluate_apply_to_conditional(
    frontmatter_value: Any,
    context: RuleEvaluationContext,
) -> tuple[bool, list[str]]:
    """评估 applyTo 条件（agent 模式过滤）

    applyTo 省略 → 应用到所有 agent 模式
    applyTo: [] → 不应用到任何模式（fail-closed）
    applyTo: [plan] → 仅在 plan 模式下激活

    Returns:
        (passed, matched_modes)
    """
    if frontmatter_value is None:
        # 省略 → 无条件通过
        return True, []

    if not _is_non_empty_string_array(frontmatter_value):
        # 类型无效或空数组 → fail-open（与 Cline paths 行为略有不同，applyTo 我们采用 fail-open）
        # 但空数组明确表示"不应用"，所以单独处理
        if isinstance(frontmatter_value, list) and len(frontmatter_value) == 0:
            return False, []
        return True, []

    if context.agent_mode is None:
        # 上下文未指定 agent mode，但规则指定了 applyTo → fail-closed（保守不激活）
        return False, []

    patterns = [p.strip() for p in frontmatter_value if p.strip()]
    if context.agent_mode in patterns:
        return True, [context.agent_mode]
    return False, []


def _evaluate_business_mode_conditional(
    frontmatter_value: Any,
    context: RuleEvaluationContext,
) -> tuple[bool, list[str]]:
    """评估 mode 条件（业务模式过滤）

    mode 省略 → 应用到所有业务模式
    mode: [] → 不应用
    mode: [research, trade] → 当前业务模式命中任一则激活

    Returns:
        (passed, matched_modes)
    """
    if frontmatter_value is None:
        return True, []

    if not _is_non_empty_string_array(frontmatter_value):
        if isinstance(frontmatter_value, list) and len(frontmatter_value) == 0:
            return False, []
        return True, []

    if not context.business_modes:
        # 上下文未指定业务模式，但规则指定了 mode → fail-closed
        return False, []

    patterns = [p.strip() for p in frontmatter_value if p.strip()]
    matched = [m for m in context.business_modes if m in patterns]
    return len(matched) > 0, matched


def evaluate_rule_conditionals(
    frontmatter: dict[str, Any],
    context: RuleEvaluationContext,
) -> tuple[bool, dict[str, list[str]]]:
    """评估所有条件 — 对标 Cline evaluateRuleConditionals

    未知字段忽略（forward compatibility）。

    Args:
        frontmatter: 解析后的 frontmatter 数据
        context: 评估上下文

    Returns:
        (passed, matched_conditions)
        - passed: 所有条件均通过
        - matched_conditions: 命中的条件 {field: [matched_values]}
    """
    matched_conditions: dict[str, list[str]] = {}

    # enabled 开关
    enabled = frontmatter.get("enabled", True)
    if enabled is not None and enabled is False:
        return False, {}

    # applyTo 条件（agent 模式）
    if "applyTo" in frontmatter:
        passed, matched = _evaluate_apply_to_conditional(frontmatter["applyTo"], context)
        if not passed:
            return False, {}
        if matched:
            matched_conditions["applyTo"] = matched

    # mode 条件（业务模式）
    if "mode" in frontmatter:
        passed, matched = _evaluate_business_mode_conditional(frontmatter["mode"], context)
        if not passed:
            return False, {}
        if matched:
            matched_conditions["mode"] = matched

    # paths 条件（工作空间路径）
    if "paths" in frontmatter:
        passed, matched = _evaluate_paths_conditional(frontmatter["paths"], context)
        if not passed:
            return False, {}
        if matched:
            matched_conditions["paths"] = matched

    return True, matched_conditions


# ============================================================================
# 规则目录加载 — 对标 Cline getRuleFilesTotalContentWithMetadata
# ============================================================================


def _is_rule_file(path: Path) -> bool:
    """判断是否为规则文件（.md 后缀）"""
    return path.is_file() and path.suffix.lower() == ".md"


def _is_path_in_excluded_subdir(
    file_path: Path,
    rules_dir: Path,
    excluded_subdirs: list[str] | None,
) -> bool:
    """判断文件是否位于排除子目录中 — Stage 7.4 新增

    对标 Cline cline-rules.ts:22-27 排除 workflows/ / hooks/ / skills/ 子目录。
    通过相对路径的 parts 判断，避免误匹配同名文件（如 `myworkflows/a.md` 不应被排除）。

    Args:
        file_path: 待判断的文件路径
        rules_dir: 规则根目录
        excluded_subdirs: 排除子目录名列表（如 ["workflows", "hooks", "skills"]）

    Returns:
        True 表示文件位于排除子目录中，应跳过
    """
    if not excluded_subdirs:
        return False
    try:
        rel_parts = file_path.relative_to(rules_dir).parts
    except ValueError:
        # file_path 不在 rules_dir 下，理论上不会发生（rglob 出来的都在 rules_dir 下）
        return False
    excluded_set = set(excluded_subdirs)
    # 任一层路径段命中排除列表即跳过（支持嵌套如 rules/skills/foo/bar.md）
    return any(part in excluded_set for part in rel_parts)


def _read_with_mtime_cache(
    file_path: Path,
) -> tuple[str, "FrontmatterParseResult"]:
    """读取文件并应用 mtime 缓存 — Stage 7.4 新增

    对标 Cline UnifiedConfigFileWatcher 的增量更新语义（性能特征对齐）：
        - mtime 未变化：复用缓存的 (raw_text, parse_result)，避免重复 I/O 与解析
        - mtime 变化：重新读取与解析，更新缓存

    缓存粒度：仅缓存"原始文本 + frontmatter 解析结果"，不缓存条件评估结果。
    条件评估每次都需基于当前 context 重算，不进缓存。

    Args:
        file_path: 规则文件路径

    Returns:
        (raw_text, parse_result) 元组。raw_text 已 strip()。
        mtime 读取失败时抛 OSError（不写 fallback，让上层感知）
    """
    abs_key = str(file_path.resolve())
    # stat().st_mtime_ns 返回 int 纳秒精度，避免浮点比较误差
    mtime_ns = file_path.stat().st_mtime_ns

    cached = _RULES_MTIME_CACHE.get(abs_key)
    if cached is not None and cached[0] == mtime_ns:
        # 缓存命中：复用 raw_text 与 parse_result
        return cached[1], cached[2]

    # 缓存未命中或 mtime 变化：重新读取与解析
    raw = file_path.read_text(encoding="utf-8").strip()
    parse_result = parse_yaml_frontmatter(raw)
    _RULES_MTIME_CACHE[abs_key] = (mtime_ns, raw, parse_result)
    return raw, parse_result


def clear_rules_mtime_cache() -> None:
    """清空规则 mtime 缓存 — Stage 7.4 新增

    用于测试场景或显式强制重新解析所有规则文件。
    生产环境一般无需调用，mtime 变化会自动失效单文件缓存。
    """
    _RULES_MTIME_CACHE.clear()


def load_rules_directory(
    rules_dir: Path | str,
    context: RuleEvaluationContext | None = None,
    toggles: dict[str, bool] | None = None,
    excluded_subdirs: list[str] | None = None,
) -> list[RuleLoadResult]:
    """加载规则目录下所有 .md 文件 — 对标 Cline getRuleFilesTotalContentWithMetadata

    Stage 7.4 (L6/X12) 增强:
        - 新增 excluded_subdirs 参数，跳过指定子目录（对标 Cline cline-rules.ts:22-27
          排除 workflows/ / hooks/ / skills/）
        - 引入 mtime 缓存（模块级 _RULES_MTIME_CACHE），避免无变更文件的重复 I/O
          与 frontmatter 解析（对标 Cline UnifiedConfigFileWatcher 增量更新性能特征）

    Args:
        rules_dir: 规则目录路径
        context: 评估上下文，None 时所有条件均视为通过（仅按 toggles 过滤）
        toggles: 文件路径 → 启用/禁用开关（对标 Cline ClineRulesToggles），
                 None 时默认全部启用。优先级高于 frontmatter.enabled
        excluded_subdirs: 排除子目录名列表（如 ["workflows", "hooks", "skills"]），
                          None 时不过滤（向后兼容）。任一层路径段命中即跳过该文件

    Returns:
        加载结果列表（按文件名排序），包含未激活的文件（activated=False）便于调试
    """
    rules_path = Path(rules_dir)
    if not rules_path.exists() or not rules_path.is_dir():
        return []

    if context is None:
        context = RuleEvaluationContext()

    # 收集所有 .md 文件（递归），并应用 excluded_subdirs 过滤
    # 过滤在 sorted 之后做不影响稳定性，因为 sorted 仅按文件名排序
    all_files = sorted([p for p in rules_path.rglob("*.md") if _is_rule_file(p)])
    rule_files = [
        p for p in all_files
        if not _is_path_in_excluded_subdir(p, rules_path, excluded_subdirs)
    ]

    results: list[RuleLoadResult] = []
    for file_path in rule_files:
        # toggles 优先（key 支持绝对路径和相对路径两种形式）
        rel_path = str(file_path.relative_to(rules_path)).replace("\\", "/")
        abs_path = str(file_path)
        if toggles is not None:
            toggle_key = rel_path if rel_path in toggles else abs_path
            if toggles.get(toggle_key, True) is False:
                results.append(RuleLoadResult(
                    path=file_path,
                    body="",
                    activated=False,
                    skip_reason="disabled by toggle",
                ))
                continue

        # Stage 7.4: 读取文件（应用 mtime 缓存）
        try:
            raw, parse_result = _read_with_mtime_cache(file_path)
        except OSError as e:
            logger.warning("rules_loader: 读取失败 %s: %s", file_path, e)
            continue

        if not raw:
            continue

        # fail-open：解析失败时保留原文
        if parse_result.had_frontmatter and parse_result.parse_error:
            logger.warning(
                "rules_loader: frontmatter 解析失败 %s: %s（fail-open，整体加载）",
                file_path, parse_result.parse_error,
            )
            results.append(RuleLoadResult(
                path=file_path,
                body=raw,
                frontmatter=parse_result.data,
                activated=True,
                matched_conditions={},
            ))
            continue

        # 无 frontmatter → 整体加载（向后兼容）
        if not parse_result.had_frontmatter:
            results.append(RuleLoadResult(
                path=file_path,
                body=raw,
                frontmatter={},
                activated=True,
                matched_conditions={},
            ))
            continue

        # 有 frontmatter → 评估条件
        passed, matched_conditions = evaluate_rule_conditionals(
            parse_result.data, context,
        )
        if not passed:
            results.append(RuleLoadResult(
                path=file_path,
                body=parse_result.body,
                frontmatter=parse_result.data,
                activated=False,
                matched_conditions=matched_conditions,
                skip_reason="condition not met",
            ))
            continue

        results.append(RuleLoadResult(
            path=file_path,
            body=parse_result.body,
            frontmatter=parse_result.data,
            activated=True,
            matched_conditions=matched_conditions,
        ))

    return results


def _resolve_rule_name(result: RuleLoadResult) -> str:
    """解析规则名称 — 三级优先级，对标 Cline resolveRuleFallbackName + parseRuleConfigFromMarkdown

    P1-24: 对齐 Cline 的 rule name 三级优先级解析:
        1. frontmatter 中的 name 字段（若为非空字符串）— 对标 Cline parseStringField(data.name)
        2. 文件名为 AGENTS.md 时使用 "AGENTS"（对标 Cline AGENTS_RULES_FILE_NAME 特殊处理）
        3. 文件 stem（不含扩展名）— 对标 Cline resolveRuleFallbackName 默认分支

    对标 Cline:
        - third_party/cline/.../user-instruction-config-loader.ts resolveRuleFallbackName
        - third_party/cline/.../user-instruction-config-loader.ts parseRuleConfigFromMarkdown

    Args:
        result: 单个规则文件加载结果

    Returns:
        规则名称字符串
    """
    # 1. frontmatter name 字段（最高优先级）
    fm_name = result.frontmatter.get("name")
    if isinstance(fm_name, str) and fm_name.strip():
        return fm_name.strip()
    # 2. AGENTS.md 特殊名（大小写不敏感，对标 Cline AGENTS_RULES_FILE_NAME）
    if result.path.name.upper() == "AGENTS.MD":
        return "AGENTS"
    # 3. 文件 stem（默认）
    return result.path.stem


def format_rules_content(results: list[RuleLoadResult]) -> str:
    """格式化规则加载结果为 system prompt 文本 — 对标 Cline formatRulesForSystemPrompt

    仅拼接 activated=True 的规则，统一输出格式:
        # Rules

        ## rule_name_1
        <body>

        ## rule_name_2
        <body>

    与 Cline 的差异:
        - Cline 使用 rule 文件路径/ID 作为 ## 标题
        - 本项目使用三级优先级解析 rule name（frontmatter name → AGENTS → stem）

    Args:
        results: load_rules_directory 返回值

    Returns:
        拼接后的文本（包含统一的 # Rules 标题），无激活规则时返回空字符串
    """
    parts: list[str] = []
    for r in results:
        if not r.activated:
            continue
        body = r.body.strip()
        if not body:
            continue
        # P1-24: 三级优先级解析 rule name（对齐 Cline ## name 格式）
        name = _resolve_rule_name(r)
        parts.append(f"## {name}\n\n{body}")

    if not parts:
        return ""

    return "# Rules\n\n" + "\n\n".join(parts)


def get_activated_rules_summary(results: list[RuleLoadResult]) -> list[dict[str, Any]]:
    """获取已激活规则的摘要信息（用于 UI 展示和调试）

    Returns:
        [{"name": ..., "path": ..., "matched_conditions": {...}}, ...]
    """
    return [
        {
            "name": _resolve_rule_name(r),
            "path": str(r.path),
            "matched_conditions": r.matched_conditions,
        }
        for r in results
        if r.activated
    ]


# ============================================================================
# 便捷入口 — 按当前会话 mode 加载
# ============================================================================


def load_for_session(
    rules_dir: Path | str,
    session_id: str | None = None,
    business_modes: list[str] | None = None,
    paths: list[str] | None = None,
    toggles: dict[str, bool] | None = None,
    persist_toggles: bool = False,
    excluded_subdirs: list[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """按会话上下文加载规则 — 便捷入口

    Args:
        rules_dir: 规则目录路径
        session_id: 会话 ID，None 时不按 agent mode 过滤
        business_modes: 业务模式列表（如 ["research"]），None 时不按此过滤
        paths: 候选工作空间路径列表，None 时不按此过滤
        toggles: 文件级启用/禁用开关。显式传入时跳过持久化加载（用户显式优先）
        persist_toggles: Stage 7.2 新增。True 且 toggles is None 时，
                         自动调用 synchronize_rule_toggles 加载持久化 toggle。
                         默认 False 保持向后兼容
        excluded_subdirs: Stage 7.4 新增。排除子目录名列表（如
                          ["workflows", "hooks", "skills"]），None 时不过滤。
                          透传给 load_rules_directory 与 synchronize_rule_toggles

    Returns:
        (rules_content, activated_summary)
        - rules_content: 拼接后的规则文本，可直接注入 system prompt
        - activated_summary: 已激活规则摘要
    """
    # Stage 7.2 (X6): 持久化 toggle 自动加载 — 对标 Cline refreshClineRulesToggles
    # 仅在 toggles 未显式传入且 persist_toggles=True 时加载持久化 toggle
    # Stage 7.4: 透传 excluded_subdirs，确保 toggle 列表与加载列表一致
    if toggles is None and persist_toggles:
        try:
            toggles = synchronize_rule_toggles(rules_dir, excluded_subdirs=excluded_subdirs)
        except Exception as e:
            logger.warning("rules_loader: 加载持久化 toggles 失败: %s", e)

    # 查询当前 agent mode
    # session_id 为 None 时默认 'act'（与系统默认模式一致），避免 applyTo 条件全部 fail-closed
    agent_mode: str = "act"
    if session_id:
        try:
            from agent.state import get_mode

            agent_mode = get_mode(session_id)
        except Exception as e:
            logger.debug("rules_loader: 查询 agent mode 失败 %s: %s", session_id, e)

    context = RuleEvaluationContext(
        agent_mode=agent_mode,
        business_modes=business_modes or [],
        paths=paths or [],
    )

    results = load_rules_directory(
        rules_dir,
        context=context,
        toggles=toggles,
        excluded_subdirs=excluded_subdirs,
    )
    content = format_rules_content(results)
    summary = get_activated_rules_summary(results)

    if results:
        activated_count = sum(1 for r in results if r.activated)
        logger.debug(
            "rules_loader: 加载 %d 个规则文件，激活 %d 个（agent_mode=%s, business_modes=%s）",
            len(results), activated_count, agent_mode, business_modes,
        )

    return content, summary


# ============================================================================
# Stage 7.2 (X6): Toggle 持久化 — 对标 Cline refreshClineRulesToggles +
# synchronizeRuleToggles
# ============================================================================


def _default_toggles_store_path(rules_dir: Path | str) -> Path:
    """计算默认 toggle 持久化文件路径

    默认路径: <rules_dir>/../rule_toggles.json（与 rules/ 同级，便于版本控制）
    """
    rules_path = Path(rules_dir)
    return rules_path.parent / "rule_toggles.json"


def load_toggles(store_path: Path | str) -> dict[str, bool]:
    """从 JSON 文件读取 toggles — Stage 7.2 新增

    对标 Cline stateManager.get('localClineRulesToggles')。

    Args:
        store_path: 持久化文件路径

    Returns:
        toggles dict（key 为相对路径，value 为 True/False）。
        文件不存在时返回空 dict
    """
    path = Path(store_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("load_toggles: 文件内容非 dict，返回空: %s", store_path)
            return {}
        # 校验 value 必须为 bool
        result: dict[str, bool] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, bool):
                result[k] = v
            else:
                logger.debug("load_toggles: 跳过非法条目 key=%s value=%s", k, v)
        return result
    except Exception as e:
        logger.warning("load_toggles: 读取失败 %s: %s", store_path, e)
        return {}


def save_toggles(toggles: dict[str, bool], store_path: Path | str) -> None:
    """写入 toggles 到 JSON 文件 — Stage 7.2 新增

    对标 Cline stateManager.update('localClineRulesToggles', toggles)。
    使用 UTF-8 编码、ensure_ascii=False、indent=2 便于人工查看。

    Args:
        toggles: toggles dict
        store_path: 持久化文件路径
    """
    path = Path(store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 序列化时按 key 排序，保证文件 diff 稳定
    sorted_toggles = {k: bool(v) for k, v in sorted(toggles.items())}
    path.write_text(
        json.dumps(sorted_toggles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def synchronize_rule_toggles(
    rules_dir: Path | str,
    store_path: Path | str | None = None,
    excluded_subdirs: list[str] | None = None,
) -> dict[str, bool]:
    """同步 toggle 列表与磁盘文件 — Stage 7.2 新增

    对标 Cline rule-helpers.ts synchronizeRuleToggles：
        1. 读取现有 toggles
        2. 扫描 rules_dir 下所有 .md 文件
        3. 为新文件添加默认 True
        4. 为已删除文件清理 toggle
        5. 写回存储
        6. 返回同步后的 toggles

    Stage 7.4 增强: 新增 excluded_subdirs 参数，跳过排除子目录中的文件，
    保证 toggle 列表与 load_rules_directory 实际加载列表一致。

    Args:
        rules_dir: 规则目录路径
        store_path: 持久化文件路径，None 时用默认路径
                    <rules_dir>/../rule_toggles.json
        excluded_subdirs: 排除子目录名列表（如 ["workflows", "hooks", "skills"]），
                          None 时不过滤

    Returns:
        同步后的 toggles dict（key 为相对 rules_dir 的 POSIX 路径）
    """
    rules_path = Path(rules_dir)
    if store_path is None:
        store_path = _default_toggles_store_path(rules_path)
    store_path = Path(store_path)

    # 1. 读取现有 toggles
    toggles = load_toggles(store_path)

    if not rules_path.exists() or not rules_path.is_dir():
        # rules_dir 不存在，返回空 toggles（不写盘）
        return {}

    # 2. 扫描所有 .md 规则文件，应用 excluded_subdirs 过滤，计算相对路径作为 key
    all_files = sorted([p for p in rules_path.rglob("*.md") if _is_rule_file(p)])
    rule_files = [
        p for p in all_files
        if not _is_path_in_excluded_subdir(p, rules_path, excluded_subdirs)
    ]
    current_keys: set[str] = set()
    for file_path in rule_files:
        rel = file_path.relative_to(rules_path).as_posix()
        current_keys.add(rel)
        # 3. 为新文件添加默认 True（仅当 key 不在 toggles 中时）
        if rel not in toggles:
            toggles[rel] = True

    # 4. 为已删除文件清理 toggle（key 在 toggles 中但磁盘不存在或已被排除）
    stale_keys = [k for k in toggles.keys() if k not in current_keys]
    for k in stale_keys:
        del toggles[k]

    # 5. 写回存储
    save_toggles(toggles, store_path)

    if stale_keys:
        logger.debug(
            "synchronize_rule_toggles: 同步 %d 个文件，清理 %d 个过期 toggle",
            len(current_keys), len(stale_keys),
        )

    return toggles


# ============================================================================
# Stage 13.3 (X7): global/local toggle 分离 — 对标 Cline globalState + workspaceState
# ============================================================================


def _local_toggles_store_path(session_id: str) -> Path:
    """计算 local toggle 持久化文件路径 — Stage 13.3 新增

    路径: agent_config/sessions/<session_id>/rule_toggles.local.json
    文件随会话存在，会话删除时由 session 清理逻辑一并删除。
    """
    return Path("agent_config") / "sessions" / session_id / "rule_toggles.local.json"


def load_local_toggles(session_id: str) -> dict[str, bool]:
    """加载 local toggle — Stage 13.3 新增

    Args:
        session_id: 会话 ID

    Returns:
        local toggles dict，文件不存在时返回空 dict
    """
    if not session_id:
        return {}
    path = _local_toggles_store_path(session_id)
    return load_toggles(path)


def save_local_toggles(session_id: str, toggles: dict[str, bool]) -> None:
    """保存 local toggle — Stage 13.3 新增

    Args:
        session_id: 会话 ID
        toggles: toggles dict
    """
    if not session_id:
        raise ValueError("session_id 不能为空")
    path = _local_toggles_store_path(session_id)
    save_toggles(toggles, path)
    logger.debug(
        "Stage 13.3: 保存 local toggles (session=%s, %d 项)",
        session_id, len(toggles),
    )


def clear_local_toggles(session_id: str) -> bool:
    """清空 local toggle，回退到 global — Stage 13.3 新增

    Args:
        session_id: 会话 ID

    Returns:
        True 表示已清空，False 表示文件不存在
    """
    if not session_id:
        return False
    path = _local_toggles_store_path(session_id)
    if not path.exists():
        return False
    try:
        path.unlink()
        logger.info("Stage 13.3: 已清空 local toggles (session=%s)", session_id)
        return True
    except Exception as e:
        logger.warning("Stage 13.3: 清空 local toggles 失败 %s: %s", session_id, e)
        return False


def load_merged_toggles(
    global_path: Path | str,
    session_id: str | None = None,
) -> dict[str, bool]:
    """加载合并后的 toggles（global + local） — Stage 13.3 新增

    local 覆盖 global（同 key 时 local 优先）。

    Args:
        global_path: global toggle 文件路径
        session_id: 会话 ID，None 时不加载 local

    Returns:
        合并后的 toggles dict（local 覆盖 global）
    """
    merged = load_toggles(global_path)
    if session_id:
        local_toggles = load_local_toggles(session_id)
        if local_toggles:
            merged.update(local_toggles)
            logger.debug(
                "Stage 13.3: 合并 toggles global=%d + local=%d → %d",
                len(merged) - len(local_toggles), len(local_toggles), len(merged),
            )
    return merged
