# -*- coding: utf-8 -*-
"""工具输出限制常量 — 对标 Cline output-limits.ts

统一管理所有工具的输出长度限制，便于调整。

设计说明:
    - Cline 源码位置: sdk/packages/core/src/extensions/tools/executors/output-limits.ts
    - 每个字符都会在后续请求中重新发送给模型，过大的输出会导致 token 成本二次增长
    - 各工具的截断逻辑保留原位置，仅常量值统一到本文件
    - 数值保留各工具已验证的现有值，避免改变行为

Cline 原始常量（参考）:
    MAX_COMMAND_OUTPUT_CHARS = 48000  # Cline 命令输出上限
    MAX_READ_LINES = 2000              # Cline 单次读取行数上限
    MAX_LINE_CHARS = 2000              # Cline 单行字符上限
    MAX_READ_OUTPUT_CHARS = 48000      # Cline 单次读取字符上限
    MAX_SEARCH_OUTPUT_CHARS = 48000    # Cline 搜索输出字符上限

P1-11 起对齐 Cline 关键常量:
    - MAX_OUTPUT_PER_COMMAND = 48000（原 8000，对标 Cline head+tail 截断）
    - DEFAULT_COMMAND_TIMEOUT_SECONDS = 30（原 60，对标 Cline bash.ts DEFAULT_TIMEOUT）
其他常量沿用各工具已验证的数值。若后续需要调整，可统一修改本文件。
"""

# ============================================================================
# 命令执行类工具 — run_commands.py / exec_tool.py
# ============================================================================

# 单条命令 stdout 字符上限 — 防止撑爆上下文
# 用于 run_commands.py _MAX_OUTPUT_PER_COMMAND
# P1-11: 对标 Cline MAX_COMMAND_OUTPUT_CHARS=48000，head+tail 截断（前 24000 + 后 24000）
MAX_OUTPUT_PER_COMMAND = 48000

# 单条命令 stderr 字符上限
# 用于 run_commands.py _MAX_STDERR_PER_COMMAND
MAX_STDERR_PER_COMMAND = 2000

# 旧版 exec_tool.py 的合并输出字符上限（stdout + stderr）
# 用于 exec_tool.py _MAX_OUTPUT
MAX_COMMAND_OUTPUT_CHARS = 16000

# 单次执行的最大命令数 — 防止 LLM 滥用
# 用于 run_commands.py _MAX_COMMANDS
MAX_COMMANDS = 10

# 命令执行默认超时秒数
# P1-11: 对标 Cline bash.ts DEFAULT_TIMEOUT=30s，从 60s 降到 30s
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30

# 命令执行最大超时秒数
MAX_COMMAND_TIMEOUT_SECONDS = 600

# ============================================================================
# 文件读取类工具 — file_tools.py
# ============================================================================

# 单次读取文件默认行数上限
# 用于 file_tools.py _DEFAULT_LIMIT
MAX_READ_LINES = 2000

# 单行字符上限 — 对标 Cline MAX_LINE_CHARS (output-limits.ts L44)
# 用于 read_files.py / search_codebase.py / run_commands.py 单行截断
# P2-7: 从各工具硬编码提取为全局常量，便于统一调整
MAX_LINE_CHARS = 2000

# 单次读取文件字符上限
# 用于 file_tools.py _MAX_CHARS
MAX_READ_OUTPUT_CHARS = 16000

# ============================================================================
# 文件列表类工具 — list_files.py
# ============================================================================

# 单次列出文件/目录条目上限
# 用于 list_files.py _MAX_ENTRIES
MAX_LIST_ENTRIES = 200

# ============================================================================
# 搜索类工具 — search_codebase.py
# ============================================================================

# 单查询最多返回的匹配数
# 用于 search_codebase.py _MAX_MATCHES_PER_QUERY
MAX_SEARCH_MATCHES_PER_QUERY = 50

# 单文件最多返回的匹配行数
# 用于 search_codebase.py _MAX_MATCHES_PER_FILE
MAX_SEARCH_MATCHES_PER_FILE = 20

# ============================================================================
# Web 抓取类工具 — fetch_web_content.py
# ============================================================================

# 单次抓取网页内容字符上限
# 用于 fetch_web_content.py _MAX_CONTENT_CHARS
# 对标 Cline web-fetch.ts 硬编码的 50000 字符截断
MAX_WEB_CONTENT_CHARS = 50000


# ============================================================================
# 工具预设 — Stage 8.5 新增，对标 Cline ToolPresets
# ============================================================================
# 设计说明（对标 Cline sdk/packages/core/src/extensions/tools/presets.ts:20-109）:
#     Cline 通过 ToolPresets 静态配置各 mode 启用的工具集，5 种预设:
#         act / plan / search / minimal / yolo
#     每种预设是一组 enableXxx 布尔开关，createDefaultToolsWithPreset 按 preset 创建工具集。
#
# 本系统不引入预设机制，实际工具过滤由 agent/tools/routing.py 的 mode-based 路由实现
# （动态规则比静态预设更灵活）。此处仅文档化各 mode 的工具集预期，
# 便于排查 routing 规则与实际行为的差异。
#
# 与 Cline 的差异:
#     - 不支持 search / minimal / yolo 预设（量化场景无需求）
#     - yolo 模式涉及实盘交易安全，不默认开启；如需启用应在
#       agent_config/execution_mode.yaml 中显式配置
#     - 实际工具过滤以 agent/tools/routing.py 的 ToolRoutingRule 为准，
#       本字典仅作文档参考，不参与运行时过滤
#
# 字段说明:
#     True  = 该 mode 下工具启用
#     False = 该 mode 下工具禁用（如 Plan Mode 禁用写入类工具）
TOOL_PRESETS: dict[str, dict[str, bool]] = {
    # act 模式：完整工具集，允许所有读写操作
    "act": {
        "read_files": True,
        "search_codebase": True,
        "list_files": True,
        "fetch_web_content": True,
        "editor": True,
        "apply_patch": True,
        "skills": True,
        "ask_question": True,
    },
    # plan 模式：只读工具集，禁用写入类工具（editor / apply_patch）
    # 对标 Cline Plan Mode：只读分析，不修改文件
    "plan": {
        "read_files": True,
        "search_codebase": True,
        "list_files": True,
        "fetch_web_content": True,
        "editor": False,
        "apply_patch": False,
        "skills": True,
        "ask_question": True,
    },
}


def resolve_tool_preset(mode: str) -> dict[str, bool]:
    """按 mode 返回工具预设字典 — Stage 8.5 新增，对标 Cline resolveToolPresetName

    仅文档化用途：返回 TOOL_PRESETS 中对应 mode 的预设副本。
    实际工具过滤仍由 agent/tools/routing.py 的 ToolRoutingRule 实现，
    本函数不参与运行时过滤。

    Args:
        mode: agent 模式（act / plan）

    Returns:
        该 mode 下各工具的启用状态字典。未知 mode 回退到 act 预设。
    """
    return dict(TOOL_PRESETS.get(mode, TOOL_PRESETS["act"]))
