# Phase Y: Plugin / Marketplace 系统 对比报告

> 对标源码：
> - `sdk/packages/core/src/extensions/plugin/`（plugin-config-loader.ts、plugin-loader.ts、plugin-sandbox.ts、plugin-targeting.ts、plugin-module-import.ts、plugin-load-report.ts、plugin-sandbox-bootstrap.ts）
> - `apps/vscode/src/core/controller/marketplace/`（installMarketplaceEntry.ts、uninstallMarketplaceEntry.ts、getMarketplaceCatalog.ts、marketplace-helpers.ts、listMarketplaceInstalledEntries.ts、listMarketplaceLocalInstalledEntries.ts、toggleMarketplaceLocalInstalledEntry.ts、uninstallMarketplaceLocalInstalledEntry.ts）
>
> 当前实现：无（无插件系统，无 marketplace）
> 对比维度：Y1-Y7

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 0 项 |
| 弱对齐 | 0 项 |
| 缺失 | 7 项 |
| 额外增强 | 0 项 |
| **对齐度** | **0%** |

说明：本阶段为 Cline 提供的「第三方插件扩展 + 远程市场目录」能力，本仓库无对应实现，因此所有子项均为「缺失」。但其中 Y1-Y4（plugin 内核）属于「主动选择不实现」，Y5-Y7（marketplace）属于「场景不需要」，详见第 7 节量化场景适用性评估。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| Y1 | `plugin-config-loader` | `sdk/packages/core/src/extensions/plugin/plugin-config-loader.ts` | 无 | 缺失 |
| Y2 | `plugin-loader` | `sdk/packages/core/src/extensions/plugin/plugin-loader.ts` + `plugin-module-import.ts` + `plugin-load-report.ts` | 无 | 缺失 |
| Y3 | `plugin-sandbox` | `sdk/packages/core/src/extensions/plugin/plugin-sandbox.ts` + `plugin-sandbox-bootstrap.ts` | 无 | 缺失 |
| Y4 | `plugin-targeting` | `sdk/packages/core/src/extensions/plugin/plugin-targeting.ts` | 无 | 缺失 |
| Y5 | marketplace 安装 | `apps/vscode/src/core/controller/marketplace/installMarketplaceEntry.ts` + `marketplace-helpers.ts::installMarketplaceEntryFromCatalog` | 无 | 缺失 |
| Y6 | marketplace 卸载 | `apps/vscode/src/core/controller/marketplace/uninstallMarketplaceEntry.ts` + `marketplace-helpers.ts::uninstallMarketplaceEntryFromCatalog` + `uninstallLocalMarketplaceInstalledEntry` | 无 | 缺失 |
| Y7 | marketplace 列表 | `apps/vscode/src/core/controller/marketplace/getMarketplaceCatalog.ts` + `marketplace-helpers.ts::fetchMarketplaceCatalog` + `listInstalledMarketplaceEntries` + `listLocalMarketplaceInstalledEntries` | 无 | 缺失 |

---

## 3. 关键差距详细分析

### 差距 #Y1：plugin-config-loader 缺失

**严重度**：P3（量化场景无插件需求）

**Cline 实现**（`plugin-config-loader.ts`，约 313 行）：

1. **路径解析三层来源**：
   - `resolveDiscoveredPluginPaths(workspacePath)`：从 `resolvePluginConfigSearchPaths()` 返回的标准搜索路径（`.cline/plugins`、`~/.cline/plugins`、`<workspace>/.cline/plugins` 等）扫描发现插件
   - `resolveConfiguredPluginModulePaths(pluginPaths, cwd)`：用户显式在配置中声明的插件路径
   - `mergePluginPaths(...)`：合并 + `dedupePaths`（按 `resolve()` 规范化去重）+ `filterDisabledPluginPaths`（过滤全局 settings 中已禁用的插件）

2. **package.json 声明识别**：
   - `readDeclaredPluginEntryPaths(packageRoot)`：读取 `package.json` 的 `cline.plugins` 字段，支持字符串数组或 `{ paths: string[] }` 对象数组
   - `packageDeclaresPluginEntry(packageRoot, entryPath)`：判断某个 entry 是否被某个 package 声明（用于「该 entry 是否属于该 package」语义）
   - `isInstalledPackageDirectory(path, entryPath)`：识别 `package/` 子目录布局（marketplace 安装产物）

3. **Skill 目录收集**：
   - `collectPluginSkillRootCandidates(entryPath)`：从 entry 向上爬，找到第一个声明该 entry 的 `package.json` 边界，停在 monorepo 根之前（避免误暴露无关 root skills）
   - `resolvePluginSkillDirectoriesFromPaths(pluginPaths)`：在每个候选 root 下找 `skills/` 目录
   - 提供了 best-effort 版本（`resolveAgentPluginPathsBestEffort`）用于 skill 解析，单个坏路径不影响其他

4. **统一加载入口** `resolveAndLoadAgentPlugins(options)`：
   - 选项：`mode: "sandbox" | "in_process"`、`exportName`、各种 timeout、`workspaceInfo`、`session`、`client`、`user`、`automation`、`logger`、`telemetry`
   - 路径为空时短路返回空结果
   - `in_process` 模式调用 `loadAgentPluginsFromPathsWithDiagnostics`
   - 默认（sandbox）模式调用 `loadSandboxedPlugins`

**我的实现**：无。仅有 `agent/skills/loader.py` 加载本地 SKILL.md（已在 Phase I 对比），无插件路径解析逻辑。

**影响**：
- 无法加载第三方插件扩展（工具、命令、规则、messageBuilder、provider、automationEvent、mcpServer）
- 无标准搜索路径约定（`.cline/plugins` 等）
- 无 package.json 声明识别能力

**修复建议**：暂不实现。若未来需要，建议先实现「路径发现 + 禁用过滤」两步，sandbox/in_process 加载可后置。

**优先级**：P3

---

### 差距 #Y2：plugin-loader 缺失

**严重度**：P3（依赖 Y1，无 Y1 则 Y2 无意义）

**Cline 实现**：

1. **`plugin-loader.ts`**（约 214 行）：
   - `validatePluginExport(plugin, absolutePath)`：断言导出是对象，`name` 是非空字符串，存在 `manifest` 字段
   - `validatePluginManifest(plugin, absolutePath)`：
     - `manifest.capabilities` 必须是非空字符串数组
     - 可选 `providerIds`、`modelIds` 必须是字符串数组
   - `loadAgentPluginFromPath(pluginPath, options)`：
     - 调用 `importPluginModule(absolutePath, { useCache })` 动态加载
     - 取 `moduleExports.default ?? moduleExports[exportName ?? "plugin"]`
     - 校验后包装 `setup`：注入 `session`、`client`、`user`、`workspaceInfo`、`automation`、`logger`、`telemetry`（用户传入优先于 ctx 传入）
     - 通过 `normalizePluginManifest` 规范化 manifest
   - `loadAgentPluginsFromPathsWithDiagnostics(pluginPaths, options)`：
     - 顺序加载，单个失败不影响其他，失败收集到 `failures: PluginInitializationFailure[]`
     - 按 `plugin.name` 去重，后加载的覆盖先加载的，覆盖收集到 `warnings`（`duplicate_plugin_override`）
     - 通过 `matchesPluginManifestTargeting` 过滤目标不匹配的插件
     - 保留加载顺序（`order` 字段）
     - 返回 `{ plugins, pluginPaths, failures, warnings }`

2. **`plugin-module-import.ts`**（约 682 行，jiti 加载器）：
   - 静态分析 import/require 语句（4 种正则模式）
   - 依赖预检（`assertPluginDependenciesInstalled`）：非 TS 文件强制预检 bare specifier 是否可解析
   - 工作区别名（`WORKSPACE_ALIASES`）：dev 模式下将 `@cline/sdk` 等映射到 src 源码路径
   - Host-runtime SDK specifier 注入（`HOST_PROVIDED_SDK_SPECIFIERS`）
   - `isPackageBasedPlugin`：向上查找最多 4 层找 `cline` 字段的 package.json
   - jiti 实例化：`interopDefault: false`、`tryNative: false`、`transformModules` 仅对 TS alias target 启用 babel transform
   - Bun 编译二进制兼容：手动定位 `jiti/dist/babel.cjs` 并注入 transform

3. **`plugin-load-report.ts`**（约 20 行）：定义 `PluginInitializationFailure`、`PluginInitializationWarning`、`PluginLoadDiagnostics` 类型

**我的实现**：无。

**影响**：
- 无法动态加载第三方 JS/TS 插件模块
- 无 plugin manifest 校验（capabilities 必填、providerIds/modelIds 类型校验）
- 无 setup 上下文注入（session/client/user/workspaceInfo 等）
- 无加载诊断（failures/warnings）
- 无重名冲突检测

**修复建议**：暂不实现。Python 生态下无 jiti 等价物，可考虑 `importlib` + manifest YAML 校验作为最小实现，但工作量与收益不匹配。

**优先级**：P3

---

### 差距 #Y3：plugin-sandbox 缺失

**严重度**：P3（仅在有第三方插件时才需要沙箱）

**Cline 实现**：

1. **`plugin-sandbox.ts`**（约 648 行）：
   - `loadSandboxedPlugins(options)`：
     - 创建 `SubprocessSandbox({ name: "plugin-sandbox", bootstrapFile | bootstrapScript, onEvent })`
     - 解析 bootstrap：先尝试 `plugin-sandbox-bootstrap.js`（生产）、`extensions/plugin-sandbox-bootstrap.js`、`agents/plugin-sandbox-bootstrap.js`、wrapper 路径、execPath 路径；dev 模式回退到内联 jiti 脚本
     - 超时配置（`withTimeoutFallback`）：
       - `importTimeoutMs`：默认 4000ms，env `CLINE_PLUGIN_IMPORT_TIMEOUT_MS` 可覆盖（Number 严格解析，拒绝 `4000ms` 这类带尾随字符的值）
       - `hookTimeoutMs`：默认 3000ms
       - `contributionTimeoutMs`：默认 60000ms
     - `sandbox.call("initialize", initArgs, { timeoutMs })` RPC 初始化
     - 初始化失败：best-effort `sandbox.shutdown()` 后 rethrow
     - 并发再初始化保护：`reinitPromise ??=` 单例化，避免多个工具同时失败触发并发 reinit
     - "Unknown sandbox plugin id:" 错误识别 → 触发 reinit → 重试一次

   - **贡献注册**（每个 descriptor 一次性注册所有贡献）：
     - `registerTools`：每个 tool 的 `execute` 通过 `sandbox.call("executeTool", { pluginId, contributionId, input, context }, { timeoutMs })`
     - `registerCommands`：类似，调用 `executeCommand`
     - `registerRules`：`hasContentHandler === true` 时通过 `resolveRuleContent` RPC 拉取，否则用静态 `content`
     - `registerMessageBuilders`：`buildMessages` RPC，返回非数组时回退原 messages
     - `registerSimpleContributions`：providers、automationEventTypes、mcpServers（无 RPC，仅注册元数据）

   - **Hook 桥接**（`createSandboxRuntimeHooks`）：每个 hook 名生成 `makeHookHandler`，统一通过 `invokeHook` RPC

2. **`plugin-sandbox-bootstrap.ts`**（约 120+ 行，子进程入口）：
   - 在隔离 Node 子进程中运行，仅依赖本地类型镜像（避免 host package 导入）
   - 接收 RPC：`initialize`、`executeTool`、`executeCommand`、`resolveRuleContent`、`buildMessages`、`invokeHook`
   - 内部维护 `pluginId → PluginModule` 映射，`initialize` 时调用 `importPluginModule` 加载所有插件

**我的实现**：无。工具直接在主进程 asyncio 事件循环中执行（见 `agent/runtime.py`），无进程隔离。

**影响**：
- 无第三方插件隔离需求（因为无第三方插件）
- 无 RPC 协议、超时、并发 reinit 等基础设施

**修复建议**：暂不实现。若未来需要，可参考 `multiprocessing.Process` + pickle RPC 实现简化版，但 Python 插件生态以 entry_points 为主流，子进程沙箱非首选。

**优先级**：P3

---

### 差距 #Y4：plugin-targeting 缺失

**严重度**：P3（依赖 Y1/Y2，独立无意义）

**Cline 实现**（`plugin-targeting.ts`，约 32 行）：

```typescript
export interface PluginTargeting {
    providerId?: string;
    modelId?: string;
}

export function matchesPluginManifestTargeting(manifest, targeting): boolean {
    if (!manifest) return true;
    if (manifest.providerIds?.length) {
        if (!targeting?.providerId || !manifest.providerIds.includes(targeting.providerId)) {
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

**我的实现**：无。

**影响**：
- 无法按 LLM provider/model 限制插件激活范围（如「GPT-4 专用插件」、「Anthropic 专用插件」）
- 我们的 `agent/providers/` 已有多 provider 支持（Phase R），但无插件层级的 targeting

**修复建议**：暂不实现。该机制仅在有大量异构插件时才有价值，量化场景下 provider 集中（OpenAI/Qwen）且无第三方插件。

**优先级**：P3

---

### 差距 #Y5：marketplace 安装缺失

**严重度**：P3（量化场景不需要远程市场）

**Cline 实现**：

1. **`installMarketplaceEntry.ts`**（约 20 行，RPC 入口）：
   ```typescript
   export async function installMarketplaceEntry(controller, request) {
       if (!request.entry) throw new Error("Marketplace entry is required.");
       const result = await installMarketplaceEntryFromCatalog(request.entry);
       if (request.entry.type === "mcp") {
           await controller.mcpHub?.reconcileMcpServersFromSettingsRPC();
       }
       if (request.entry.type === "skill" || request.entry.type === "plugin") {
           await controller.invalidateUserInstructionService();
       }
       return result;
   }
   ```
   - 后置动作按类型分支：mcp → 重建 mcp settings；skill/plugin → 失效 user instruction 缓存

2. **`marketplace-helpers.ts::installMarketplaceEntryFromCatalog`**（约 6 行分发）：
   - 校验 `args.length > 0`
   - `mcp` → `installMcpMarketplaceEntry`：`parseMcpInstallArgs(args)` + `installMcpServer(parsed)`
   - `plugin` → `installPluginMarketplaceEntry`：`installPlugin({ source })` + 同步 MCP servers（`mcpSyncFailures` 收集为 warnings）
   - `skill` → `installSkillMarketplaceEntry`：spawn `npx -y skills@latest add ... -g -a cline -y`

3. **关键安全/稳定性设施**：
   - **超时**：`INSTALL_COMMAND_TIMEOUT_MS = 120_000`（120 秒），超时发 SIGTERM，125 秒后 SIGKILL 兜底
   - **输出截断**：`MAX_OUTPUT_CHARS = 12_000`，stdout/stderr 各保留最后 12000 字符
   - **密钥脱敏**（`redactOutput`）：多组正则匹配 `api_key`/`access_token`/`refresh_token`/`authorization`/`secret`/`password`/`credential`，分别处理 `key: value`、`Bearer xxx`、`Authorization: xxx` 三种形态，替换为 `[redacted]`
   - **JSON 错误提取**（`parseJsonErrorMessage`）：尝试解析 stdout/stderr 为 JSON，递归查找 `message`/`error`/`details`/`reason` 等字段
   - **Windows 兼容**：`shell: platform() === "win32"` 在 Windows 下强制走 shell
   - **命令格式化**（`formatCommand`）：拼接 `command args`，对含特殊字符的部分用 `JSON.stringify` 引号包裹（用于错误日志展示）

4. **官方插件识别**（`isOfficialPluginInstalled`）：
   - 计算 `official:https://github.com/cline/plugins.git#plugins/<source>` 的 sha256 前 12 位
   - 检查 `~/.cline/plugins/_installed/official/<sanitized>-<hash>` 是否存在

**我的实现**：无。

**影响**：
- 无法一键安装远程 MCP/skill/plugin
- 无密钥脱敏、超时、输出截断等安全设施（但这些设施在量化场景下也无用武之地）

**修复建议**：暂不实现。量化策略以本地代码 + 自有 skills 为主，无社区市场接入需求。

**优先级**：P3

---

### 差距 #Y6：marketplace 卸载缺失

**严重度**：P3（依赖 Y5）

**Cline 实现**：

1. **`uninstallMarketplaceEntry.ts`**（约 17 行，RPC 入口）：
   ```typescript
   export async function uninstallMarketplaceEntry(controller, request) {
       if (!request.entry) throw new Error("Marketplace entry is required.");
       const result = await uninstallMarketplaceEntryFromCatalog(controller, request.entry);
       if (request.entry.type === "skill" || request.entry.type === "plugin") {
           await controller.invalidateUserInstructionService();
       }
       return result;
   }
   ```
   - 注意：mcp 类型卸载后**不**调用 `invalidateUserInstructionService`（与 install 不对称，因为 mcp 卸载由 `mcpHub` 自己处理 reconcile）

2. **`marketplace-helpers.ts::uninstallMarketplaceEntryFromCatalog`**（约 12 行）：
   - 获取 `workspaceRoot`
   - 调用 `uninstallCoreMarketplaceEntry(toCoreMarketplaceEntry(entry), { deleteMcpServer, workspaceRoot })`
   - `deleteMcpServer` callback：`controller.mcpHub?.deleteServerRPC(name)`
   - 核心卸载逻辑在 `@cline/core` 包内（不在本仓库 vs code controller 层）

3. **本地卸载**（`uninstallLocalMarketplaceInstalledEntry`，约 50 行）：
   - **mcp**：`controller.mcpHub?.deleteServerRPC(name)`
   - **skill**：
     - `entry.path?.startsWith("remote:")` → 抛错「Remote-managed skills cannot be uninstalled from Customize.」
     - 否则 `deleteSkillFile(controller, { skillPath, isGlobal })` + `invalidateUserInstructionService()`
   - **plugin**：`uninstallPlugin({ name: entry.path ? undefined : name, path: entry.path, workspaceRoot })` + `invalidateUserInstructionService()`
   - 返回结构含 `removedPaths` 列表（用于日志展示）

**我的实现**：无。

**影响**：
- 无法卸载远程安装的扩展
- 无「remote-managed 资源不可本地卸载」的保护语义

**修复建议**：暂不实现。

**优先级**：P3

---

### 差距 #Y7：marketplace 列表缺失

**严重度**：P3（依赖 Y5/Y6）

**Cline 实现**：

1. **`getMarketplaceCatalog.ts`**（约 8 行，RPC 入口）：
   ```typescript
   export async function getMarketplaceCatalog(_controller, _request) {
       return fetchMarketplaceCatalog();
   }
   ```

2. **`marketplace-helpers.ts::fetchMarketplaceCatalog`**（约 13 行）：
   - 远程拉取 `https://cline.github.io/marketplace/catalog.json`（HTTP `Accept: application/json`）
   - HTTP 错误抛 `Failed to fetch marketplace catalog: <status> <statusText>`
   - 解析后逐条 `sanitizeEntry`：
     - 校验 `id`（非空 trim 字符串）、`type`（必须 ∈ `mcp`/`skill`/`plugin`）、`name`（默认取 id）
     - 可选字段：`tagline`、`description`、`tags`（字符串数组）、`author`、`sourceUrl`、`homepageUrl`
     - `install` 子对象：`args`（字符串数组）、`env`（数组，每项 `{ name, required, description, url }`）、`command`、`notes`
   - 返回 `MarketplaceCatalog.create({ entries })`

3. **`listInstalledMarketplaceEntries`**（约 10 行，从 catalog 过滤已安装）：
   - 三种检测：
     - `isMcpInstalled`：mcpHub 中 server name 标准化后匹配 entry 的 args[0]/id/name
     - `isSkillInstalled`：委托 `isMarketplaceSkillInstalled`（@cline/core）
     - `isOfficialPluginInstalled`：检查 `~/.cline/plugins/_installed/official/<sanitized>-<hash>` 路径存在
   - 返回 `installedKeys: ["<type>:<id>", ...]`
   - `normalizeMatchValue`：小写 + 非 alnum 转 `-` + 去首尾 `-`，用于宽松匹配

4. **`listLocalMarketplaceInstalledEntries`**（约 38 行，聚合本地所有已安装）：
   - MCP servers：`controller.mcpHub?.getServers()` → `{ id, type: "mcp", name, description: status, enabled: !disabled }`
   - Skills：`refreshSkills(controller)` 返回 `globalSkills` + `localSkills`，分别映射 source 为 `remote`/`global`/`workspace`
   - Plugins：`listPluginLocalEntries()`：
     - 遍历 `resolvePluginConfigSearchPaths(workspacePath)`
     - 每个 root 下 `discoverPluginModulePaths(root)`
     - `getPluginDisplayName`：向上查找 package.json 取 `name`，回退到 basename
     - source：`isGlobalClinePath` 判断是否在 `~/.cline` 或 `~/.agents/skills` 下
     - enabled：`!disabledPlugins.has(pluginPath)`

5. **`toggleLocalMarketplaceInstalledEntry`**（约 30 行，启用/禁用切换）：
   - mcp：`toggleServerDisabledRPC(name, !enabled)`
   - skill：`toggleSkill(controller, { skillPath, isGlobal, enabled })`
   - plugin：
     - 禁用：`disablePluginMcpServersInSettings({ pluginPaths: [path] })` + `setDisabledPlugin(path, true)`
     - 启用：先 disable 旧 MCP 引用，再 `syncPluginMcpServersToSettings` 重新同步，失败抛错，最后 `setDisabledPlugin(path, false)`

**我的实现**：无。本地 skills 列表能力由 `agent/skills/registry.py` 提供（Phase I 已对比），但无远程 catalog 拉取、无 mcp/plugin 聚合视图。

**影响**：
- 无法浏览远程市场目录
- 无法聚合展示本地所有已安装扩展（mcp + skill + plugin）的统一视图
- 无法在 UI 层一键启用/禁用插件

**修复建议**：暂不实现。

**优先级**：P3

---

## 4. 一致性统计

| 子项 | 一致性 | Cline 行数（核心文件） | 我方实现 |
|------|--------|----------------------|---------|
| Y1 plugin-config-loader | 缺失 | ~313 行 | 0 行 |
| Y2 plugin-loader | 缺失 | ~916 行（loader 214 + module-import 682 + load-report 20） | 0 行 |
| Y3 plugin-sandbox | 缺失 | ~648 行（sandbox 648 + bootstrap 120+） | 0 行 |
| Y4 plugin-targeting | 缺失 | ~32 行 | 0 行 |
| Y5 marketplace 安装 | 缺失 | ~340 行（installEntry 20 + helpers 相关 ~320） | 0 行 |
| Y6 marketplace 卸载 | 缺失 | ~80 行（uninstallEntry 17 + helpers 相关 ~63） | 0 行 |
| Y7 marketplace 列表 | 缺失 | ~120 行（getCatalog 8 + helpers 相关 ~112） | 0 行 |
| **合计** | **0/7** | **~2449 行** | **0 行** |

**对齐度**：0%（按子项计数）；若按代码量加权，约 0%。

**P0/P1/P2 数量**：0 项
**P3 数量**：7 项（全部）

---

## 5. 修复建议

### 短期（3 个月内）
- **不实现**。本阶段所有子项均为 P3，量化场景下无第三方插件需求，且实现成本极高（jiti 等价物、SubprocessSandbox 等价物、远程市场协议等），ROI 极低。
- 在 `AGENT_MIGRATION_PLAN.md` 中明确标注「Phase Y 暂缓，理由见第 7 节」。

### 中期（6-12 个月）
- 若出现以下任一信号，重新评估：
  1. 需要接入第三方数据源 connector（如第三方行情/资讯 API）且希望以插件形式隔离
  2. 需要让非核心团队成员（如策略研究员）上传策略插件而不污染主仓库
  3. 需要在多用户共享部署中按用户启用/禁用扩展
- 若触发，优先实现 **Y4（targeting）+ 简化版 Y1（路径发现，不含 package.json 声明识别）+ 简化版 Y2（仅 manifest 校验，用 importlib 加载）**，跳过 Y3 sandbox（Python 用 subprocess 隔离成本高，可先用 venv + entry_points 替代）。

### 长期（12 个月以上）
- 若形成内部「策略插件市场」需求（如多团队共享策略包），再评估 Y5-Y7 的内部版（不接公网 catalog，改用内部 git 仓库 + 简化 catalog.json）。
- 此时建议参考 Cline 的安全设施（密钥脱敏、超时、输出截断）一并实现。

---

## 6. 验证记录

| 验证项 | 方法 | 结果 |
|--------|------|------|
| Y1 文件存在 | `LS plugin/` | 确认 7 个文件存在（plugin-config-loader.ts 等） |
| Y1 关键函数 | `Read plugin-config-loader.ts` | 确认 `resolveAgentPluginPaths`、`resolveAndLoadAgentPlugins`、`collectPluginSkillRootCandidates` 等 |
| Y2 关键函数 | `Read plugin-loader.ts` + `plugin-module-import.ts` + `plugin-load-report.ts` | 确认 `loadAgentPluginFromPath`、`validatePluginExport`、`importPluginModule`、jiti 加载逻辑 |
| Y3 关键函数 | `Read plugin-sandbox.ts` + `plugin-sandbox-bootstrap.ts`（前 120 行） | 确认 `loadSandboxedPlugins`、`SubprocessSandbox`、RPC 协议、reinit 保护 |
| Y4 关键函数 | `Read plugin-targeting.ts` | 确认 `matchesPluginManifestTargeting` 完整逻辑（含空数组=匹配所有、保守不匹配策略） |
| Y5 安装链路 | `Read installMarketplaceEntry.ts` + `marketplace-helpers.ts` | 确认三分支（mcp/skill/plugin）、密钥脱敏、超时 120s、Windows shell 兼容 |
| Y6 卸载链路 | `Read uninstallMarketplaceEntry.ts` + `marketplace-helpers.ts::uninstallMarketplaceEntryFromCatalog` + `uninstallLocalMarketplaceInstalledEntry` | 确认 install/uninstall 不对称（mcp 卸载不 invalidate）、remote skill 不可卸载保护 |
| Y7 列表链路 | `Read getMarketplaceCatalog.ts` + `marketplace-helpers.ts::fetchMarketplaceCatalog` + `listInstalledMarketplaceEntries` + `listLocalMarketplaceInstalledEntries` + `toggleLocalMarketplaceInstalledEntry` | 确认远程 catalog URL、sanitizeEntry 校验、三态 installed 检测、本地聚合视图 |
| 我方实现存在性 | `Grep "plugin\|marketplace" agent/` | 仅 3 文件命中，且全部为注释引用 Cline 文件名 `user-instruction-plugin.ts`，无实际实现 |
| 对标文件路径 | `Read AGENT_CLINE_COMPARISON_PLAN.md` L965-985 | 确认 Y1-Y7 7 个子项与本报告一致 |

---

## 7. 量化场景适用性评估

### 7.1 评估结论

**Plugin / Marketplace 系统对当前量化场景「不需要」，建议 P3 暂缓实现。**

### 7.2 理由

1. **生态差异**：Cline 的 plugin/marketplace 面向「开发者社区贡献扩展」场景（GitHub 公开 catalog、第三方工具/规则/插件分发），目标用户是泛开发任务人群。本系统是单一团队的 A 股量化交易研究/执行平台，扩展以**内部代码迭代**为主，不存在社区分发需求。

2. **安全考量**：量化交易系统对「第三方可执行代码」天然敏感。Cline 的 sandbox（Node 子进程）+ 远程市场（公开 catalog.json）模式在量化场景下意味着：
   - 第三方插件可能触碰实盘下单链路（`live_trading/`、`miniqmt_trader_v2.py`）
   - 远程市场拉取引入供应链风险（npm 包劫持、catalog 篡改）
   - 沙箱逃逸在金融场景下的损失不可逆

   即便实现，也应以「内部 git 仓库 + code review + venv 隔离」替代公网市场。

3. **已有替代**：
   - **扩展能力**：已有 `agent/skills/`（Phase I 对比，本地 SKILL.md 加载）+ `agent/mcp/`（Phase Q 对比，MCP server 注册）+ `agent/tools/`（Phase F 对比，工具基类）
   - **多 provider 支持**：已有 `agent/providers/`（Phase R 对比，OpenAI/Qwen 工厂）
   - **配置禁用**：`agent_config/` 下 yaml 配置即可控制启用/禁用，无需复杂 plugin targeting

4. **实现成本**：Cline 该模块合计约 2449 行 TypeScript，核心难点（jiti 动态加载、SubprocessSandbox RPC、bootstrap 文件解析、workspace alias 解析）在 Python 下无 1:1 等价物。最小可用实现至少需要：
   - 路径发现（~200 行 Python）
   - importlib 加载 + manifest 校验（~300 行）
   - 简化 sandbox（multiprocessing + pickle RPC，~400 行，且性能/稳定性远不如 Node 子进程）
   - 远程 catalog（~150 行，含密钥脱敏）
   
   合计 ~1000+ 行 Python，且持续维护成本高（Python 版本演进、依赖冲突、venv 管理）。

5. **场景不匹配**：量化系统的「扩展」实际是**策略**（`dragon_strategy/`、`sector_rotation/`、`ml_strategy/` 等），这些是强类型 Python 模块，需要回测/实盘一致性验证，不适合「热加载/远程安装」模式，而应走「代码提交 → CI 回测 → 灰度部署」的标准研发流程。

### 7.3 何时需要重新评估

仅当出现以下场景之一时建议重新评估：

| 触发场景 | 推荐最小实现 |
|---------|------------|
| 非核心团队（如策略研究员）需上传策略包而不污染主仓库 | 仅 Y1 路径发现 + Y2 manifest 校验，跳过 Y3 sandbox（用 venv 隔离） |
| 多用户共享部署需按用户启用扩展 | 仅 Y4 targeting + 配置文件禁用，跳过 Y1-Y3 |
| 形成内部「策略插件市场」需求 | Y1+Y2+Y5-Y7 内部版（用内部 git 替代公网 catalog） |
| 接入第三方行情/资讯 API 需隔离 | 仅 Y3 简化版（subprocess + stdin/stdout JSON-RPC） |

### 7.4 风险提示

- 当前完全无 plugin 系统意味着**任何扩展都必须改主仓库代码**，对快速实验不友好。建议作为补偿：
  1. 完善 `agent/skills/` 的 SKILL.md 加载（已有）
  2. 完善 `agent/mcp/` 的 MCP server 配置（已有 `agent_config/mcp_servers.yaml`）
  3. 在 `agent_config/strategies.yaml` 中提供策略注册表机制（已有 `lib/strategy_registry.py`）

  这三条已在各自 Phase 中对比过，能够覆盖 80% 的「扩展」需求，且无需引入 plugin/marketplace 的复杂度。

---

## 8. 附录：Cline 源码索引

| 文件 | 行数 | 关键导出 |
|------|------|---------|
| `plugin-config-loader.ts` | 313 | `resolvePluginConfigSearchPaths`、`discoverPluginModulePaths`、`resolveAgentPluginPaths`、`resolveAgentPluginSkillDirectories`、`resolveAndLoadAgentPlugins` |
| `plugin-loader.ts` | 214 | `loadAgentPluginFromPath`、`loadAgentPluginsFromPaths`、`loadAgentPluginsFromPathsWithDiagnostics`、`validatePluginExport`、`validatePluginManifest` |
| `plugin-module-import.ts` | 682 | `importPluginModule`、`assertPluginDependenciesInstalled`、`collectPluginImportAliases` |
| `plugin-load-report.ts` | 20 | `PluginInitializationFailure`、`PluginInitializationWarning`、`PluginLoadDiagnostics` |
| `plugin-sandbox.ts` | 648 | `loadSandboxedPlugins`、`SandboxedPluginSetupContext`、`PluginSandboxOptions` |
| `plugin-sandbox-bootstrap.ts` | 120+ | 子进程入口（无导出，由 `SubprocessSandbox` spawn） |
| `plugin-targeting.ts` | 32 | `PluginTargeting`、`matchesPluginManifestTargeting` |
| `marketplace/installMarketplaceEntry.ts` | 20 | `installMarketplaceEntry` |
| `marketplace/uninstallMarketplaceEntry.ts` | 17 | `uninstallMarketplaceEntry` |
| `marketplace/getMarketplaceCatalog.ts` | 8 | `getMarketplaceCatalog` |
| `marketplace/marketplace-helpers.ts` | 635 | `fetchMarketplaceCatalog`、`installMarketplaceEntryFromCatalog`、`uninstallMarketplaceEntryFromCatalog`、`listInstalledMarketplaceEntries`、`listLocalMarketplaceInstalledEntries`、`toggleLocalMarketplaceInstalledEntry`、`uninstallLocalMarketplaceInstalledEntry`、`redactOutput`、`runCommand` |
| `marketplace/listMarketplaceInstalledEntries.ts` | 10 | `listMarketplaceInstalledEntries` |
| `marketplace/listMarketplaceLocalInstalledEntries.ts` | 11 | `listMarketplaceLocalInstalledEntries` |
| `marketplace/toggleMarketplaceLocalInstalledEntry.ts` | 13 | `toggleMarketplaceLocalInstalledEntry` |
| `marketplace/uninstallMarketplaceLocalInstalledEntry.ts` | 10 | `uninstallMarketplaceLocalInstalledEntry` |
