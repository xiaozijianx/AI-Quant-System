# Phase 7.12 Plugin / Marketplace 对比

> 对比范围：Cline `sdk/packages/core/src/extensions/plugin/` 的插件内核（plugin-config-loader / plugin-loader / plugin-module-import / plugin-sandbox / plugin-sandbox-bootstrap / plugin-targeting / plugin-load-report）+ `apps/vscode/src/core/controller/marketplace/` 的远程市场（catalog 拉取 / 安装 / 卸载 / 列表 / 启用禁用切换）共 15 个文件，与 Charles `agent/types.py` + `agent/runtime.py` 的 `plugins` 预留字段逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> 本阶段聚焦"Plugin / Marketplace 系统"维度，是 Cline 第三方扩展能力的总入口：plugin 内核（Y1-Y4）+ marketplace 远程市场（Y5-Y7）。Charles 在 Stage 8 已明确决策"Y 阶段不实施"，仅保留 `plugins` 预留字段。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-config-loader.ts`（L1-285，路径发现 + 禁用过滤 + Skill 目录收集 + 统一加载入口）
> - `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-loader.ts`（L1-200，manifest 校验 + setup 上下文注入 + 顺序加载 + 重名覆盖）
> - `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-module-import.ts`（L1-648，jiti 动态加载 + 依赖预检 + 工作区别名 + Bun 二进制兼容）
> - `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-sandbox.ts`（L1-614，SubprocessSandbox RPC + 贡献注册 + Hook 桥接 + 超时 + reinit 保护）
> - `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-sandbox-bootstrap.ts`（L1-736，子进程入口 + RPC 派发 + 插件映射维护）
> - `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-targeting.ts`（L1-32，providerId/modelId 双重过滤）
> - `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-load-report.ts`（L1-20，PluginInitializationFailure / Warning / LoadDiagnostics 类型）
> - `third_party/cline/apps/vscode/src/core/controller/marketplace/getMarketplaceCatalog.ts`（L1-8，catalog 拉取 RPC 入口）
> - `third_party/cline/apps/vscode/src/core/controller/marketplace/installMarketplaceEntry.ts`（L1-20，安装 RPC 入口 + 后置动作分支）
> - `third_party/cline/apps/vscode/src/core/controller/marketplace/uninstallMarketplaceEntry.ts`（L1-17，卸载 RPC 入口）
> - `third_party/cline/apps/vscode/src/core/controller/marketplace/marketplace-helpers.ts`（L1-592，远程 catalog + 三分支安装/卸载 + 密钥脱敏 + 超时 + 本地聚合视图）
> - `third_party/cline/apps/vscode/src/core/controller/marketplace/listMarketplaceInstalledEntries.ts`（L1-10，从 catalog 过滤已安装）
> - `third_party/cline/apps/vscode/src/core/controller/marketplace/listMarketplaceLocalInstalledEntries.ts`（L1-11，本地已安装聚合）
> - `third_party/cline/apps/vscode/src/core/controller/marketplace/toggleMarketplaceLocalInstalledEntry.ts`（L1-13，启用/禁用切换）
> - `third_party/cline/apps/vscode/src/core/controller/marketplace/uninstallMarketplaceLocalInstalledEntry.ts`（L1-10，本地卸载）
>
> Charles 源码：
> - `agent/types.py` L569-571（`plugins: list[Any]` 预留字段，注释明确"当前不实现加载逻辑"）
> - `agent/runtime.py` L307-309（`self._plugins: list[Any] = list(config.plugins)`，仅存储不处理）
> - 注：`agent/skills/loader.py` L59 / `agent/skills/registry.py` L74/L114 / `agent/skills/skill_tool.py` L26/L70/L127/L164 中出现的 `user-instruction-plugin.ts` 是 Cline 技能系统的**配置加载器**（skill frontmatter toggle + allowedSkillSet），**不是** plugin/marketplace 系统，归属 P4.x / P5.x 阶段，不在 P7.12 范围内。

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 Plugin / Marketplace 系统。**核心结论：Charles 在 Stage 8 已明确决策"Y 阶段不实施"，仅有 `plugins: list[Any]` 预留字段（types.py L571 + runtime.py L309）做存储不处理，无任何插件加载、沙箱、marketplace 远程市场实现。Cline 该模块合计 3216 行 TypeScript，是 Charles 全阶段对比中"主动选择不实施"规模最大的模块。该决策与 Charles 单进程 + OpenAI 兼容协议 + 量化场景内部迭代的架构原则一致。**

### 核心结论

1. **Plugin 系统完全缺失**：Cline 实现了完整的"路径发现 → manifest 校验 → jiti 动态加载 → 沙箱隔离 → 贡献注册 → Hook 桥接"七层插件链路（plugin-config-loader 285 行 + plugin-loader 200 行 + plugin-module-import 648 行 + plugin-sandbox 614 行 + plugin-sandbox-bootstrap 736 行 + plugin-targeting 32 行 + plugin-load-report 20 行 = 2535 行）；Charles 仅有 `plugins: list[Any] = field(default_factory=list)`（types.py L571）+ `self._plugins = list(config.plugins)`（runtime.py L309）共 2 行预留代码，注释明确"Stage 8 已确认 Y 阶段不实施"。

2. **Marketplace 完全缺失**：Cline 实现了完整的"远程 catalog 拉取 → sanitizeEntry 校验 → 三分支安装（mcp/skill/plugin）→ 三分支卸载 → 本地已安装聚合 → 启用/禁用切换"链路（marketplace-helpers 592 行 + 6 个 RPC 入口文件共 89 行 = 681 行），含密钥脱敏（多组正则）+ 120 秒超时 + 12000 字符输出截断 + Windows shell 兼容等安全设施；Charles 完全无实现。

3. **plugin-targeting 缺失但场景匹配度低**：Cline `plugin-targeting.ts` L8-32 实现 `matchesPluginManifestTargeting` 按 `providerIds` + `modelIds` 双重过滤插件激活范围（空数组=匹配所有 + 保守不匹配策略）。Charles 已有 `agent/providers/` 多 provider 支持（P7.4 对比），但无插件层级 targeting——量化场景下 provider 集中（OpenAI/Qwen），且无第三方插件，targeting 机制无适用对象。

4. **plugin-sandbox 进程隔离缺失**：Cline `plugin-sandbox.ts` + `plugin-sandbox-bootstrap.ts` 合计 1350 行，通过 `SubprocessSandbox` 在隔离 Node 子进程中加载插件，RPC 协议 + 超时配置（import 4s/hook 3s/contribution 60s）+ 并发 reinit 保护 + bootstrap 文件解析。Charles 工具直接在主进程 asyncio 事件循环中执行（`agent/runtime.py`），无进程隔离——因 Charles 无第三方插件，无隔离需求。

5. **plugin-module-import 动态加载缺失**：Cline `plugin-module-import.ts` 648 行，基于 jiti 实现 TS/JS 动态加载，含静态分析 import/require 语句 + 依赖预检 + 工作区别名（`@cline/sdk` → src 源码路径）+ Host-runtime SDK specifier 注入 + Bun 编译二进制兼容。Python 生态下无 jiti 1:1 等价物，可用 `importlib` + manifest YAML 校验作为最小替代，但工作量与收益不匹配。

6. **marketplace 安全设施缺失**：Cline `marketplace-helpers.ts` L51-58 实现三层密钥脱敏（`SECRET_KEY_VALUE_PATTERN` + `SECRET_BEARER_VALUE_PATTERN` + `SECRET_AUTHORIZATION_VALUE_PATTERN`），覆盖 `api_key/access_token/refresh_token/authorization/secret/password/credential` 七类敏感字段；L51 `INSTALL_COMMAND_TIMEOUT_MS = 120_000` + 125 秒 SIGKILL 兜底；L52 `MAX_OUTPUT_CHARS = 12_000` 输出截断。Charles 无远程市场，无密钥脱敏需求。

7. **官方插件识别缺失**：Cline `marketplace-helpers.ts` 实现 `isOfficialPluginInstalled`：计算 `official:https://github.com/cline/plugins.git#plugins/<source>` 的 sha256 前 12 位 + 检查 `~/.cline/plugins/_installed/official/<sanitized>-<hash>` 路径存在。Charles 无官方插件仓库概念。

8. **install/uninstall 不对称语义缺失**：Cline `installMarketplaceEntry.ts` L13-18 安装后按类型分支：mcp → `reconcileMcpServersFromSettingsRPC`；skill/plugin → `invalidateUserInstructionService`。`uninstallMarketplaceEntry.ts` L13-16 卸载后：**mcp 不调用 invalidate**（由 mcpHub 自己 reconcile），skill/plugin 调用 invalidate。Charles 无此不对称语义——因无安装/卸载链路。

9. **本地已安装聚合视图缺失**：Cline `listMarketplaceLocalInstalledEntries.ts` + `marketplace-helpers.ts::listLocalMarketplaceInstalledEntries` 聚合 MCP servers + Skills + Plugins 三态本地已安装清单，含 `normalizeMatchValue`（小写 + 非 alnum 转 `-` + 去首尾 `-`）宽松匹配 + `getPluginDisplayName`（向上查找 package.json 取 name）+ source 分类（remote/global/workspace）。Charles 的本地 skills 列表由 `agent/skills/registry.py` 提供（P4.3 对比），MCP servers 由 `agent/mcp/registry.py` 提供（P7.8 对比），但无统一聚合视图。

10. **nanobot 残留**：P7.12 范围内（`agent/types.py` L569-571 + `agent/runtime.py` L307-309 共 4 行预留代码）共 **0 处注释残留 + 0 处实现逻辑残留**。预留字段的注释仅对标"Stage 8 / Y 阶段"，无 "nanobot" 字样。`agent/skills/` 下的 nanobot 残留属 P4.20 范围。

### 一致性总体评估

| 维度 | 一致性等级 | 说明 |
|------|-----------|------|
| Plugin 内核（路径发现 + 加载 + 沙箱 + targeting） | 缺失 | Charles 仅有 2 行预留字段，0 行实现 |
| Marketplace 远程市场（catalog + 安装 + 卸载 + 列表） | 缺失 | Charles 完全无实现 |
| 安全设施（密钥脱敏 + 超时 + 输出截断） | 缺失 | Charles 无远程市场，无安全设施需求 |
| 官方插件识别（sha256 + 路径校验） | 缺失 | Charles 无官方插件仓库概念 |
| install/uninstall 不对称语义 | 缺失 | Charles 无安装/卸载链路 |
| 本地已安装聚合视图 | 缺失 | Charles 各模块独立提供列表，无统一聚合 |
| 预留字段 | 高 | Charles `plugins: list[Any]` 预留字段语义清晰，注释明确"不实施" |

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.12.1 | Plugin 系统总入口 | `plugin-config-loader.ts` L1-285 `resolveAndLoadAgentPlugins` 统一入口 + `in_process`/`sandbox` 双模式分发 | `agent/types.py` L571 `plugins: list[Any] = field(default_factory=list)` + `agent/runtime.py` L309 `self._plugins = list(config.plugins)` | 缺失 | Charles 仅 2 行预留字段，0 行实现。注释明确"Stage 8 已确认 Y 阶段不实施" |
| 7.12.2 | plugin-loader | `plugin-loader.ts` L1-200 `loadAgentPluginFromPath` + `validatePluginExport` + `validatePluginManifest` + `loadAgentPluginsFromPathsWithDiagnostics`（顺序加载 + 单个失败不影响其他 + 按 name 去重覆盖 + targeting 过滤 + order 保留） | 无 | 缺失 | Charles 无插件加载逻辑 |
| 7.12.3 | plugin-sandbox | `plugin-sandbox.ts` L1-614 `loadSandboxedPlugins` + `SubprocessSandbox` RPC + 贡献注册（tools/commands/rules/messageBuilders/simpleContributions）+ Hook 桥接 + 超时配置 + 并发 reinit 保护 | 无 | 缺失 | Charles 工具在主进程 asyncio 事件循环执行，无进程隔离 |
| 7.12.4 | plugin-sandbox-bootstrap | `plugin-sandbox-bootstrap.ts` L1-736 子进程入口 + RPC 派发（initialize/executeTool/executeCommand/resolveRuleContent/buildMessages/invokeHook）+ pluginId → PluginModule 映射 | 无 | 缺失 | Charles 无子进程入口 |
| 7.12.5 | plugin-module-import | `plugin-module-import.ts` L1-648 `importPluginModule` + 静态分析 import/require + 依赖预检 + 工作区别名 + Host SDK 注入 + Bun 二进制兼容 + jiti 实例化 | 无 | 缺失 | Charles 无 jiti 等价物 |
| 7.12.6 | plugin-targeting | `plugin-targeting.ts` L8-32 `matchesPluginManifestTargeting` — providerIds + modelIds 双重过滤 + 空数组=匹配所有 + 保守不匹配策略 | 无 | 缺失 | Charles 无插件层级 targeting（providers 层级 targeting 在 P7.4 对比） |
| 7.12.7 | plugin-load-report | `plugin-load-report.ts` L1-20 `PluginInitializationFailure` + `PluginInitializationWarning` + `PluginLoadDiagnostics` 类型 | 无 | 缺失 | Charles 无加载诊断 |
| 7.12.8 | Marketplace 远程 catalog | `marketplace-helpers.ts` L111-123 `fetchMarketplaceCatalog` — 拉取 `https://cline.github.io/marketplace/catalog.json` + `sanitizeEntry` 校验 + `MarketplaceCatalog.create` | 无 | 缺失 | Charles 无远程市场 |
| 7.12.9 | Marketplace 安装 | `installMarketplaceEntry.ts` L5-20 + `marketplace-helpers.ts::installMarketplaceEntryFromCatalog` — 三分支（mcp/skill/plugin）+ 后置动作（mcp reconcile / skill+plugin invalidate）+ 密钥脱敏 + 120s 超时 + 12000 字符截断 + Windows shell 兼容 | 无 | 缺失 | Charles 无安装链路 |
| 7.12.10 | Marketplace 卸载 | `uninstallMarketplaceEntry.ts` L5-17 + `marketplace-helpers.ts::uninstallMarketplaceEntryFromCatalog` + `uninstallLocalMarketplaceInstalledEntry` — 三分支 + install/uninstall 不对称（mcp 卸载不 invalidate）+ remote skill 不可卸载保护 | 无 | 缺失 | Charles 无卸载链路 |
| 7.12.11 | Marketplace 列表 | `getMarketplaceCatalog.ts` L1-8 + `listMarketplaceInstalledEntries.ts` L1-10 + `listMarketplaceLocalInstalledEntries.ts` L1-11 + `marketplace-helpers.ts` 三态检测（isMcpInstalled/isSkillInstalled/isOfficialPluginInstalled）+ 本地聚合（mcp+skills+plugins）+ normalizeMatchValue 宽松匹配 | 无 | 缺失 | Charles 各模块独立提供列表，无统一聚合视图 |
| 7.12.12 | Marketplace 启用/禁用 | `toggleMarketplaceLocalInstalledEntry.ts` L1-13 + `marketplace-helpers.ts::toggleLocalMarketplaceInstalledEntry` — mcp toggleServerDisabledRPC / skill toggleSkill / plugin disablePluginMcpServersInSettings + setDisabledPlugin + syncPluginMcpServersToSettings | 无 | 缺失 | Charles 通过配置文件控制启用/禁用（如 `mcp_servers.yaml`） |
| 7.12.13 | Marketplace 安全设施 | `marketplace-helpers.ts` L51-58 三层密钥脱敏正则 + L51 `INSTALL_COMMAND_TIMEOUT_MS = 120_000` + L52 `MAX_OUTPUT_CHARS = 12_000` + `parseJsonErrorMessage` JSON 错误提取 + `formatCommand` 命令格式化 | 无 | 缺失 | Charles 无远程市场，无安全设施需求 |
| 7.12.14 | 官方插件识别 | `marketplace-helpers.ts::isOfficialPluginInstalled` — sha256 前 12 位 + `~/.cline/plugins/_installed/official/<sanitized>-<hash>` 路径校验 | 无 | 缺失 | Charles 无官方插件仓库概念 |
| 7.12.15 | 预留字段 | N/A（Cline 不需要预留，已实现） | `agent/types.py` L569-571 + `agent/runtime.py` L307-309 — `plugins: list[Any]` 仅存储不处理，注释明确"Stage 8 已确认 Y 阶段不实施" | 额外增强 | Charles 的预留字段是"未来扩展点"标记，与 Cline 的"已实现"形成对比 |

---

## 三、重点差距详解

### 3.1 Plugin 内核链路完全缺失

**严重度**：P3（Charles 量化场景下无第三方插件需求，主动选择不实施）

**Cline 实现**（`plugin-config-loader.ts` + `plugin-loader.ts` + `plugin-module-import.ts` + `plugin-sandbox.ts` + `plugin-sandbox-bootstrap.ts` + `plugin-targeting.ts` + `plugin-load-report.ts`，合计 2535 行）：

Cline 实现七层插件链路：

1. **路径发现**（`plugin-config-loader.ts` L1-285）：
   - `resolvePluginConfigSearchPaths(workspacePath)`：标准搜索路径（`.cline/plugins`、`~/.cline/plugins`、`<workspace>/.cline/plugins` 等）
   - `discoverPluginModulePaths(directoryPath)`：扫描发现插件
   - `resolveConfiguredPluginModulePaths(pluginPaths, cwd)`：用户显式配置路径
   - `mergePluginPaths` + `dedupePaths`（按 `resolve()` 规范化去重）+ `filterDisabledPluginPaths`（过滤全局 settings 中已禁用插件）
   - `resolveAndLoadAgentPlugins(options)`：统一加载入口，`mode: "sandbox" | "in_process"` 分发

2. **manifest 校验 + 加载**（`plugin-loader.ts` L1-200）：
   - `validatePluginExport`：断言导出是对象，`name` 是非空字符串，存在 `manifest` 字段
   - `validatePluginManifest`：`capabilities` 必须是非空字符串数组，可选 `providerIds`/`modelIds` 必须是字符串数组
   - `loadAgentPluginFromPath`：动态加载 + setup 上下文注入（session/client/user/workspaceInfo/automation/logger/telemetry）
   - `loadAgentPluginsFromPathsWithDiagnostics`：顺序加载 + 单个失败不影响其他 + 按 `plugin.name` 去重覆盖 + targeting 过滤 + order 保留

3. **jiti 动态加载**（`plugin-module-import.ts` L1-648）：
   - 静态分析 import/require 语句（4 种正则模式）
   - 依赖预检（`assertPluginDependenciesInstalled`）：非 TS 文件强制预检 bare specifier
   - 工作区别名（`WORKSPACE_ALIASES`）：dev 模式 `@cline/sdk` → src 源码路径
   - Host-runtime SDK specifier 注入（`HOST_PROVIDED_SDK_SPECIFIERS`）
   - `isPackageBasedPlugin`：向上查找最多 4 层找 `cline` 字段的 package.json
   - jiti 实例化：`interopDefault: false`、`tryNative: false`、`transformModules` 仅对 TS alias target 启用 babel transform
   - Bun 编译二进制兼容：手动定位 `jiti/dist/babel.cjs` 并注入 transform

4. **沙箱隔离**（`plugin-sandbox.ts` L1-614 + `plugin-sandbox-bootstrap.ts` L1-736）：
   - `loadSandboxedPlugins`：创建 `SubprocessSandbox` + bootstrap 解析（多路径回退 + dev 模式内联 jiti 脚本）
   - 超时配置：`importTimeoutMs` 默认 4000ms（env `CLINE_PLUGIN_IMPORT_TIMEOUT_MS` 可覆盖）、`hookTimeoutMs` 默认 3000ms、`contributionTimeoutMs` 默认 60000ms
   - RPC 初始化 + 失败 best-effort shutdown + 并发再初始化保护（`reinitPromise ??=` 单例化）
   - 贡献注册：`registerTools`/`registerCommands`/`registerRules`/`registerMessageBuilders`/`registerSimpleContributions`（providers/automationEventTypes/mcpServers）
   - Hook 桥接：`createSandboxRuntimeHooks` 每个 hook 名生成 `makeHookHandler`，统一通过 `invokeHook` RPC
   - 子进程入口（`plugin-sandbox-bootstrap.ts`）：在隔离 Node 子进程运行，接收 RPC（initialize/executeTool/executeCommand/resolveRuleContent/buildMessages/invokeHook），维护 `pluginId → PluginModule` 映射

5. **targeting 过滤**（`plugin-targeting.ts` L8-32）：
   - `matchesPluginManifestTargeting(manifest, targeting)` 按 `providerIds` + `modelIds` 双重过滤
   - **空数组 = 匹配所有**（`providerIds?.length` 为 0 时不限制）
   - **未定义 manifest = 匹配所有**
   - **providerIds 非空但 targeting.providerId 缺失 = 不匹配**（保守策略）
   - 同一插件可同时按 providerId 和 modelId 双重过滤，两者必须都通过

6. **加载诊断**（`plugin-load-report.ts` L1-20）：
   - `PluginInitializationFailure`：pluginPath + pluginName + phase（load/setup）+ message + stack
   - `PluginInitializationWarning`：type（duplicate_plugin_override）+ pluginPath + pluginName + overriddenPluginPath + message
   - `PluginLoadDiagnostics`：failures + warnings 数组

**Charles 实现**：

Charles 仅有 2 行预留代码：

```python
# agent/types.py L569-571
# plugins: 插件列表预留字段，当前不实现加载逻辑（Stage 8 已确认 Y 阶段不实施）
# AgentRuntime.__init__ 中仅存储不处理，未来扩展时使用
plugins: list[Any] = field(default_factory=list)

# agent/runtime.py L307-309
# plugins: 插件列表预留字段，当前不实现加载逻辑（Stage 8 已确认 Y 阶段不实施）
# 仅存储不处理，未来扩展时使用
self._plugins: list[Any] = list(config.plugins)
```

**对比**：
- Cline 实现完整七层链路（路径发现 → manifest 校验 → jiti 动态加载 → 沙箱隔离 → 贡献注册 → Hook 桥接 → targeting 过滤）+ 加载诊断
- Charles 仅"存储不处理"，无任何加载逻辑
- Charles 的"主动选择不实施"决策依据：量化场景无第三方插件需求 + Python 生态无 jiti 等价物 + SubprocessSandbox 在 Python 下成本高 + 安全考量（金融场景对第三方可执行代码天然敏感）

### 3.2 Marketplace 远程市场完全缺失

**严重度**：P3（Charles 量化场景下无社区市场接入需求）

**Cline 实现**（`marketplace-helpers.ts` L1-592 + 6 个 RPC 入口文件共 89 行 = 681 行）：

Cline 实现完整远程市场链路：

1. **远程 catalog 拉取**（`marketplace-helpers.ts` L111-123 `fetchMarketplaceCatalog`）：
   - HTTP `Accept: application/json` 拉取 `https://cline.github.io/marketplace/catalog.json`
   - HTTP 错误抛 `Failed to fetch marketplace catalog: <status> <statusText>`
   - 逐条 `sanitizeEntry` 校验：id（非空 trim）+ type（必须 ∈ mcp/skill/plugin）+ name（默认取 id）+ 可选字段（tagline/description/tags/author/sourceUrl/homepageUrl）+ install 子对象（args/env/command/notes）

2. **三分支安装**（`installMarketplaceEntry.ts` L5-20 + `marketplace-helpers.ts::installMarketplaceEntryFromCatalog`）：
   - mcp → `installMcpMarketplaceEntry`：`parseMcpInstallArgs(args)` + `installMcpServer(parsed)`
   - plugin → `installPluginMarketplaceEntry`：`installPlugin({ source })` + 同步 MCP servers（`mcpSyncFailures` 收集为 warnings）
   - skill → `installSkillMarketplaceEntry`：spawn `npx -y skills@latest add ... -g -a cline -y`
   - 后置动作：mcp → `reconcileMcpServersFromSettingsRPC`；skill/plugin → `invalidateUserInstructionService`

3. **三分支卸载**（`uninstallMarketplaceEntry.ts` L5-17 + `marketplace-helpers.ts::uninstallMarketplaceEntryFromCatalog` + `uninstallLocalMarketplaceInstalledEntry`）：
   - **install/uninstall 不对称**：mcp 卸载**不**调用 `invalidateUserInstructionService`（由 mcpHub 自己 reconcile）
   - mcp → `controller.mcpHub?.deleteServerRPC(name)`
   - skill → `deleteSkillFile` + `invalidateUserInstructionService`；`entry.path?.startsWith("remote:")` → 抛错「Remote-managed skills cannot be uninstalled from Customize.」
   - plugin → `uninstallPlugin({ name, path, workspaceRoot })` + `invalidateUserInstructionService`

4. **三态已安装检测**（`listMarketplaceInstalledEntries.ts` + `marketplace-helpers.ts`）：
   - `isMcpInstalled`：mcpHub 中 server name 标准化后匹配 entry 的 args[0]/id/name
   - `isSkillInstalled`：委托 `isMarketplaceSkillInstalled`（@cline/core）
   - `isOfficialPluginInstalled`：计算 `official:https://github.com/cline/plugins.git#plugins/<source>` 的 sha256 前 12 位 + 检查 `~/.cline/plugins/_installed/official/<sanitized>-<hash>` 路径存在
   - `normalizeMatchValue`：小写 + 非 alnum 转 `-` + 去首尾 `-`，用于宽松匹配

5. **本地已安装聚合**（`listMarketplaceLocalInstalledEntries.ts` + `marketplace-helpers.ts::listLocalMarketplaceInstalledEntries`）：
   - MCP servers：`controller.mcpHub?.getServers()` → `{ id, type: "mcp", name, description: status, enabled: !disabled }`
   - Skills：`refreshSkills(controller)` 返回 `globalSkills` + `localSkills`，分别映射 source 为 `remote`/`global`/`workspace`
   - Plugins：`listPluginLocalEntries()`：遍历 `resolvePluginConfigSearchPaths(workspacePath)` + 每个 root 下 `discoverPluginModulePaths(root)` + `getPluginDisplayName`（向上查找 package.json 取 `name`，回退到 basename）+ source（`isGlobalClinePath` 判断）+ enabled（`!disabledPlugins.has(pluginPath)`）

6. **启用/禁用切换**（`toggleMarketplaceLocalInstalledEntry.ts` + `marketplace-helpers.ts::toggleLocalMarketplaceInstalledEntry`）：
   - mcp：`toggleServerDisabledRPC(name, !enabled)`
   - skill：`toggleSkill(controller, { skillPath, isGlobal, enabled })`
   - plugin 禁用：`disablePluginMcpServersInSettings({ pluginPaths: [path] })` + `setDisabledPlugin(path, true)`
   - plugin 启用：先 disable 旧 MCP 引用，再 `syncPluginMcpServersToSettings` 重新同步，失败抛错，最后 `setDisabledPlugin(path, false)`

7. **安全设施**（`marketplace-helpers.ts` L51-58）：
   - **超时**：`INSTALL_COMMAND_TIMEOUT_MS = 120_000`（120 秒），超时发 SIGTERM，125 秒后 SIGKILL 兜底
   - **输出截断**：`MAX_OUTPUT_CHARS = 12_000`，stdout/stderr 各保留最后 12000 字符
   - **密钥脱敏**（`redactOutput`）：`SECRET_KEY_VALUE_PATTERN` + `SECRET_BEARER_VALUE_PATTERN` + `SECRET_AUTHORIZATION_VALUE_PATTERN` 三组正则，覆盖 `api_key/access_token/refresh_token/authorization/secret/password/credential` 七类字段，分别处理 `key: value`、`Bearer xxx`、`Authorization: xxx` 三种形态，替换为 `[redacted]`
   - **JSON 错误提取**（`parseJsonErrorMessage`）：尝试解析 stdout/stderr 为 JSON，递归查找 `message`/`error`/`details`/`reason` 等字段
   - **Windows 兼容**：`shell: platform() === "win32"` 在 Windows 下强制走 shell
   - **命令格式化**（`formatCommand`）：拼接 `command args`，对含特殊字符的部分用 `JSON.stringify` 引号包裹

**Charles 实现**：

Charles 完全无 marketplace 实现。

**对比**：
- Cline 实现完整远程市场链路（catalog 拉取 → 三分支安装/卸载 → 三态检测 → 本地聚合 → 启用/禁用切换）+ 安全设施（密钥脱敏 + 超时 + 输出截断 + Windows 兼容）
- Charles 完全无实现
- Charles 的"主动选择不实施"决策依据：量化策略以本地代码 + 自有 skills 为主 + 无社区分发需求 + 远程市场拉取引入供应链风险（npm 包劫持、catalog 篡改）+ 沙箱逃逸在金融场景下损失不可逆

### 3.3 plugin-targeting 缺失分析

**严重度**：P3（依赖 plugin 内核，独立无意义）

**Cline 实现**（`plugin-targeting.ts` L8-32）：

```typescript
export function matchesPluginManifestTargeting(
    manifest: PluginManifest | undefined,
    targeting: PluginTargeting | undefined,
): boolean {
    if (!manifest) {
        return true;
    }
    if (manifest.providerIds?.length) {
        if (
            !targeting?.providerId ||
            !manifest.providerIds.includes(targeting.providerId)
        ) {
            return false;
        }
    }
    if (manifest.modelIds?.length) {
        if (!targeting?.modelId || !manifest.modelIds.includes(targeting.modelId)) {
            return false;
        }
    }
    return true;
}
```

关键语义：
- **空数组 = 匹配所有**（`providerIds?.length` 为 0 时不限制）
- **未定义 manifest = 匹配所有**
- **providerIds 非空但 targeting.providerId 缺失 = 不匹配**（保守策略，避免插件跑到未声明的 provider 上）
- 同一插件可同时按 providerId 和 modelId 双重过滤，两者必须都通过

**Charles 实现**：

Charles 无插件层级 targeting。但 Charles 在 providers 层级有 targeting：
- `agent/providers/`（P7.4 对比）已有多 provider 支持（OpenAI/Qwen 工厂）
- `agent/types.py` L562-564 `provider_id` + `model_id` + `tool_routing_rules` 字段
- `agent/tools/routing.py` 实现工具按 provider/model 路由

**对比**：
- Cline targeting 是"插件激活范围限制"（插件声明 `providerIds`/`modelIds`，仅匹配的 provider/model 下激活）
- Charles 的 tool routing 是"工具路由规则"（按 provider/model 过滤工具列表），语义不同
- Charles 的 providers 层级 targeting 已覆盖 80% 的"按 provider/model 限制"需求，无需插件层级 targeting
- 量化场景下 provider 集中（OpenAI/Qwen），且无第三方插件，targeting 机制无适用对象

### 3.4 plugin-sandbox 进程隔离缺失分析

**严重度**：P3（仅在有第三方插件时才需要沙箱）

**Cline 实现**（`plugin-sandbox.ts` L1-614 + `plugin-sandbox-bootstrap.ts` L1-736，合计 1350 行）：

Cline 通过 `SubprocessSandbox` 在隔离 Node 子进程中加载插件：

1. **沙箱创建**：`loadSandboxedPlugins(options)` 创建 `SubprocessSandbox({ name: "plugin-sandbox", bootstrapFile | bootstrapScript, onEvent })`
2. **bootstrap 解析**：多路径回退（`plugin-sandbox-bootstrap.js` → `extensions/plugin-sandbox-bootstrap.js` → `agents/plugin-sandbox-bootstrap.js` → wrapper 路径 → execPath 路径），dev 模式回退到内联 jiti 脚本
3. **超时配置**（`withTimeoutFallback`）：
   - `importTimeoutMs`：默认 4000ms，env `CLINE_PLUGIN_IMPORT_TIMEOUT_MS` 可覆盖（Number 严格解析，拒绝 `4000ms` 这类带尾随字符的值）
   - `hookTimeoutMs`：默认 3000ms
   - `contributionTimeoutMs`：默认 60000ms
4. **RPC 初始化**：`sandbox.call("initialize", initArgs, { timeoutMs })`，失败 best-effort `sandbox.shutdown()` 后 rethrow
5. **并发再初始化保护**：`reinitPromise ??=` 单例化，避免多个工具同时失败触发并发 reinit
6. **"Unknown sandbox plugin id:" 错误识别** → 触发 reinit → 重试一次
7. **贡献注册**：每个 descriptor 一次性注册所有贡献
   - `registerTools`：每个 tool 的 `execute` 通过 `sandbox.call("executeTool", { pluginId, contributionId, input, context }, { timeoutMs })`
   - `registerCommands`：类似，调用 `executeCommand`
   - `registerRules`：`hasContentHandler === true` 时通过 `resolveRuleContent` RPC 拉取，否则用静态 `content`
   - `registerMessageBuilders`：`buildMessages` RPC，返回非数组时回退原 messages
   - `registerSimpleContributions`：providers、automationEventTypes、mcpServers（无 RPC，仅注册元数据）
8. **Hook 桥接**（`createSandboxRuntimeHooks`）：每个 hook 名生成 `makeHookHandler`，统一通过 `invokeHook` RPC
9. **子进程入口**（`plugin-sandbox-bootstrap.ts`）：在隔离 Node 子进程运行，仅依赖本地类型镜像，接收 RPC（initialize/executeTool/executeCommand/resolveRuleContent/buildMessages/invokeHook），内部维护 `pluginId → PluginModule` 映射

**Charles 实现**：

Charles 工具直接在主进程 asyncio 事件循环中执行（`agent/runtime.py`），无进程隔离。

**对比**：
- Cline 沙箱实现"插件代码隔离 + RPC 通信 + 超时保护 + 并发 reinit 保护"
- Charles 无第三方插件，无隔离需求
- Python 生态下可用 `multiprocessing.Process` + pickle RPC 实现简化版，但性能/稳定性远不如 Node 子进程，且 Python 插件生态以 entry_points 为主流，子进程沙箱非首选

---

## 四、nanobot 残留审计

### 4.1 检查范围

P7.12 范围内核心文件：
- `agent/types.py` L569-571（`plugins` 预留字段定义，3 行）
- `agent/runtime.py` L307-309（`self._plugins` 存储，3 行）

**注**：`agent/skills/loader.py` L59 / `agent/skills/registry.py` L74/L114 / `agent/skills/skill_tool.py` L26/L70/L127/L164 中出现的 `user-instruction-plugin.ts` 是 Cline 技能系统的配置加载器（skill frontmatter toggle + allowedSkillSet），**不是** plugin/marketplace 系统，归属 P4.x / P5.x 阶段。这些文件中的 nanobot 残留属 P4.20 范围，不在 P7.12 范围内。

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `agent/types.py` L569-571 | 0 处 | 0 处 | 预留字段注释仅对标"Stage 8 / Y 阶段"，无 "nanobot" 字样。`plugins: list[Any] = field(default_factory=list)` 是空列表默认值，无 nanobot 逻辑 |
| `agent/runtime.py` L307-309 | 0 处 | 0 处 | 预留字段注释仅对标"Stage 8 / Y 阶段"，无 "nanobot" 字样。`self._plugins: list[Any] = list(config.plugins)` 是浅拷贝存储，无 nanobot 逻辑 |

**P7.12 范围内 nanobot 残留总计：0 处注释残留 + 0 处实现逻辑残留。**

### 4.3 实现逻辑残留检查

**0 处实现逻辑残留**。验证依据：

1. `agent/types.py` L571 `plugins: list[Any] = field(default_factory=list)` 是 Stage 10.6 (A16) 新增的预留字段，默认空列表，无任何 nanobot 插件加载逻辑
2. `agent/runtime.py` L309 `self._plugins: list[Any] = list(config.plugins)` 是 Stage 10.6 (A16) 新增的存储代码，仅做浅拷贝，无任何 nanobot 插件处理逻辑
3. 两处注释均明确"Stage 8 已确认 Y 阶段不实施"+"仅存储不处理，未来扩展时使用"，是对 Cline plugin 系统的"主动选择不实施"决策记录，非 nanobot 残留
4. Charles 全文无 `import nanobot` / `from nanobot` 等导入语句
5. Charles 全文无 `nanobot.SkillsLoader` / `nanobot.plugin` 等类引用

**结论**：P7.12 范围内 Plugin / Marketplace 模块是 Charles"主动选择不实施"的模块，预留字段无任何 nanobot 残留。所有注释均对标"Stage 8 / Y 阶段"决策记录，而非 "nanobot"。

### 4.4 范围外残留说明

以下文件的 nanobot 残留**超出 P7.12 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/skills/loader.py` L2/L29/L48/L96/L167/L222/L392/L423 | 注释 + 实现残留 | docstring 对标 "nanobot SkillsLoader" + fallback 解析逻辑 | P4.20 |
| `agent/skills/registry.py` L2/L20/L100/L184 | 注释残留 | docstring 对标 "nanobot SkillsLoader" | P4.20 |
| `agent/skills/skill_tool.py` L18 | 注释残留 | docstring "nanobot 的子 agent 隔离执行" | P4.20 |
| `agent/skills/__init__.py` L2/L23 | 注释残留 | docstring 对标 "nanobot SkillsLoader" | P4.20 |
| `agent/server.py` L2/L4/L28 | 注释残留 | docstring 对标 "nanobot routes/chat.py" | P1.x / P2.x |
| `agent/context.py` L275 | 注释残留 | docstring "nanobot 风格的额外段落" | P5.1 |
| `agent/session.py` L2/L22 | 注释残留 | docstring 对标 "nanobot session_key" | P1.x |
| `agent/providers/qwen.py` 7 处 | 注释残留 | docstring 对标 "nanobot openai_compat_provider.py" | P7.4 |
| `agent/tools/exec_tool.py` 多处 | 注释残留 | 对标 nanobot ShellTool / shell.py | P3.x |
| `agent/tools/web_tool.py` 多处 | 注释残留 | 对标 nanobot WebSearchTool | P3.x |
| `agent/tools/file_tools.py` 多处 | 注释残留 | 对标 nanobot FilesystemTool | P3.x |
| `agent/tools/__init__.py` L2 | 注释残留 | 对标 "nanobot agent/tools" | P3.x |

**注**：`agent/skills/` 下虽出现 `user-instruction-plugin.ts` 字样（L59/L74/L114/L26/L70/L127/L164），但这是 **Cline 文件名**（`sdk/packages/core/src/extensions/config/user-instruction-plugin.ts`），是 Cline 技能系统的配置加载器，**不是** nanobot 残留，也**不是** plugin/marketplace 系统引用。该文件名包含 "plugin" 字样易引起误解，实际归属 P4.x / P5.x 阶段（技能系统配置加载）。

---

## 五、修复建议

### 5.1 高优先级：无

**说明**：P7.12 范围内所有子项均为 P3（主动选择不实施），无 P0/P1/P2 项。Charles 在 Stage 8 已明确决策"Y 阶段不实施"，预留字段语义清晰，无修复需求。

### 5.2 中优先级：预留字段语义保持

**问题**：Charles `agent/types.py` L569-571 + `agent/runtime.py` L307-309 的 `plugins` 预留字段当前仅存储不处理。若未来扩展，需明确"plugin"语义——是 Cline 式"第三方可执行代码插件"，还是 Charles 式"内部策略模块"。

**修复建议**：**保持现状**。理由：
1. 当前预留字段语义清晰（注释明确"Stage 8 已确认 Y 阶段不实施"）
2. 若未来扩展，建议重命名为 `extension_modules` 或 `strategy_plugins` 以区分 Cline 式"第三方可执行代码插件"
3. 当前 `list[Any]` 类型保持灵活，未来扩展时再约束

**优先级**：低。当前无需修改。

### 5.3 低优先级：内部策略市场评估

**问题**：Cline marketplace 模式（远程 catalog + 三分支安装/卸载 + 密钥脱敏 + 超时）适合"社区分发"场景。Charles 若未来形成"内部策略市场"需求（如多团队共享策略包），可参考 Cline 的安全设施实现内部版。

**修复建议**：**按需补**。理由：
1. 当前 Charles 量化策略以本地代码迭代为主（`dragon_strategy/`、`sector_rotation/`、`ml_strategy/` 等），无社区分发需求
2. 若未来形成内部策略市场，建议：
   - 用内部 git 仓库替代公网 catalog（`git+ssh://internal-repo/strategies.git`）
   - 用 venv 隔离替代 SubprocessSandbox（Python 生态下 venv + entry_points 是主流）
   - 保留 Cline 的安全设施（密钥脱敏 + 超时 + 输出截断）
3. 最小可用实现约 1000+ 行 Python（路径发现 ~200 行 + importlib 加载 + manifest 校验 ~300 行 + 简化 sandbox ~400 行 + 远程 catalog ~150 行）

**优先级**：低。当前无内部策略市场需求。

### 5.4 不建议补：plugin-sandbox 进程隔离

**问题**：Cline `plugin-sandbox.ts` + `plugin-sandbox-bootstrap.ts` 合计 1350 行，通过 `SubprocessSandbox` 在隔离 Node 子进程中加载插件。Charles 无第三方插件，无隔离需求。

**修复建议**：**不建议补**。理由：
1. Charles 单进程架构，工具在主进程 asyncio 事件循环执行
2. Python 生态下 `multiprocessing.Process` + pickle RPC 性能/稳定性远不如 Node 子进程
3. Python 插件生态以 entry_points 为主流，子进程沙箱非首选
4. 若未来需要隔离，可先用 venv + entry_points 替代，成本远低于 SubprocessSandbox

### 5.5 不建议补：plugin-module-import jiti 动态加载

**问题**：Cline `plugin-module-import.ts` 648 行，基于 jiti 实现 TS/JS 动态加载。Python 生态下无 jiti 1:1 等价物。

**修复建议**：**不建议补**。理由：
1. Python 的 `importlib` + `importlib.util.spec_from_file_location` 可实现类似功能，但无 jiti 的"工作区别名 + Host SDK 注入 + Bun 二进制兼容"等高级特性
2. Charles 量化场景下"扩展"实际是策略模块（强类型 Python 模块），需要回测/实盘一致性验证，不适合"热加载/远程安装"模式
3. 应走"代码提交 → CI 回测 → 灰度部署"的标准研发流程，而非 jiti 式动态加载

### 5.6 不建议补：marketplace 远程 catalog

**问题**：Cline `marketplace-helpers.ts` L111-123 拉取 `https://cline.github.io/marketplace/catalog.json`，Charles 无远程市场。

**修复建议**：**不建议补**。理由：
1. 量化交易系统对"第三方可执行代码"天然敏感
2. 远程市场拉取引入供应链风险（npm 包劫持、catalog 篡改）
3. 沙箱逃逸在金融场景下的损失不可逆
4. Charles 已有替代：`agent/skills/`（本地 SKILL.md 加载）+ `agent/mcp/`（MCP server 配置）+ `agent/tools/`（工具基类）+ `agent_config/strategies.yaml`（策略注册表）

### 5.7 不建议补：plugin-targeting

**问题**：Cline `plugin-targeting.ts` L8-32 实现 `matchesPluginManifestTargeting` 按 providerIds + modelIds 双重过滤插件激活范围。Charles 无插件层级 targeting。

**修复建议**：**不建议补**。理由：
1. Charles 已有 providers 层级 targeting（`agent/providers/` + `agent/tools/routing.py`），已覆盖 80% 的"按 provider/model 限制"需求
2. 量化场景下 provider 集中（OpenAI/Qwen），且无第三方插件，targeting 机制无适用对象
3. plugin-targeting 依赖 plugin 内核（Y1/Y2），独立无意义

---

## 六、附录

### 6.1 Cline Plugin / Marketplace 模块文件清单

| 文件 | 行数 | 关键导出 |
|------|------|---------|
| `extensions/plugin/plugin-config-loader.ts` | 285 | `resolvePluginConfigSearchPaths`、`discoverPluginModulePaths`、`resolveAgentPluginPaths`、`resolveAndLoadAgentPlugins`、`collectPluginSkillRootCandidates` |
| `extensions/plugin/plugin-loader.ts` | 200 | `loadAgentPluginFromPath`、`loadAgentPluginsFromPaths`、`loadAgentPluginsFromPathsWithDiagnostics`、`validatePluginExport`、`validatePluginManifest` |
| `extensions/plugin/plugin-module-import.ts` | 648 | `importPluginModule`、`assertPluginDependenciesInstalled`、`collectPluginImportAliases` |
| `extensions/plugin/plugin-sandbox.ts` | 614 | `loadSandboxedPlugins`、`SandboxedPluginSetupContext`、`PluginSandboxOptions` |
| `extensions/plugin/plugin-sandbox-bootstrap.ts` | 736 | 子进程入口（无导出，由 `SubprocessSandbox` spawn） |
| `extensions/plugin/plugin-targeting.ts` | 32 | `PluginTargeting`、`matchesPluginManifestTargeting` |
| `extensions/plugin/plugin-load-report.ts` | 20 | `PluginInitializationFailure`、`PluginInitializationWarning`、`PluginLoadDiagnostics` |
| `marketplace/getMarketplaceCatalog.ts` | 8 | `getMarketplaceCatalog` |
| `marketplace/installMarketplaceEntry.ts` | 20 | `installMarketplaceEntry` |
| `marketplace/uninstallMarketplaceEntry.ts` | 17 | `uninstallMarketplaceEntry` |
| `marketplace/marketplace-helpers.ts` | 592 | `fetchMarketplaceCatalog`、`installMarketplaceEntryFromCatalog`、`uninstallMarketplaceEntryFromCatalog`、`listInstalledMarketplaceEntries`、`listLocalMarketplaceInstalledEntries`、`toggleLocalMarketplaceInstalledEntry`、`uninstallLocalMarketplaceInstalledEntry`、`redactOutput`、`runCommand` |
| `marketplace/listMarketplaceInstalledEntries.ts` | 10 | `listMarketplaceInstalledEntries` |
| `marketplace/listMarketplaceLocalInstalledEntries.ts` | 11 | `listMarketplaceLocalInstalledEntries` |
| `marketplace/toggleMarketplaceLocalInstalledEntry.ts` | 13 | `toggleMarketplaceLocalInstalledEntry` |
| `marketplace/uninstallMarketplaceLocalInstalledEntry.ts` | 10 | `uninstallMarketplaceLocalInstalledEntry` |
| **合计** | **3216** | 15 个文件 |

### 6.2 Charles 预留字段清单

| 文件 | 行号 | 代码 | 说明 |
|------|------|------|------|
| `agent/types.py` | L569-571 | `# plugins: 插件列表预留字段，当前不实现加载逻辑（Stage 8 已确认 Y 阶段不实施）`<br/>`# AgentRuntime.__init__ 中仅存储不处理，未来扩展时使用`<br/>`plugins: list[Any] = field(default_factory=list)` | 预留字段定义 |
| `agent/runtime.py` | L307-309 | `# plugins: 插件列表预留字段，当前不实现加载逻辑（Stage 8 已确认 Y 阶段不实施）`<br/>`# 仅存储不处理，未来扩展时使用`<br/>`self._plugins: list[Any] = list(config.plugins)` | 预留字段存储 |
| **合计** | **6 行** | 2 处预留 | 0 行实现逻辑 |

### 6.3 量化场景适用性评估

#### 6.3.1 评估结论

**Plugin / Marketplace 系统对当前量化场景「不需要」，建议 P3 暂缓实现。**

#### 6.3.2 理由

1. **生态差异**：Cline 的 plugin/marketplace 面向"开发者社区贡献扩展"场景（GitHub 公开 catalog、第三方工具/规则/插件分发），目标用户是泛开发任务人群。Charles 是单一团队的 A 股量化交易研究/执行平台，扩展以**内部代码迭代**为主，不存在社区分发需求。

2. **安全考量**：量化交易系统对"第三方可执行代码"天然敏感。Cline 的 sandbox（Node 子进程）+ 远程市场（公开 catalog.json）模式在量化场景下意味着：
   - 第三方插件可能触碰实盘下单链路（`live_trading/`、`miniqmt_trader_v2.py`）
   - 远程市场拉取引入供应链风险（npm 包劫持、catalog 篡改）
   - 沙箱逃逸在金融场景下的损失不可逆

   即便实现，也应以"内部 git 仓库 + code review + venv 隔离"替代公网市场。

3. **已有替代**：
   - **扩展能力**：已有 `agent/skills/`（P4.x 对比，本地 SKILL.md 加载）+ `agent/mcp/`（P7.8 对比，MCP server 注册）+ `agent/tools/`（P3.x 对比，工具基类）
   - **多 provider 支持**：已有 `agent/providers/`（P7.4 对比，OpenAI/Qwen 工厂）
   - **配置禁用**：`agent_config/` 下 yaml 配置即可控制启用/禁用，无需复杂 plugin targeting
   - **策略注册表**：`agent_config/strategies.yaml` + `lib/strategy_registry.py` 提供策略注册机制

4. **实现成本**：Cline 该模块合计 3216 行 TypeScript，核心难点（jiti 动态加载、SubprocessSandbox RPC、bootstrap 文件解析、workspace alias 解析）在 Python 下无 1:1 等价物。最小可用实现至少需要：
   - 路径发现（~200 行 Python）
   - importlib 加载 + manifest 校验（~300 行）
   - 简化 sandbox（multiprocessing + pickle RPC，~400 行，且性能/稳定性远不如 Node 子进程）
   - 远程 catalog（~150 行，含密钥脱敏）
   
   合计 ~1000+ 行 Python，且持续维护成本高（Python 版本演进、依赖冲突、venv 管理）。

5. **场景不匹配**：量化系统的"扩展"实际是**策略**（`dragon_strategy/`、`sector_rotation/`、`ml_strategy/` 等），这些是强类型 Python 模块，需要回测/实盘一致性验证，不适合"热加载/远程安装"模式，而应走"代码提交 → CI 回测 → 灰度部署"的标准研发流程。

#### 6.3.3 何时需要重新评估

仅当出现以下场景之一时建议重新评估：

| 触发场景 | 推荐最小实现 |
|---------|------------|
| 非核心团队（如策略研究员）需上传策略包而不污染主仓库 | 仅路径发现 + manifest 校验，跳过 sandbox（用 venv 隔离） |
| 多用户共享部署需按用户启用扩展 | 仅 targeting + 配置文件禁用，跳过路径发现/加载/sandbox |
| 形成内部"策略插件市场"需求 | 路径发现 + 加载 + marketplace 内部版（用内部 git 替代公网 catalog） |
| 接入第三方行情/资讯 API 需隔离 | 仅简化版 sandbox（subprocess + stdin/stdout JSON-RPC） |

#### 6.3.4 风险提示

- 当前完全无 plugin 系统意味着**任何扩展都必须改主仓库代码**，对快速实验不友好。建议作为补偿：
  1. 完善 `agent/skills/` 的 SKILL.md 加载（已有）
  2. 完善 `agent/mcp/` 的 MCP server 配置（已有 `agent_config/mcp_servers.yaml`）
  3. 在 `agent_config/strategies.yaml` 中提供策略注册表机制（已有 `lib/strategy_registry.py`）

  这三条已在各自 Phase 中对比过，能够覆盖 80% 的"扩展"需求，且无需引入 plugin/marketplace 的复杂度。

### 6.4 一致性统计

| 子项 | 一致性 | Cline 行数 | Charles 实现 |
|------|--------|-----------|-------------|
| 7.12.1 Plugin 系统总入口 | 缺失 | 285 行（plugin-config-loader） | 2 行预留 |
| 7.12.2 plugin-loader | 缺失 | 200 行 | 0 行 |
| 7.12.3 plugin-sandbox | 缺失 | 614 行 | 0 行 |
| 7.12.4 plugin-sandbox-bootstrap | 缺失 | 736 行 | 0 行 |
| 7.12.5 plugin-module-import | 缺失 | 648 行 | 0 行 |
| 7.12.6 plugin-targeting | 缺失 | 32 行 | 0 行 |
| 7.12.7 plugin-load-report | 缺失 | 20 行 | 0 行 |
| 7.12.8 Marketplace 远程 catalog | 缺失 | 13 行（fetchMarketplaceCatalog） | 0 行 |
| 7.12.9 Marketplace 安装 | 缺失 | 20 + ~320 行（installEntry + helpers 相关） | 0 行 |
| 7.12.10 Marketplace 卸载 | 缺失 | 17 + ~63 行（uninstallEntry + helpers 相关） | 0 行 |
| 7.12.11 Marketplace 列表 | 缺失 | 8 + 10 + 11 + ~112 行（catalog + listInstalled + listLocal + helpers 相关） | 0 行 |
| 7.12.12 Marketplace 启用/禁用 | 缺失 | 13 + ~30 行（toggleEntry + helpers 相关） | 0 行 |
| 7.12.13 Marketplace 安全设施 | 缺失 | ~80 行（redactOutput + runCommand + 超时 + 截断） | 0 行 |
| 7.12.14 官方插件识别 | 缺失 | ~30 行（isOfficialPluginInstalled） | 0 行 |
| 7.12.15 预留字段 | 额外增强 | N/A | 6 行（types.py + runtime.py） |
| **合计** | **0/14 实现项** | **3216 行** | **6 行预留 + 0 行实现** |

**对齐度**：0%（按实现项计数）；若按代码量加权，约 0.19%（6/3216）。

**P0/P1/P2 数量**：0 项
**P3 数量**：14 项（全部主动选择不实施）

### 6.5 引用文件清单

**Cline 文件**（15 个，合计 3216 行）：
- `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-config-loader.ts`（285 行）
- `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-loader.ts`（200 行）
- `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-module-import.ts`（648 行）
- `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-sandbox.ts`（614 行）
- `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-sandbox-bootstrap.ts`（736 行）
- `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-targeting.ts`（32 行）
- `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-load-report.ts`（20 行）
- `third_party/cline/apps/vscode/src/core/controller/marketplace/getMarketplaceCatalog.ts`（8 行）
- `third_party/cline/apps/vscode/src/core/controller/marketplace/installMarketplaceEntry.ts`（20 行）
- `third_party/cline/apps/vscode/src/core/controller/marketplace/uninstallMarketplaceEntry.ts`（17 行）
- `third_party/cline/apps/vscode/src/core/controller/marketplace/marketplace-helpers.ts`（592 行）
- `third_party/cline/apps/vscode/src/core/controller/marketplace/listMarketplaceInstalledEntries.ts`（10 行）
- `third_party/cline/apps/vscode/src/core/controller/marketplace/listMarketplaceLocalInstalledEntries.ts`（11 行）
- `third_party/cline/apps/vscode/src/core/controller/marketplace/toggleMarketplaceLocalInstalledEntry.ts`（13 行）
- `third_party/cline/apps/vscode/src/core/controller/marketplace/uninstallMarketplaceLocalInstalledEntry.ts`（10 行）

**Charles 文件**（2 个，合计 6 行预留代码）：
- `agent/types.py` L569-571（3 行，`plugins` 预留字段定义）
- `agent/runtime.py` L307-309（3 行，`self._plugins` 存储代码）
