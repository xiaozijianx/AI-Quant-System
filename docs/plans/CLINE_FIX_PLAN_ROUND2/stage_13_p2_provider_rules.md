# Stage 13: P2 LLM Provider 与 Rules 补全方案

> 生成时间：2026-07-26
> 优先级：P2
> 预估工作量：1 周
> 依赖：Stage 10 完成（10.6 AgentRuntimeConfig 是 R5 的基础）
>
> 来源：
> - `CLINE_DIFF/SUMMARY_v2.md` §3.2 P2 级剩余差距 #17-#20
> - `CLINE_DIFF/phase_R_llm_provider.md`（R5 / R10）
> - `CLINE_DIFF/phase_X_rules_frontmatter.md`（X7 / X10）
>
> 涉及源文件：
> - 我的：`agent/providers/base.py`、`agent/providers/factory.py`、`agent/providers/qwen.py`、`agent/providers/openai.py`、`agent/rules_loader.py`、`agent/skills_loader.py`、`agent/types.py`
> - Cline：`third_party/cline/sdk/packages/core/src/services/llms/`、`third_party/cline/apps/vscode/src/core/context/instructions/`

---

## 0. 阶段总览

| 小阶段 | 任务 | 来源 | 严重度 | 涉及文件 |
|--------|------|------|--------|----------|
| 13.1 | capabilities 透传到 AgentModelRequest | R5 | P2 | agent/types.py、agent/providers/base.py、agent/runtime.py |
| 13.2 | provider-settings 持久化 | R10 | P2 | agent/providers/factory.py、agent/persistence/ |
| 13.3 | global/local toggle 分离 | X7 | P2 | agent/rules_loader.py、agent/persistence/ |
| 13.4 | skills multi-source + override resolution | X10 | P2 | agent/skills_loader.py |

依赖关系：
- 13.1 / 13.2 / 13.3 / 13.4 互相独立，可并行
- 建议执行顺序：13.1 → 13.2 → 13.3 → 13.4

---

## 13.1 capabilities 透传到 AgentModelRequest（R5）

### 任务背景

来源 Phase R #R5。Stage 7.8 已为 `ProviderDefaults` 增加 `capabilities: list[str]` 字段（如 `["tool_calls", "vision", "reasoning"]`），但该字段**未透传到 `AgentModelRequest`**：
- runtime 构造 `AgentModelRequest` 时不包含 capabilities
- Provider 在 `stream_chat` 中无法获知当前模型的能力，无法做能力路由
- 量化场景下，部分模型不支持 vision，runtime 应根据 capabilities 决定是否将 ImagePart 转为文本描述

Cline 的 `llm-gateway.ts` 中 `AgentModelRequest.capabilities` 字段供 Provider 决策：
- 无 `tool_calls` 能力时，将 ToolCallPart 转为文本指令
- 无 `vision` 能力时，将 ImagePart 转为 `[image: alt_text]`
- 无 `reasoning` 能力时，丢弃 ReasoningPart

### 目标

让 capabilities 透传到 `AgentModelRequest`，供 runtime 和 Provider 决策：
1. `AgentModelRequest` 增加 `capabilities: list[str]` 字段
2. runtime 构造 request 时从 ProviderDefaults 读取并填充
3. Provider 在 `stream_chat` 中根据 capabilities 做能力降级

### 当前实现位置

- `agent/types.py`（`AgentModelRequest` dataclass）
- `agent/providers/base.py`（`LLMProvider` 抽象类）
- `agent/providers/factory.py`（`ProviderDefaults.capabilities` 字段，已有）
- `agent/runtime.py`（`_generate_assistant_message` 构造 request）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/shared/src/agent.ts`（`AgentModelRequest.capabilities`）
- Cline `third_party/cline/sdk/packages/core/src/services/llms/llm-gateway.ts`（capabilities 读取与降级）

### 修复步骤建议

1. **`AgentModelRequest` 增加 `capabilities` 字段**
   - 在 `agent/types.py` 的 `AgentModelRequest` 中：
     ```python
     @dataclass
     class AgentModelRequest:
         # 原有字段...
         system_prompt: str
         messages: list[AgentMessage]
         tools: list[AgentToolDefinition]
         # ...
         capabilities: list[str] = field(default_factory=list)
     ```
   - 默认空 list（向后兼容，无能力约束）

2. **runtime 构造 request 时填充 capabilities**
   - 在 `_generate_assistant_message` 中构造 request：
     ```python
     provider_defaults = self._provider.get_defaults()  # 新增方法
     request = AgentModelRequest(
         system_prompt=...,
         messages=...,
         tools=...,
         capabilities=provider_defaults.capabilities,
     )
     ```
   - `LLMProvider.get_defaults()` 返回 `ProviderDefaults` 实例（已有）

3. **能力降级逻辑（Provider 层）**
   - 在 `agent/providers/base.py` 的 `LLMProvider` 抽象类中新增 `_apply_capability_downgrade(request: AgentModelRequest) -> AgentModelRequest`：
     ```python
     def _apply_capability_downgrade(self, request: AgentModelRequest) -> AgentModelRequest:
         """根据 capabilities 降级 request 中的 content"""
         caps = request.capabilities
         for msg in request.messages:
             new_content = []
             for part in msg.content:
                 if isinstance(part, ImagePart) and "vision" not in caps:
                     # 降级为文本描述
                     new_content.append(TextPart(
                         text=f"[image: {part.alt_text or 'truncated'}]",
                     ))
                 elif isinstance(part, ReasoningPart) and "reasoning" not in caps:
                     # 丢弃 reasoning
                     continue
                 else:
                     new_content.append(part)
             msg.content = new_content
         return request
     ```
   - 在 `stream_chat` 入口调用 `_apply_capability_downgrade`
   - 保留原 request 不变（降级在副本上进行）

4. **tool_calls 能力处理**
   - 无 `tool_calls` 能力时，将 `tools` 字段置空，将 ToolCallPart 转为文本指令
   - 该降级较复杂，建议仅在 `stream_chat` 中处理（不修改 request）
   - Provider 检测 `"tool_calls" not in capabilities` 时：
     - 不传 `tools` 参数给 LLM
     - 在 system_prompt 追加"请用文本描述你想执行的操作"

5. **capabilities 字段标准化**
   - 在 `agent/types.py` 中定义常量：
     ```python
     MODEL_CAPABILITIES = {
         "tool_calls": "支持工具调用",
         "vision": "支持图像输入",
         "reasoning": "支持思考链",
         "streaming": "支持流式输出",
     }
     ```
   - ProviderDefaults 配置时按此列表标准化

### 验证方法

1. 配置 qwen-plus 模型 capabilities=["tool_calls", "streaming"]（无 vision）
2. 构造含 ImagePart 的 request，确认 Provider 降级为文本描述
3. 配置 capabilities=["vision"]，确认 ImagePart 不被降级
4. 调用 `LLMProvider.get_defaults()` 确认返回 ProviderDefaults 含 capabilities

### 注意事项

- 降级在 Provider 层执行，runtime 层仅填充 capabilities 字段
- 降级不修改原 request（在副本上操作），避免影响压缩历史
- 不强制所有 Provider 都实现降级（仅 qwen/openai 实现，其他 Provider 保留原行为）

---

## 13.2 provider-settings 持久化（R10）

### 任务背景

来源 Phase R #R10。当前 Provider 配置（model name / api_key / base_url / temperature / max_tokens 等）通过 `agent_config/providers.yaml` 加载，运行时修改不持久化：
- 用户在前端调整 temperature 后，重启 agent 配置丢失
- 量化场景下，用户可能根据策略类型切换模型（如研报用 qwen-max，因子计算用 qwen-plus），每次手动改配置繁琐

Cline 的 `provider-settings.ts` 中 Provider 配置持久化到 `globalState`，跨会话保留。

### 目标

实现 Provider 配置持久化：
1. 用户通过 API 修改 Provider 配置时，写回 `agent_config/providers.yaml`
2. agent 启动时从 yaml 加载（已有），运行时修改写回
3. 提供 `GET/PUT /api/agent/providers/<provider_id>` API

### 当前实现位置

- `agent/providers/factory.py`（`ProviderFactory.load_from_yaml` / `ProviderFactory.get_provider`）
- `agent_config/providers.yaml`（配置文件）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/services/llms/provider-settings.ts`（`ProviderSettings` 持久化）

### 修复步骤建议

1. **`ProviderFactory` 增加持久化方法**
   - 在 `agent/providers/factory.py` 中新增：
     ```python
     class ProviderFactory:
         def __init__(self, config_path: Path):
             self._config_path = config_path
             self._providers: dict[str, ProviderConfig] = {}
             self._lock = asyncio.Lock()

         async def update_provider(self, provider_id: str, updates: dict) -> ProviderConfig:
             """更新 Provider 配置并持久化"""
             async with self._lock:
                 config = self._providers[provider_id]
                 # 更新字段
                 for key, value in updates.items():
                     if hasattr(config, key):
                         setattr(config, key, value)
                 # 写回 yaml
                 self._save_to_yaml()
                 return config

         def _save_to_yaml(self) -> None:
             """写回 yaml 文件"""
             data = {pid: cfg.to_dict() for pid, cfg in self._providers.items()}
             with open(self._config_path, "w", encoding="utf-8") as f:
                 yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
     ```
   - 用 `asyncio.Lock` 保证并发安全
   - 写回用 `yaml.safe_dump` 保持格式

2. **`ProviderConfig` 增加 `to_dict` 方法**
   - 在 `agent/providers/factory.py` 中扩展 `ProviderConfig` dataclass：
     ```python
     @dataclass
     class ProviderConfig:
         provider_id: str
         model_id: str
         api_key: str = ""
         base_url: str = ""
         temperature: float = 0.7
         max_tokens: int = 4096
         # ...

         def to_dict(self) -> dict:
             return {
                 "provider_id": self.provider_id,
                 "model_id": self.model_id,
                 "api_key": self.api_key,
                 "base_url": self.base_url,
                 "temperature": self.temperature,
                 "max_tokens": self.max_tokens,
             }
     ```
   - 字段名与 yaml 中的 key 一致

3. **新增 API 端点**
   - 在 `agent/server.py` 中注册：
     - `GET /api/agent/providers`：返回所有 Provider 配置（脱敏 api_key）
     - `GET /api/agent/providers/<provider_id>`：返回单个 Provider 配置
     - `PUT /api/agent/providers/<provider_id>`：更新 Provider 配置
   - PUT 请求体：`{"temperature": 0.5, "max_tokens": 8192}`
   - 返回更新后的配置（脱敏 api_key，仅显示前 4 位 + ***）

4. **api_key 脱敏**
   - GET 返回时 `api_key` 字段显示为 `"sk-***"`（仅前缀 + 掩码）
   - PUT 时不接受 `api_key` 字段（api_key 仅通过环境变量配置，符合用户规则）
   - 用户尝试 PUT api_key 时返回 400 错误

5. **配置变更生效**
   - PUT 成功后，调用 `ProviderFactory.rebuild_provider(provider_id)` 重建 Provider 实例
   - 重建会断开现有连接（如有），下次调用时重新建立
   - 进行中的 run 不受影响（已创建的 Provider 实例独立）

6. **前端配置 UI**
   - 在设置页面增加"Provider 配置"区块
   - 列出所有 Provider，支持编辑 temperature / max_tokens / base_url
   - api_key 字段只读显示掩码
   - 保存按钮调用 PUT API

### 验证方法

1. 调用 `PUT /api/agent/providers/qwen`，body 含 `{"temperature": 0.5}`
2. 确认 `agent_config/providers.yaml` 已更新
3. 重启 agent，确认配置仍为 temperature=0.5
4. GET API 确认 api_key 字段为 `"sk-***"`
5. PUT api_key 字段，确认返回 400

### 注意事项

- api_key 不允许通过 API 修改（仅环境变量配置，符合用户规则）
- 配置变更需重建 Provider 实例，可能影响连接池
- 不写 fallback：yaml 写入失败时抛错，让用户感知

---

## 13.3 global/local toggle 分离（X7）

### 任务背景

来源 Phase X #X7。Stage 7.2 已实现 rules toggle 持久化到 `rule_toggles.json`，但**未区分 global 和 local 粒度**：
- 所有 toggle 都写入同一个文件，全局生效
- 用户无法为不同会话配置不同 toggle（如"实盘交易会话启用 trading 规则，研报会话不启用"）
- 量化场景下，用户可能需要按场景切换规则集

Cline 的 `rule-conditionals.ts` 中支持 global toggle（全局）和 local toggle（per-workspace）分离，local 覆盖 global。

### 目标

实现 global/local toggle 分离：
1. `rule_toggles.json` 存 global toggle（已有）
2. `rule_toggles.local.json` 存 local toggle（per-session）
3. local 覆盖 global（同 key 时 local 优先）
4. 切换会话时加载对应的 local toggle

### 当前实现位置

- `agent/rules_loader.py`（`load_toggles` / `save_toggles` / `synchronize_rule_toggles`）
- `agent_config/rule_toggles.json`（global toggle 文件）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts`（globalState + workspaceState 双层）

### 修复步骤建议

1. **新增 local toggle 文件**
   - 路径：`agent_config/sessions/<session_id>/rule_toggles.local.json`
   - 格式与 global 一致：
     ```json
     {
       "version": 1,
       "toggles": {
         "trading": false,
         "research": true
       }
     }
     ```
   - 文件随会话存在，会话删除时一并删除

2. **`load_toggles` 支持双层加载**
   - 修改 `agent/rules_loader.py:load_toggles`：
     ```python
     def load_toggles(global_path: Path, local_path: Path | None = None) -> dict[str, bool]:
         """加载 toggle，local 覆盖 global"""
         toggles = {}
         # 1. 加载 global
         if global_path.exists():
             data = json.loads(global_path.read_text(encoding="utf-8"))
             toggles.update(data.get("toggles", {}))
         # 2. 加载 local（覆盖 global）
         if local_path and local_path.exists():
             data = json.loads(local_path.read_text(encoding="utf-8"))
             toggles.update(data.get("toggles", {}))
         return toggles
     ```
   - 保留原有 global 加载逻辑，新增 local 加载
   - local 文件不存在时仅用 global（向后兼容）

3. **`save_toggles` 支持 scope 参数**
   - 修改签名：
     ```python
     def save_toggles(
         path: Path,
         toggles: dict[str, bool],
         scope: str = "global",  # "global" / "local"
     ) -> None:
         """保存 toggle 到指定路径"""
         data = {"version": 1, "scope": scope, "toggles": toggles}
         tmp = path.with_suffix(".tmp")
         tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
         tmp.replace(path)
     ```
   - scope 字段记录类型，便于调试

4. **`synchronize_rule_toggles` 双层处理**
   - 修改函数签名：
     ```python
     def synchronize_rule_toggles(
         rules: list[RuleConfig],
         global_toggles: dict[str, bool],
         local_toggles: dict[str, bool] | None = None,
     ) -> list[RuleConfig]:
         """同步 toggle 到 rules，local 优先"""
         merged = dict(global_toggles)
         if local_toggles:
             merged.update(local_toggles)
         for rule in rules:
             if rule.name in merged:
                 rule.enabled = merged[rule.name]
         return rules
     ```

5. **新增 API 端点**
   - `GET /api/agent/sessions/<session_id>/rule_toggles?scope=local`：返回 local toggle
   - `PUT /api/agent/sessions/<session_id>/rule_toggles`：更新 local toggle
   - `DELETE /api/agent/sessions/<session_id>/rule_toggles`：清空 local toggle（回退到 global）
   - 保留原有 global toggle API

6. **前端 toggle UI**
   - 规则列表中每个规则显示两个开关：
     - 全局开关（影响所有会话）
     - 本会话开关（仅当前会话，覆盖全局）
   - 本会话开关默认显示"跟随全局"，启用后变为"本会话启用/禁用"
   - 切换会话时重新加载 local toggle

### 验证方法

1. 在会话 A 中将 trading 规则的 local toggle 设为 false
2. 确认会话 A 中 trading 规则不启用
3. 切换到会话 B，确认 trading 规则仍启用（global 默认 true）
4. 删除会话 A 的 local toggle，确认回退到 global
5. global 修改 trading=false，确认所有新会话默认 trading=false

### 注意事项

- local 文件路径含 session_id，需做路径转义（与 9.4 一致）
- local toggle 不影响其他会话（独立性）
- 文件写入用 `tmp.replace` 保证原子性

---

## 13.4 skills multi-source + override resolution（X10）

### 任务背景

来源 Phase X #X10。当前 skills 仅从单一目录 `agent_config/skills/` 加载，不支持多目录。Cline 支持多目录加载 + override 解析：
- 用户级 skills（`~/.cline/skills/`）
- 项目级 skills（`<workspace>/.cline/skills/`）
- 同名 skill 时项目级覆盖用户级

量化场景需求：
- 用户级 skills：通用研报生成、因子计算模板
- 项目级 skills：特定策略代码模板（如"动量策略生成器"）
- 同名时项目级优先，避免用户级被覆盖

### 目标

实现 skills 多目录加载 + override 解析：
1. `SkillsLoader` 支持多目录参数
2. 同名 skill 时按目录优先级覆盖
3. 加载日志记录 skill 来源（便于调试）

### 当前实现位置

- `agent/skills_loader.py`（`SkillsLoader.load_skills` 从单一目录加载）
- `agent_config/skills/`（默认 skills 目录）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/skills-loader.ts`（多目录加载）

### 修复步骤建议

1. **`SkillsLoader.load_skills` 支持多目录**
   - 修改签名：
     ```python
     def load_skills(
         dirs: list[Path],
         excluded_subdirs: list[str] | None = None,
     ) -> list[SkillConfig]:
         """从多个目录加载 skills，后加载的覆盖先加载的"""
         skills_by_name: dict[str, SkillConfig] = {}
         for d in dirs:
             if not d.exists():
                 continue
             for skill in self._load_from_dir(d, excluded_subdirs):
                 if skill.name in skills_by_name:
                     logger.info(
                         f"skill override: {skill.name} from "
                         f"{skills_by_name[skill.name].source_dir} -> {d}"
                     )
                 skill.source_dir = str(d)
                 skills_by_name[skill.name] = skill
         return list(skills_by_name.values())
     ```
   - 优先级：dirs 列表中**靠后**的目录优先级高（覆盖前面的）
   - 保留原有 `_load_from_dir` 单目录加载逻辑

2. **`SkillConfig` 增加 `source_dir` 字段**
   - 在 `agent/skills_loader.py` 的 `SkillConfig` 中：
     ```python
     @dataclass
     class SkillConfig:
         name: str
         description: str
         # 原有字段...
         source_dir: str = ""  # 新增：skill 来源目录
     ```
   - 用于 override 日志和调试

3. **目录优先级配置**
   - 在 `AgentRuntimeConfig` 中增加 `skills_dirs: list[Path]` 字段
   - 默认值 `[Path("agent_config/skills")]`（向后兼容）
   - 用户可配置多目录：
     ```yaml
     skills_dirs:
       - ~/.cline/skills  # 用户级（低优先级）
       - agent_config/skills  # 项目级（高优先级）
     ```
   - 加载顺序：列表顺序 = 优先级升序（后面覆盖前面）

4. **override 日志**
   - 加载时记录每个 override：
     ```
     [SkillsLoader] skill 'report_generator' overridden: /home/user/.cline/skills -> /workspace/agent_config/skills
     ```
   - 日志级别 INFO，便于调试
   - 不阻止 override（仅记录）

5. **`always` skills 合并**
   - 多目录中都有 `always: true` 的 skill 时，全部保留（不覆盖）
   - 同名 always skill 时按优先级覆盖（与其他 skill 一致）
   - `build_summary` 表格中显示 `source_dir` 列

6. **`keywords` 索引合并**
   - 多目录的 keywords 索引合并到统一字典
   - 同 keyword 指向多个 skill 时，按优先级排序（高优先级在前）
   - 检索时按优先级返回

### 验证方法

1. 配置两个 skills 目录：`/home/user/skills`（含 skill A）和 `agent_config/skills`（含 skill A 和 B）
2. 加载 skills，确认：
   - skill A 来自 `agent_config/skills`（覆盖用户级）
   - skill B 来自 `agent_config/skills`
   - 日志记录 override 信息
3. 调用 `skills` 工具，确认 skill A 的 `source_dir` 为项目级
4. 配置空目录，确认无报错（向后兼容）

### 注意事项

- 目录路径需展开 `~`（用 `Path.expanduser()`）
- 不存在的目录跳过（不报错）
- override 时不修改原 skill 文件（仅运行时覆盖）

---

## 14. 阶段汇总

### 14.1 完成判据

- 13.1：`AgentModelRequest.capabilities` 字段透传，Provider 能力降级生效
- 13.2：Provider 配置 PUT API 持久化到 yaml
- 13.3：global/local toggle 分离，local 覆盖 global
- 13.4：skills 多目录加载，同名 override 生效

### 14.2 风险与回滚

- 13.1 能力降级可能误判（如模型实际支持 vision 但 capabilities 未配置），需文档提示
- 13.2 yaml 写入需保证原子性（tmp.replace）
- 13.3 / 13.4 向后兼容，风险低

### 14.3 后续衔接

- 13.1 完成后，未来可扩展 capabilities 自动探测（通过模型 API 查询）
- 13.2 完成后，Stage 14 的 Z3/Z4（事件枚举）可基于 provider 变更事件扩展
- 13.4 完成后，未来可支持 skills 热重载（Stage 8.8 不实施项的预留）

---

**Stage 13 结束。建议按 13.1 → 13.2 → 13.3 → 13.4 顺序执行，完成后进入 Stage 14。**
