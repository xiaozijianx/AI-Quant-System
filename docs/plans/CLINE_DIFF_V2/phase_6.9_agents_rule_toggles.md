# Phase 6.9 AGENTS.md rule_toggles 对比

> 对比范围：Cline `rule-helpers.ts` 的 `synchronizeRuleToggles` + `cline-rules.ts` 的 `refreshClineRulesToggles` + `toggleClineRule.ts` 的 toggle 入口 + `state-keys.ts` 的存储定义 + `ClineRulesToggleModal.tsx` / `RuleRow.tsx` / `RulesToggleList.tsx` 的 toggle UI，与 Charles `agent/rules_loader.py` 的 `synchronize_rule_toggles` / `load_toggles` / `save_toggles` / `load_merged_toggles` / `load_local_toggles` / `save_local_toggles` / `clear_local_toggles` + `agent/server.py` 的 rule_toggles REST API + `static/js/ai-settings.js` 的 toggle UI 实现差异；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/apps/vscode/src/shared/cline-rules.ts` L1（`ClineRulesToggles = Record<string, boolean>` 类型定义）
> - `third_party/cline/apps/vscode/src/shared/storage/state-keys.ts` L67-98（`GLOBAL_STATE_FIELDS`）/ L248-295（`USER_SETTINGS_FIELDS`）/ L357-364（`LocalStateKeys`）
> - `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts` L40-104（`synchronizeRuleToggles` 核心同步函数）
> - `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/cline-rules.ts` L7-34（`refreshClineRulesToggles` global + local 双层同步入口）
> - `third_party/cline/apps/vscode/src/core/controller/file/toggleClineRule.ts` L14-67（按 scope 分发的 toggle 控制器）
> - `third_party/cline/apps/vscode/src/core/controller/file/refreshRules.ts` L16-39（统一刷新 Cline/External/Workflow 三类 toggle）
> - `third_party/cline/apps/vscode/webview-ui/src/components/cline-rules/ClineRulesToggleModal.tsx` L1-731（React Modal 主组件）
> - `third_party/cline/apps/vscode/webview-ui/src/components/cline-rules/RuleRow.tsx` L31-187（单条规则行组件）
> - `third_party/cline/apps/vscode/webview-ui/src/components/cline-rules/RulesToggleList.tsx` L4-63（规则列表组件）
>
> Charles 源码：
> - `agent/rules_loader.py` L568-683（`load_rules_directory` 接受 toggles 参数）+ L821-957（Stage 7.2 toggle 持久化：`_default_toggles_store_path` / `load_toggles` / `save_toggles` / `synchronize_rule_toggles`）+ L960-1053（Stage 13.3 global/local 分离：`_local_toggles_store_path` / `load_local_toggles` / `save_local_toggles` / `clear_local_toggles` / `load_merged_toggles`）
> - `agent/context.py` L541-609（`_load_rules_directory` 调用 `synchronize_rule_toggles` + 合并显式 toggles + 应用 frontmatter 条件过滤）
> - `agent/server.py` L2043-2137（`/sessions/{session_id}/rule_toggles` GET/PUT/DELETE REST API）
> - `static/js/ai-settings.js` L325-393（`_loadRulesTab` + `_toggleRule` HTML 表格 UI）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 rule_toggles 机制（持久化禁用/启用规则、toggle 状态存储、toggle UI）。**核心结论：toggles 核心机制已对齐（同步/加载/合并语义等价），但 scope 分层、持久化介质、local 隔离粒度、toggle key 形态存在显著差异；UI 实现强度差距极大（Cline 完整 React Modal vs Charles 简单 HTML 表格）。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.9（L2418-2435）列出 3 项对比，全部标注"已对齐"。**此标注过于乐观，实际存在未提及的差异**：

1. **"toggle 持久化 已对齐"过度简化**：双方确实都持久化，但**介质不同**——Cline 用 VSCode `globalState`/`workspaceState` API（key-value 存储，由 IDE 管理），Charles 用自管 JSON 文件（`rule_toggles.json` / `rule_toggles.local.json`）。语义等价但实现路径不同。
2. **"全局/本地分离 已对齐"未指出 scope 数量差异**：Cline 实际是 **三层** scope（global / local / remote），Charles 是**两层**（global / local，无 remote 概念）。Cline 的 `remoteRulesToggles`（GLOBAL_STATE_FIELDS L92）用于企业远程规则配置，Charles 无对应。
3. **"toggles 机制 已对齐"未指出 local 隔离粒度差异**：Cline 的 `localClineRulesToggles` 按 **workspace** 隔离（VSCode workspaceState 语义），Charles 的 `rule_toggles.local.json` 按 **session_id** 隔离（`agent_config/sessions/<session_id>/rule_toggles.local.json`）。这意味着 Cline 同一 workspace 的多个 task 共享 local toggle，Charles 同一 workspace 的不同会话有独立 local toggle。
4. **计划表未提及 toggle key 形态差异**：Cline toggle key 是**绝对路径**（`rule-helpers.ts` L61 `path.resolve(rulesDirectoryPath, filePath)`），Charles toggle key **优先用相对路径**（`rules_loader.py` L611/L614 `rel_path if rel_path in toggles else abs_path`）。

### 核心结论

1. **toggles 类型定义已对齐**：Cline `ClineRulesToggles = Record<string, boolean>`（cline-rules.ts L1）与 Charles `dict[str, bool]`（rules_loader.py 函数签名）等价，均为"路径→bool"映射。
2. **synchronize 语义等价**：双方 `synchronizeRuleToggles` / `synchronize_rule_toggles` 均实现"扫描目录 + 为新文件添加默认 True + 清理已删除文件的 toggle + 写回存储"四步流程。Charles L916-957 与 Cline L40-104 行为对齐。
3. **load 流程对齐**：Cline `getRuleFilesTotalContentWithMetadata` L220 检查 `toggles[ruleFilePath] === false` 跳过；Charles `load_rules_directory` L613-622 检查 `toggles.get(toggle_key, True) is False` 跳过。语义等价。
4. **scope 分层 Charles 是 Cline 子集**：Cline 支持 global/local/remote 三层 + cursor/windsurf/agents/workflows 多种外部规则类型；Charles 仅支持 global/local 两层，无 remote 也无外部规则类型概念。
5. **local 隔离粒度不同**：Cline 按 workspace 隔离（VSCode workspaceState），Charles 按 session_id 隔离。Charles 的设计更适合多会话并行场景（每个会话独立 toggle），但与 Cline 语义不完全一致。
6. **toggle key 形态不同**：Cline 用绝对路径（便于 VSCode UI 直接打开文件），Charles 优先用相对路径（便于跨环境迁移，但回退到绝对路径保证兼容）。Charles L611-614 的 `rel_path if rel_path in toggles else abs_path` 是双形态兼容设计。
7. **UI 实现强度差距极大**：Cline 是完整的 React Modal（ClineRulesToggleModal.tsx 731 行），支持 Rules/Hooks/Skills 三 tab 切换、global/local/remote 三 section 分组、Switch 开关 + 编辑/删除按钮、远程规则锁定标识、遥测上报；Charles 是简单 HTML 表格（ai-settings.js L325-378 共 54 行），仅展示 global/local 两列对比 + checkbox 开关，无编辑/删除按钮、无遥测、无远程规则概念。
8. **REST API 设计差异**：Cline 通过 gRPC + proto（`FileServiceClient.toggleClineRule` + `ToggleClineRuleRequest`）调用；Charles 通过 REST API（`GET/PUT/DELETE /sessions/{session_id}/rule_toggles`）。语义等价，协议不同。
9. **nanobot 残留**：P6.9 范围内（rules_loader.py + context.py toggle 相关代码 + server.py toggle API + ai-settings.js toggle UI）共 **1 处注释残留**（context.py L275，已在 P5.1/P6.7 记录），**0 处实现逻辑残留**。toggle 机制本身无任何 nanobot 痕迹。

### 一致性总体评估

- **toggles 类型定义**：**高**。`Record<string, boolean>` 与 `dict[str, bool]` 等价。
- **synchronize 语义**：**高**。四步流程（扫描+添加+清理+写回）完全对齐。
- **load 时 toggle 过滤**：**高**。双方均 `toggles[path] === false` 跳过，语义等价。
- **global/local 分离**：**中**。Charles 有两层，Cline 有三层（多 remote）。Charles 是 Cline 子集。
- **local 隔离粒度**：**中**。Cline 按 workspace，Charles 按 session_id。语义有差异但都合理。
- **持久化介质**：**中**。Cline 用 VSCode state API，Charles 用 JSON 文件。语义等价但实现不同。
- **toggle key 形态**：**中**。Cline 绝对路径，Charles 相对路径优先+绝对路径回退。
- **UI 实现**：**低**。Cline 完整 React Modal，Charles 简单 HTML 表格。功能覆盖差距大。
- **REST/gRPC 协议**：**中**。语义等价，协议不同（gRPC vs REST）。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.9.1 | toggles 类型定义 | `ClineRulesToggles = Record<string, boolean>`（cline-rules.ts L1） | `dict[str, bool]`（rules_loader.py 多处函数签名） | 高 | 双方均为"路径→bool"映射，类型等价 |
| 6.9.2 | 全局/本地分离 | 三层：`globalClineRulesToggles`（USER_SETTINGS_FIELDS L253）+ `localClineRulesToggles`（LocalStateKeys L358）+ `remoteRulesToggles`（GLOBAL_STATE_FIELDS L92）；另有 `localCursorRulesToggles`/`localWindsurfRulesToggles`/`localAgentsRulesToggles`/`workflowToggles` 等外部规则类型 | 两层：`rule_toggles.json`（global，rules_loader.py L827-833）+ `rule_toggles.local.json`（local，L965-971，按 session_id 隔离）；无 remote，无外部规则类型 | 中 | Charles 是 Cline 子集（两层 vs 三层，无 remote/外部规则）。local 隔离粒度不同（session_id vs workspace） |
| 6.9.3 | toggle 持久化 | VSCode `globalState`/`workspaceState` API（stateManager 抽象，非文件）。`setGlobalState("globalClineRulesToggles", toggles)` / `setWorkspaceState("localClineRulesToggles", toggles)` | JSON 文件：`rule_toggles.json`（global）+ `agent_config/sessions/<session_id>/rule_toggles.local.json`（local）。`save_toggles` L869-886 用 `json.dumps(..., ensure_ascii=False, indent=2)` 写入 | 中 | 介质不同（IDE state API vs JSON 文件），语义等价。Charles 文件可人工查看/版本控制，Cline state 由 IDE 管理 |
| 6.9.4 | synchronize 同步函数 | `synchronizeRuleToggles`（rule-helpers.ts L40-104）：DIRECTORY CASE 扫描+添加缺失+清理过期；FILE CASE 单文件；PATH NOT EXIST 清空全部 | `synchronize_rule_toggles`（rules_loader.py L889-957）：扫描 rglob *.md + 应用 excluded_subdirs + 添加缺失+清理过期 + 写回 | 高 | 四步流程完全对齐（扫描+添加默认True+清理+写回）。Charles 额外支持 `excluded_subdirs` 参数（对标 Cline `excludedPaths`，Stage 7.4 新增） |
| 6.9.5 | load 时 toggle 过滤 | `getRuleFilesTotalContentWithMetadata` L220：`if (ruleFilePath in toggles && toggles[ruleFilePath] === false) return null` | `load_rules_directory` L613-622：`if toggles.get(toggle_key, True) is False: results.append(RuleLoadResult(..., activated=False, skip_reason="disabled by toggle")); continue` | 高 | 语义等价（均跳过 toggle=false 的文件）。Charles 额外保留 `activated=False` 的 RuleLoadResult 便于 UI 调试 |
| 6.9.6 | toggle key 形态 | 绝对路径（`path.resolve(rulesDirectoryPath, filePath)`，rule-helpers.ts L61） | 相对路径优先 + 绝对路径回退（`rel_path if rel_path in toggles else abs_path`，rules_loader.py L614） | 中 | Cline 全用绝对路径便于 UI 直接打开文件；Charles 双形态兼容，相对路径便于跨环境迁移 |
| 6.9.7 | local 隔离粒度 | 按 workspace（VSCode workspaceState 语义，同一 workspace 的多个 task 共享 local toggle） | 按 session_id（`agent_config/sessions/<session_id>/rule_toggles.local.json`，同一 workspace 的不同会话有独立 local toggle） | 中 | 语义不同但都合理。Charles 设计更适合多会话并行，Cline 设计更符合 IDE workspace 概念 |
| 6.9.8 | load_merged 合并 | 无显式 merge 函数；`getRuleFilesTotalContentWithMetadata` 接受单个 `toggles` 参数，调用方需自行合并 global+local（cline-rules.ts L17-28 分别同步 global 和 local，未合并） | `load_merged_toggles`（rules_loader.py L1029-1053）：`merged = load_toggles(global_path); merged.update(load_local_toggles(session_id))`，local 覆盖 global | 高（Charles 更优） | Charles 显式提供 merge 语义（local 覆盖 global），Cline 调用方需自行处理。Charles 设计更清晰 |
| 6.9.9 | toggle 控制器入口 | `toggleClineRule`（toggleClineRule.ts L14-67）：按 `scope` 枚举分发到 global/local/remote 三个 state key + 遥测上报（`telemetryService.captureClineRuleToggled` L55）+ 返回三层 toggle 快照 | `update_session_rule_toggles`（server.py L2079-2116）：接收 `{toggles: {...}}` JSON，校验后调用 `save_local_toggles(session_id, clean_toggles)` 写入 local 文件。`clear_session_rule_toggles`（L2119-2137）支持 DELETE 清空 local 回退 global | 中 | Cline 单 toggle 粒度（一次一个 rule），Charles 批量写入（整个 toggles dict）。Charles 额外提供 DELETE 清空 local 接口，Cline 无对应（需逐个 toggle） |
| 6.9.10 | refresh 入口 | `refreshRules`（refreshRules.ts L16-39）：统一刷新 Cline/External/Workflow 三类 toggle，返回 `RefreshedRules` proto | `get_session_rule_toggles`（server.py L2043-2076）：按 `scope` 查询参数返回 local/merged/global | 中 | Cline 一次刷新所有规则类型，Charles 按需查询。语义等价 |
| 6.9.11 | REST/gRPC 协议 | gRPC + proto（`FileServiceClient.toggleClineRule(ToggleClineRuleRequest.create({scope, rulePath, enabled}))`，ClineRulesToggleModal.tsx L216-222） | REST + JSON（`PUT /api/chat/sessions/{id}/rule_toggles` + `{toggles: {...}}`，ai-settings.js L388） | 中 | 协议不同（gRPC vs REST），语义等价 |
| 6.9.12 | UI 实现 | `ClineRulesToggleModal`（731 行 React）+ `RuleRow`（187 行）+ `RulesToggleList`（63 行）+ `NewRuleRow` + `HookRow`。支持 Rules/Hooks/Skills 三 tab、global/local/remote 三 section、Switch 开关 + 编辑/删除按钮、远程规则锁定（`alwaysEnabled`/`isDisabled`）、tooltip 说明、遥测上报、轮询刷新 | `ai-settings.js` L325-393：`_loadRulesTab` 渲染 HTML 表格（规则文件/global 状态/local checkbox 三列）+ `_toggleRule` onchange 调用 PUT API + toast 提示 | 低 | Charles UI 功能覆盖远低于 Cline：无编辑/删除按钮、无远程规则、无 tab 切换、无 Switch 组件（用原生 checkbox）、无遥测 |
| 6.9.13 | 外部规则类型 | 支持 cursor/windsurf/agents/workflows 四种外部规则类型，每种独立 toggle（`localCursorRulesToggles`/`localWindsurfRulesToggles`/`localAgentsRulesToggles`/`workflowToggles`）+ 独立 toggle 控制器（toggleCursorRule.ts/toggleWindsurfRule.ts/toggleAgentsRule.ts/toggleWorkflow.ts）+ UI 独立分组展示 | 无外部规则类型概念，所有规则统一为 `.md` 文件，单一 toggle 体系 | 低 | Charles 无 cursor/windsurf/agents 兼容能力，但 Charles 也无需兼容这些 IDE |
| 6.9.14 | 遥测上报 | `telemetryService.captureClineRuleToggled(controller.task.ulid, ruleFileName, enabled, isGlobal)`（toggleClineRule.ts L55）+ 文件名脱敏（仅传 basename 不传全路径） | 无遥测 | 低 | Charles 无遥测，但 Charles 也无 telemetry 基础设施 |
| 6.9.15 | 文件创建/删除联动 | `createRuleFile`（rule-helpers.ts L339-393）创建后由 `refreshRules` 自动同步 toggle；`deleteRuleFile`（L398-466）删除后立即从对应 state key 移除 toggle（L424-452 按 isGlobal+type 分发） | `synchronize_rule_toggles` 在每次 `build()` 时调用（context.py L559），自动同步新文件/清理已删除文件；无独立 create/delete API | 中 | 双方均自动同步，Cline 更主动（删除时立即移除），Charles 依赖 build 触发同步 |
| 6.9.16 | remote 规则 | `remoteRulesToggles`（GLOBAL_STATE_FIELDS L92）+ `synchronizeRemoteRuleToggles`（rule-helpers.ts L110-134）+ `getRemoteRulesTotalContentWithMetadata`（L261-297）+ UI 锁定标识（`alwaysEnabled`/`isDisabled`，RuleRow.tsx L46/L161） | 无 remote 概念 | 低 | Charles 无企业远程规则配置能力，但 Charles 也无远程配置基础设施 |

---

## 三、源码细节对比

### 3.1 Cline synchronizeRuleToggles（rule-helpers.ts L40-104）

```typescript
export async function synchronizeRuleToggles(
    rulesDirectoryPath: string,
    currentToggles: ClineRulesToggles,
    allowedFileExtension = "",
    excludedPaths: string[][] = [],
): Promise<ClineRulesToggles> {
    const updatedToggles = { ...currentToggles }
    // DIRECTORY CASE: 扫描 + 添加缺失 + 清理过期
    // FILE CASE: 单文件
    // PATH NOT EXIST: 清空全部
    return updatedToggles
}
```

**关键点**：
- 三分支处理（DIRECTORY / FILE / PATH NOT EXIST），Charles 仅处理 DIRECTORY 场景
- `excludedPaths` 参数为 `string[][]`（二维数组，如 `[[".clinerules", "workflows"]]`）
- 返回新 toggles，不修改原对象（不可变语义）

### 3.2 Charles synchronize_rule_toggles（rules_loader.py L889-957）

```python
def synchronize_rule_toggles(
    rules_dir: Path | str,
    store_path: Path | str | None = None,
    excluded_subdirs: list[str] | None = None,
) -> dict[str, bool]:
    # 1. 读取现有 toggles
    # 2. 扫描所有 .md 规则文件，应用 excluded_subdirs 过滤
    # 3. 为新文件添加默认 True
    # 4. 为已删除文件清理 toggle
    # 5. 写回存储
    # 6. 返回同步后的 toggles
```

**关键差异**：
- `excluded_subdirs` 为 `list[str]`（一维数组，如 `["workflows", "hooks", "skills"]`），语义不同但效果等价
- 直接修改并返回 toggles（可变语义，Python 风格）
- 显式 `store_path` 参数，默认 `<rules_dir>/../rule_toggles.json`
- Stage 7.4 增强的 `excluded_subdirs` 与 Cline `excludedPaths` 对齐（context.py L554 `["workflows", "hooks", "skills"]`）

### 3.3 Cline refreshClineRulesToggles（cline-rules.ts L7-34）

```typescript
export async function refreshClineRulesToggles(controller, workingDirectory) {
    // Global toggles
    const globalClineRulesToggles = controller.stateManager.getGlobalSettingsKey("globalClineRulesToggles")
    const updatedGlobalToggles = await synchronizeRuleToggles(globalClineRulesFilePath, globalClineRulesToggles)
    controller.stateManager.setGlobalState("globalClineRulesToggles", updatedGlobalToggles)
    // Local toggles（excludedPaths 排除 workflows/hooks/skills）
    const localClineRulesToggles = controller.stateManager.getWorkspaceStateKey("localClineRulesToggles")
    const updatedLocalToggles = await synchronizeRuleToggles(localClineRulesFilePath, localClineRulesToggles, "", [
        [".clinerules", "workflows"], [".clinerules", "hooks"], [".clinerules", "skills"],
    ])
    controller.stateManager.setWorkspaceState("localClineRulesToggles", updatedLocalToggles)
    return { globalToggles: updatedGlobalToggles, localToggles: updatedLocalToggles }
}
```

**关键点**：
- 显式分离 global 和 local 两次同步
- local 同步时排除 `workflows/hooks/skills` 子目录（与 Charles context.py L554 一致）

### 3.4 Charles _load_rules_directory（context.py L541-609）

```python
def _load_rules_directory(self, task_type: str) -> list[RuleLoadResult]:
    excluded_subdirs = ["workflows", "hooks", "skills"]
    merged_toggles: dict[str, bool] = {}
    # 1. 同步磁盘 toggles（作为默认值）
    persisted = synchronize_rule_toggles(self.rules_dir, excluded_subdirs=excluded_subdirs)
    merged_toggles.update(persisted)
    # 2. 应用显式传入的 toggles（用户显式设置优先）
    if self.rule_toggles:
        merged_toggles.update(self.rule_toggles)
    # 3. 兼容层：加载 rules/<task_type>.md，并禁用扫描重复
    ...
    directory_results = load_rules_directory(self.rules_dir, context=context, toggles=merged_toggles or None, excluded_subdirs=excluded_subdirs)
```

**关键差异**：
- Charles 在加载时合并 `synchronize_rule_toggles`（磁盘同步）+ `self.rule_toggles`（显式传入）+ 兼容层禁用
- Cline 的 `getRuleFilesTotalContentWithMetadata` 只接受单个 `toggles` 参数，调用方需自行合并
- Charles 的合并优先级：显式传入 > 磁盘同步（synchronize）> 默认 True

### 3.5 Cline toggleClineRule（toggleClineRule.ts L14-67）

```typescript
export async function toggleClineRule(controller, request: ToggleClineRuleRequest) {
    const { scope, rulePath, enabled } = request
    switch (scope) {
        case RuleScope.GLOBAL: // 写 globalClineRulesToggles
        case RuleScope.LOCAL:  // 写 localClineRulesToggles
        case RuleScope.REMOTE: // 写 remoteRulesToggles
    }
    // 遥测上报（脱敏文件名）
    if (controller.task?.ulid) {
        telemetryService.captureClineRuleToggled(controller.task.ulid, ruleFileName, enabled, isGlobal)
    }
    // 返回三层 toggle 快照
    return ToggleClineRules.create({ globalClineRulesToggles, localClineRulesToggles, remoteRulesToggles })
}
```

**关键点**：
- 单 toggle 粒度（一次一个 rule）
- 按 scope 枚举分发
- 遥测上报 + 文件名脱敏（仅传 basename）
- 返回三层 toggle 快照供 UI 更新

### 3.6 Charles update_session_rule_toggles（server.py L2079-2116）

```python
@router.put("/sessions/{session_id}/rule_toggles")
async def update_session_rule_toggles(session_id: str, request: Request):
    body = await request.json()
    toggles = body.get("toggles")
    if not isinstance(toggles, dict):
        return {"status": "error", "message": "toggles 必须是 dict"}
    if not session_id:
        return {"status": "error", "message": "session_id 不能为空"}
    clean_toggles: dict[str, bool] = {}
    for k, v in toggles.items():
        if isinstance(k, str) and isinstance(v, bool):
            clean_toggles[k] = v
    save_local_toggles(session_id, clean_toggles)
    return {"status": "ok", "message": ..., "toggles": clean_toggles}
```

**关键差异**：
- 批量写入（整个 toggles dict）
- 仅支持 local scope（无 global/remote scope 参数）
- 校验 value 必须为 bool（`isinstance(v, bool)`）
- 无遥测
- Charles 额外提供 `DELETE /sessions/{session_id}/rule_toggles` 清空 local 回退 global（Cline 无对应）

### 3.7 Cline UI（ClineRulesToggleModal.tsx 摘要）

```tsx
// 731 行 React Modal
- 三个 tab: Rules / Hooks / Skills（currentView state）
- Rules tab 内三个 section: Enterprise Rules / Global Rules / Workspace Rules
- 每条规则用 RuleRow 组件（Switch 开关 + 编辑按钮 + 删除按钮）
- 远程规则锁定标识（alwaysEnabled + isDisabled + tooltip "This rule is required"）
- 外部规则类型图标（cursor/windsurf/agents SVG icon）
- 打开时自动调 refreshRules 同步
- Hooks tab 轮询 1s 刷新（setInterval）
- Skills tab 轮询 1s 刷新
```

### 3.8 Charles UI（ai-settings.js L325-393）

```javascript
async _loadRulesTab() {
    // 查询 merged + global 两份 toggles
    const [mergedResp, globalResp] = await Promise.all([
        this.apiGet(`/api/chat/sessions/${sid}/rule_toggles?scope=merged`),
        this.apiGet(`/api/chat/sessions/${sid}/rule_toggles?scope=global`),
    ]);
    // 渲染 HTML 表格：规则文件 | global 状态 | local checkbox
    let html = `<table class="rules-table">
        <thead><tr><th>规则文件</th><th>global</th><th>本会话 local</th></tr></thead>
        <tbody>`;
    for (const k of keys) {
        const gval = globalToggles[k] !== false;
        const lval = merged[k] !== false;
        html += `<tr><td>${k}</td><td>${gval ? '启用' : '禁用'}</td>
            <td><label class="switch"><input type="checkbox" ${lval ? 'checked' : ''}
                onchange="AI_SETTINGS._toggleRule('${k}', this.checked)"></label></td></tr>`;
    }
}
async _toggleRule(ruleKey, enabled) {
    // 先读 local toggles，合并本次变更，再 PUT 写回
    const resp = await this.apiGet(`.../rule_toggles?scope=local`);
    const toggles = resp.toggles || {};
    toggles[ruleKey] = enabled;
    await this.apiSend(`.../rule_toggles`, 'PUT', { toggles });
    this.toast(`规则 ${ruleKey} 已${enabled ? '启用' : '禁用'}`);
}
```

**关键差异**：
- Charles 表格三列：规则文件名 / global 状态（只读）/ local checkbox（可编辑）
- Charles 用原生 checkbox + CSS switch 样式，Cline 用 `<Switch>` 组件
- Charles 无编辑/删除按钮（需另去文件管理界面）
- Charles 无 tab 切换（仅 Rules，无 Hooks/Skills）
- Charles 无远程规则锁定
- Charles 无遥测

---

## 四、nanobot 残留专项检查

### 4.1 P6.9 范围内文件清单

| 文件 | 行数 | 检查范围 |
|------|------|---------|
| `agent/rules_loader.py` | 1053 | 全文（toggle 相关 L568-1053） |
| `agent/context.py` | 2666 | 全文（toggle 相关 L541-609） |
| `agent/server.py` | 2137+ | toggle API L2043-2137 |
| `static/js/ai-settings.js` | 393+ | toggle UI L325-393 |

### 4.2 残留统计

| 残留类型 | 数量 | 位置 | 内容 | 严重程度 |
|---------|------|------|------|---------|
| 注释残留 | 1 | `agent/context.py` L275 | `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。保留参数签名仅为向后兼容，当前无调用方传入。` | 低（已标注"已废弃"+ "Cline 无此概念"，仅为历史说明，非实现逻辑） |
| 实现逻辑残留 | 0 | - | - | - |

### 4.3 残留详情

**唯一残留**（context.py L275）：
```python
extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。
                保留参数签名仅为向后兼容，当前无调用方传入。
```

**分析**：
- 此残留是 `SystemPromptBuilder.__init__` 的参数 docstring，描述 `extra_sections` 参数的历史来源
- 已明确标注"[已废弃]"和"Cline 无此概念"，是诚实的历史说明
- 不影响 toggle 机制实现逻辑
- 此残留已在 P5.1（SystemPromptBuilder 架构对比）和 P6.7（AGENTS.md 加载机制对比）中记录，P6.9 范围内无新增残留

### 4.4 toggle 机制本身无 nanobot 痕迹

- `rules_loader.py` 全文 0 处 nanobot 字样
- `server.py` toggle API 0 处 nanobot 字样
- `ai-settings.js` toggle UI 0 处 nanobot 字样
- toggle 机制是 Stage 7.2（X6）+ Stage 13.3（X7）全新实现，无 nanobot 历史包袱

---

## 五、一致性等级汇总

| 维度 | 等级 | 说明 |
|------|------|------|
| toggles 类型定义 | 高 | `Record<string, boolean>` ≡ `dict[str, bool]` |
| synchronize 同步语义 | 高 | 四步流程完全对齐 |
| load 时 toggle 过滤 | 高 | 双方均 `=== false` 跳过 |
| global/local 分离 | 中 | Charles 两层，Cline 三层（多 remote） |
| local 隔离粒度 | 中 | session_id vs workspace |
| 持久化介质 | 中 | JSON 文件 vs VSCode state API |
| toggle key 形态 | 中 | 相对路径优先 vs 绝对路径 |
| load_merged 合并 | 高（Charles 更优） | Charles 显式 merge 函数，Cline 需调用方自行合并 |
| toggle 控制器入口 | 中 | 单 toggle 粒度 vs 批量写入 |
| refresh 入口 | 中 | 一次刷新所有类型 vs 按需查询 |
| REST/gRPC 协议 | 中 | 协议不同，语义等价 |
| UI 实现 | 低 | 完整 React Modal vs 简单 HTML 表格 |
| 外部规则类型 | 低 | cursor/windsurf/agents/workflows vs 无 |
| 遥测上报 | 低 | 有 vs 无 |
| 文件创建/删除联动 | 中 | 删除时立即移除 vs build 触发同步 |
| remote 规则 | 低 | 有 vs 无 |

---

## 六、改进建议

### 6.1 高优先级（功能缺失）

1. **补齐 global scope 的 toggle API**：Charles 当前仅支持 local scope 的 PUT/DELETE，无 global scope 的 toggle API。用户只能编辑 `rule_toggles.json` 文件修改 global。建议增加 `PUT /api/chat/rule_toggles` 接口支持 global scope 写入。
2. **UI 增加编辑/删除按钮**：Charles UI 仅能切换 toggle，无法编辑/删除规则文件。建议在表格行增加"编辑"按钮（跳转到文件编辑页）和"删除"按钮（调 `DELETE /api/chat/rules/<filename>`）。

### 6.2 中优先级（体验优化）

3. **UI 增加 Switch 组件**：当前用原生 checkbox + CSS，视觉反馈不如 Switch 组件明显。可引入轻量 CSS Switch 组件库或自实现。
4. **toggle key 标准化**：建议明确文档化 Charles 的"相对路径优先 + 绝对路径回退"策略，避免调用方混淆。或在 `synchronize_rule_toggles` 中强制统一为相对路径。

### 6.3 低优先级（对齐 Cline 但 Charles 可能不需要）

5. **remote 规则概念**：Charles 无远程配置基础设施，无需补齐 remote scope。如未来接入企业远程配置再考虑。
6. **遥测上报**：Charles 无 telemetry 基础设施，无需补齐。如未来接入再考虑。
7. **外部规则类型**：Charles 无需兼容 cursor/windsurf/agents IDE，无需补齐。

---

## 七、验证方法

### 7.1 已验证项

- ✅ Cline `synchronizeRuleToggles` 三分支处理（DIRECTORY/FILE/PATH NOT EXIST）
- ✅ Charles `synchronize_rule_toggles` 四步流程（读取/扫描/添加/清理/写回）
- ✅ 双方 toggle 过滤语义（`=== false` 跳过）
- ✅ Cline 三层 scope（global/local/remote）+ Charles 两层（global/local）
- ✅ Charles local 按 session_id 隔离 + Cline local 按 workspace 隔离
- ✅ Cline UI 完整功能 + Charles UI 简化功能
- ✅ nanobot 残留：1 处注释残留（context.py L275），0 处实现逻辑残留

### 7.2 未验证项（超出 P6.9 范围）

- ⚠️ Charles `extra_sections` 参数是否真有调用方传入（需检查所有 `SystemPromptBuilder(...)` 调用点）
- ⚠️ Charles `synchronize_rule_toggles` 的 `excluded_subdirs` 是否与 Cline `excludedPaths` 在所有场景下行为一致（需端到端测试）

---

## 八、结论

P6.9 AGENTS.md rule_toggles 对比完成。**核心 toggle 机制（synchronize/load/merge 语义）已对齐，但 scope 分层、local 隔离粒度、持久化介质、UI 实现强度存在显著差异。** 计划文件"已对齐"标注过于乐观，实际 Charles 是 Cline 的功能子集（两层 vs 三层，无 remote/外部规则类型，UI 简化）。

**nanobot 残留**：P6.9 范围内 1 处注释残留（context.py L275，已在前序阶段记录），0 处实现逻辑残留。toggle 机制本身是 Stage 7.2 + Stage 13.3 全新实现，无 nanobot 历史包袱。

**建议优先级**：补齐 global scope toggle API（高）> UI 增加编辑/删除按钮（高）> UI Switch 组件（中）> toggle key 标准化（中）> remote/遥测/外部规则类型（低，Charles 可能不需要）。
