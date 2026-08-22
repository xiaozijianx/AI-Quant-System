# LLM 增强 GP 实施方案（第六阶段 · 独立引擎子页）

> 版本：v1（2026-08-18）
> 状态：待评审
> 对应主线设计：`因子挖掘页面设计方案.md` 阶段 6.2（其他引擎，独立子页备选）
> 定位：与 GP 主线（阶段 1~5）**互不并列**的独立引擎，独立子 Tab，不修改现有 GP 子 Tab 行为。

---

## 一、方案来源与依据

| 项 | 内容 |
|---|---|
| 方案名 | LLM 增强 GP（LLM-Augmented Genetic Programming） |
| 来源 | 东吴证券金工《AI因子挖掘的双路径实践与Skill沉淀》（2026-06，微信"东吴金工与产品研究"，finance.sina.com.cn 收录） |
| 实证 | 87 候选因子，全区间 \|RankIC\| 均值 6.98%，ICIR 0.79，81.6% 因子对相关 <0.70，测试集 RankIC 6.93% 稳定；相对 Alpha158MLP 增量 IC 2.53% |
| 四支柱 | ① LLM 子表达式基因供给 ② 分岛进化 ③ 周期性 LLM 注入 ④ 低相关筛选（<0.70） |

**本引擎必须忠实实现上述四支柱**。任何一项缺失都不构成"LLM 增强 GP"，只能算普通 GP 加了个 LLM 辅助，故不满足阶段 6.2 的立项依据。

---

## 二、目标与定位

1. **独立引擎**：不修改、不复用现有 `evolve()` 的"单岛主循环"作为本引擎的进化本体；而是新增一个多岛调度层，岛内个体选择/交叉/变异/评估**复用**现有逻辑。
2. **独立子界面**：在因子挖掘页新增 `miningSubTab === 'llm_gp'` 子 Tab，与现有 `ml / gp / svd` 同层并列，互不影响。
3. **可复用边界（原则）**：
   - 现有系统**已有且语义相同**的功能 → 复用；
   - 现有系统**没有**的功能（多岛调度、LLM 基因生成、周期注入、基因注册表）→ 新增，不得拿现有功能硬凑。

---

## 三、与现有 GP 的差异对比（复用 / 改造 / 新增矩阵）

| 能力点 | 现有实现（GP 主线） | LLM 增强 GP 要求 | 处理 |
|---|---|---|---|
| 个体表示 / 表达式树 | `random_tree` / `tree_to_str` / `formula_to_tree`（[factor_gp.py L281/L358/L513]） | 子表达式基因以树形态注册进空间，参与交叉/变异 | **复用**：LLM 产出公式 → `formula_to_tree` 解析为树 → 作为终端/子树注入 |
| 搜索空间 | `SPACE_LEVELS`（L0/L1/L2，[factor_gp.py L63-161]） | 需把"LLM 子表达式基因"注册为**新终端** | **改造（扩展）**：新增 `gene_registry` 基因注册表，运行时并入当前空间（不写死进 `SPACE_L0/L1/L2` 常量） |
| 适应度 / 评估 | `fitness_expr` + `run_ic_timeseries_panel` + GPU 整树求值 | 相同（RankIC 系适应度） | **复用** |
| 多进程并行 | `n_jobs` + `ProcessPoolExecutor`（[factor_gp.py L1130-1145]） | 岛内评估并行 | **复用**：岛与岛之间本身就是天然并行，但首版先做**单线程多岛调度**（简单可控），`n_jobs` 复用于岛内批量评估 |
| Warm-Start | `warm_start_trees / warm_start_formulas` 注入库内因子（[factor_gp.py L1102-1117]） | 本引擎的"基因供给"升级为 **LLM 生成子表达式**，库内公式 Warm-Start 仅作初始种群补充 | **复用**（初始种群注入框架）+ **新增**（LLM 基因生成器） |
| 进化主循环（选择/交叉/变异/精英/早停） | `evolve()` 单岛循环（[factor_gp.py L1497 起]） | 每岛独立跑"选择/交叉/变异"，岛间定期迁移 | **改造**：抽取岛内"一代推进"逻辑为可复用函数（或直接调用 `evolve` 的算子函数 `crossover/subtree_mutation/hoist_mutation/point_mutation`），**新增**多岛调度循环 |
| 去冗余 / 低相关筛选 | `dedup_by_corr`，默认 `corr_thresh=0.8`（[factor_gp.py L2235]） | 阈值收紧到 **0.70**（东吴口径） | **复用函数，改默认阈值**：本引擎调用时传 `corr_thresh=0.70` |
| 多样性维持 | `diversity_weight` Jaccard / `pca_qd` PCA 新奇性 | 分岛 + 迁移本身就是多样性机制，另加周期 LLM 注入 | **复用**（可选叠加）+ **新增**（岛间迁移） |
| LLM 调用 | AI 助手的 `QwenModel`（异步 `stream`）/ `providers.yaml` 配置 | 需在后台线程内同步调用 LLM 生成子表达式，且**配置独立**（不复用 AI 助手 provider，避免互相干扰） | **不复用**：新增独立配置存储（`factor_llm_config` 表）+ 轻量同步封装（openai 同步客户端，兼容模式；参考 preprocess.py 用法） |
| 三段分段 / OOS 复核 | `split_train_test_dates` / `oos_recheck` / `walk_forward_recheck` | 相同 | **复用** |
| 接口 | `/mine_gp`、`/mine_gp/stream`（[routes/factor.py L1125]） | 独立接口 | **新增** `/mine_llm_gp/stream`（SSE 流式，模式照抄现有，事件结构扩展） |
| 前端子页 | `miningSubTab === 'gp'`（[factor.html L766]） | 独立子 Tab | **新增** `miningSubTab === 'llm_gp'`，复用现有配色/卡片/栅格风格 |

**明确不能直接套用的项**：
- `evolve()` 的整体单岛循环**不能**当多岛用——多岛需要独立的种群状态、独立 RNG、跨代迁移挂点、LLM 注入挂点。复用粒度是**算子函数**（`crossover` 等）与"岛内一代推进模式"，不是整个 `evolve`。
- `QwenModel.stream()` 是异步接口，直接塞进同步后台线程会引入事件循环管理复杂度；本引擎在**线程内**用同步 OpenAI 兼容客户端。
- **不复用 AI 助手页面的大模型配置**（`agent_config/providers.yaml` / agent 模块 / `DASHSCOPE_API_KEY` 等）：LLM 增强 GP 在子页内**单独配置**大模型（api_key / base_url / model / temperature），存入独立配置表 `factor_llm_config`。两处配置互不读取、互不覆盖，避免串用互相干扰。

---

## 四、总体架构

```
因子挖掘页 (templates/factor.html)
  └─ miningSubTab === 'llm_gp'   ← 新增独立子 Tab
        │  fetch/EventSource
        ▼
routes/factor.py
  └─ POST /mine_llm_gp/stream    ← 新增 SSE 流式接口
        │
        ▼
lib/factor_llm_gp.py             ← 新增：LLM 增强 GP 引擎
  ├─ GeneGenerator        (LLM 子表达式基因生成器)
  │    └─ llm_client 同步封装（读取独立配置表 factor_llm_config）
  ├─ GeneRegistry         (基因注册表：LLM 基因 + 基础空间)
  ├─ IslandSchedule       (分岛进化调度器：多岛 + 迁移)
  ├─ PeriodicInject       (周期性 LLM 注入调度)
  └─ 收尾：dedup_by_corr(0.70) + OOS 复核（复用 factor_gp.py）
        │
        ▼
lib/factor_gp.py          ← 复用：formula_to_tree / crossover / 变异算子 /
                             fitness_expr / dedup_by_corr / 三段分段 / OOS
lib/factor_engine.py      ← 复用：evaluate_expression（LLM 基因合法性验证）
lib/factor_db.py          ← 新增：factor_llm_config 独立大模型配置表（init_tables 幂等建表，与 AI 助手 providers.yaml 完全隔离）
```

**数据流**：
1. 前端提交参数 → `/mine_llm_gp/stream` 启动后台线程。
2. 线程内先加载面板，做训练/验证/测试三段分段（复用）。
3. 首代前：调用 `GeneGenerator` 用 LLM 从量价结构批量生成子表达式基因 → 解析/求值验证 → 注册进 `GeneRegistry`。
4. 初始化 N 个岛屿种群（随机 + 库内公式 Warm-Start + 已注册 LLM 基因）。
5. 每代：每岛独立 评估 → 选择 → 交叉/变异（复用算子）→ 记录进化曲线。
6. 每 `migration_interval` 代：岛间迁移（环形拓扑，迁移每岛精英）。
7. 每 `inject_interval` 代：再次调用 LLM 生成新基因注入种群（替换岛内低适应度个体）。
8. 收尾：汇聚全部岛屿 hall_of_fame → `dedup_by_corr(corr_thresh=0.70)` → 测试段 OOS 复核 → 返回候选。

---

## 五、新增模块详细设计

### 5.1 LLM 子表达式基因生成器（GeneGenerator）

**职责**：按东吴口径从"量价结构"提取有金融逻辑的子表达式，作为表达式树空间的基本构件（终端基因）。

**输入**：
- 可用字段（复用 `GP_FIELDS`：Open/High/Low/Close/Volume/Amount/VWAP/Turnover/IdioRet/Value/TotalRet）
- 可用算子白名单（复用空间算子：`ts_Mean/ts_Stdev/ts_Delta/ts_Sum/ts_Rank/ts_Corr/ts_PctChange/ts_ROC/...`、`cs_Rank/cs_Demean/cs_Zscore`、`add/sub/mul/div/abs`、常数池）
- 窗口参数域（复用 `WINDOW_POOL`）

**七类子表达式维度**（对应东吴研报，映射到我们的字段）：

| 维度 | 金融逻辑 | 示例基因 |
|---|---|---|
| 收益率 | 动量 / 反转 | `ts_Mean(ts_PctChange(Close,1),10)` |
| 量能变化 | 放量缩量 | `ts_Mean(Volume,5)/ts_Mean(Volume,20)` |
| K线形态 | 上下影 / 实体 | `sub(Close,Open)/sub(High,Low)` |
| 价格位置 | 相对高低位 | `div(Close,ts_Max(High,20))` |
| 波动率 | 风险水平 | `ts_Stdev(ts_PctChange(Close,1),20)` |
| 路径效率 | 趋势直线性 | `abs(div(sub(Close,ts_Delay(Close,20)),ts_Sum(abs(ts_Delta(Close,1)),20)))` |
| 量价协同 | 量价背离/共振 | `ts_Corr(Close,Volume,20)` |

**输出格式（强制 JSON，方便程序解析）**：

```json
[
  {
    "category": "动量",
    "expr": "ts_Mean(ts_PctChange(Close,1),10)",
    "logic": "过去10日收益率均值，捕捉短期动量",
    "window": 10
  }
]
```

**生成数量**：每次调用生成 K 条（如 10~20 条），K 由参数 `genes_per_inject` 控制。

**合法性验证（硬性要求）**：LLM 输出**不可信**，逐条过三道闸：
1. 语法闸：`formula_to_tree(expr)` 解析成功（[factor_gp.py L513]）；
2. 求值闸：`evaluate_expression(expr, panel)` 返回非空面板（复用引擎）；
3. 去重闸：与基因注册表已有基因表达式去重（`expr_hash`）。
   任一道失败即丢弃该基因，不影响整体。

### 5.2 基因注册表（GeneRegistry）

**职责**：维护"基础算子空间 + LLM 基因终端"的统一搜索空间。

```python
class GeneRegistry:
    """LLM 增强 GP 的统一搜索空间
    - base_space: 复用 factor_gp.SPACE_LEVELS[space_level] 的字段/算子/常数
    - llm_genes:  [{expr, tree, category, logic}] 由 GeneGenerator 产出并经三道闸验证
    - 注入方式: LLM 基因作为"终端"(叶子) 嵌入树 —— 树节点 t="gene", name=expr, tree=原始树
      基因本身是一棵子树, 但以原子终端身份进入空间 (GP 不向基因内部注入子树,
      只可整体引用/被交叉拆下/被替换), 避免搜索空间爆炸, 与 L2 基类叶子的语义一致
    """
```

**为什么基因当"叶子/终端"而不是函数节点**：与现有 `_warm` 注入、L2 基类叶子同一语义——基因是"已封装好的复合体"，GP 不修改其内部，只组合它。这保证生成结果不重复发明轮子，且基因内部合法性由 LLM+三道闸负责。

### 5.3 分岛进化调度器（IslandSchedule）

**职责**：多岛独立进化 + 周期性迁移。

**参数**：

| 参数 | 默认 | 说明 |
|---|---|---|
| `n_islands` | 4 | 岛屿数量（1 退化为单岛，但本引擎建议 >=3） |
| `island_pop_size` | 60 | 每岛种群大小 |
| `migration_interval` | 10 | 每多少代迁移一次 |
| `migrate_count` | 6 | 每次每岛迁出/迁入的个体数 |
| `migration_topology` | `ring` | 迁移拓扑：`ring`（环形，i→i+1）/ `random`（随机配对）/ `all_to_best`（全部迁往当前最优岛） |
| `generations` | 40 | 总代数（所有岛同步推进同一代计数） |

**调度伪代码**：

```python
islands = [init_island(rng, size=island_pop_size) for _ in range(n_islands)]  # 每岛独立 RNG + 独立种群
for gen in range(generations):
    for idx, island in enumerate(islands):
        fit = eval_all(island.pop)                     # 复用 factor_gp 的评估/并行框架
        island.evolve_one_generation(...)              # 复用 crossover/变异算子 + 锦标赛选择
        emit_progress(gen, idx, island.stats)          # SSE 进度
    if (gen + 1) % migration_interval == 0:
        migrate(islands, topology, migrate_count)      # 环形迁移: 每岛取 top-k 精英迁入下一岛, 替换下一岛 bottom-k
    if (gen + 1) % inject_interval == 0:
        new_genes = gene_generator.generate(k=genes_per_inject)   # 周期 LLM 注入
        registry.register(new_genes)
        inject_genes_into_islands(islands, new_genes)  # 替换每岛最低适应度个体
```

**迁移实现要点**：迁出的个体是**树的拷贝**（`copy_tree`），迁入目标岛后替换其 `bottom migrate_count` 名低适应度个体，保证种群规模恒定。迁移本身通过 SSE 事件上报（`migration` 事件）。

### 5.4 周期性 LLM 注入（PeriodicInject）

**职责**：每隔 `inject_interval` 代调用 LLM 生成新基因，注入各岛种群。

**参数**：

| 参数 | 默认 | 说明 |
|---|---|---|
| `inject_interval` | 10 | 每多少代 LLM 注入一次（0 = 关闭周期注入，仅首代生成） |
| `genes_per_inject` | 12 | 每次生成并注入的基因数 |
| `max_inject_rounds` | 3 | 整个进化过程最多注入轮数（防无限调用、控成本） |

**注入目标**：把新基因以"终端"身份替换各岛 `bottom genes_per_inject` 名低适应度个体（与迁移同机制），同时注册进 `GeneRegistry` 供后续代随机引用。

**LLM 调用成本控制**：每次注入 = 1 次 LLM 调用（批量返回 K 条），默认 40 代 / 间隔 10 = 3 轮 + 首代 1 轮 = 4 次调用。可完全满足"周期性维持多样性"而不失控。

### 5.5 收尾筛选（复用）

- 汇聚全部岛屿 hall_of_fame（跨代收集，表达式去重）；
- `dedup_by_corr(candidates, corr_thresh=0.70)` 低相关筛选（[factor_gp.py L2235] 复用，**阈值传 0.70**，忠实东吴口径）；
- 测试段 `oos_recheck` / 可选 `walk_forward_recheck` 复核（复用）；
- 输出 Top-N 候选（含 expr / fitness / rank_ic / corr 报告）。

---

## 六、后端接口设计

### 6.1 `POST /api/factor/mine_llm_gp/stream`（新增，SSE 流式）

**请求体**：

```json
{
  "stock_codes": [],
  "pool_type": "active",
  "pool_ref": "",
  "start_date": "2023-01-01",
  "end_date": "2025-12-31",
  "train_ratio": 0.7,
  "val_ratio": 0.15,
  "rebal_period": 5,
  "max_depth": 4,
  "parsimony": 0.001,

  "n_islands": 4,
  "island_pop_size": 60,
  "generations": 40,
  "migration_interval": 10,
  "migrate_count": 6,
  "migration_topology": "ring",

  "inject_interval": 10,
  "genes_per_inject": 12,
  "max_inject_rounds": 3,
  "gene_enabled": true,

  "corr_thresh": 0.70,
  "use_warm_start": true,
  "space_level": "L0",
  "n_jobs": 1,
  "random_state": 42,
  "return_candidates": 20
}
```

> 说明：大模型参数**不通过 body 传递**。接口启动时后端从独立配置表 `factor_llm_config` 读取 api_key / base_url / model / temperature / max_tokens；表为空时若 body 显式传了 `llm_*` 字段则用其联调，否则返回 `error: 请先配置 LLM 增强 GP 的大模型`（前端跳到"大模型配置"区）。前端只保存配置，不随每次挖掘重复提交密钥。

**SSE 事件流**（复用现有 `/mine_gp/stream` 的 `heartbeat/progress/done/error` 框架，新增两类事件）：

| 事件 | 载荷 | 说明 |
|---|---|---|
| `progress` | `{gen, generations, island_idx, n_islands, best_fitness, avg_fitness}` | 每岛每代一次，前端画多岛进化曲线 |
| `llm_gene` | `{round, k, genes: [{expr, category}], accepted, rejected}` | 每次 LLM 基因生成完成时推送（含通过三道闸的数量） |
| `migration` | `{gen, topology, from_island, to_island, count}` | 每次迁移完成时推送 |
| `done` | 候选结果（含 dedup 报告、OOS 结果） | 结束 |
| `error` | `{error}` | 异常 |

### 6.2 独立大模型配置存储（新增）与 LLM 同步调用封装

**独立配置表 `factor_llm_config`（新增，幂等建表）**：在 `lib/factor_db.py` 的 `init_tables()` 内新增，单行配置（id=1），与 AI 助手的 `providers.yaml` / agent 模块 / `DASHSCOPE_API_KEY` 完全隔离：

```sql
CREATE TABLE IF NOT EXISTS factor_llm_config (
    id          SERIAL PRIMARY KEY,
    api_key     TEXT NOT NULL,
    base_url    TEXT NOT NULL DEFAULT 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model       VARCHAR(100) NOT NULL,
    temperature FLOAT DEFAULT 0.7,
    max_tokens  INT DEFAULT 2048,
    updated_at  TIMESTAMP DEFAULT NOW()
);
```

**配置接口（新增，routes/factor.py）**：
- `GET /api/factor/llm_gp/config`：返回独立配置（api_key 掩码显示，仅保留尾 4 位，避免前端明文常驻）；
- `PUT /api/factor/llm_gp/config`：保存独立配置（body 传 `api_key / base_url / model / temperature / max_tokens`；`api_key` 传空串或掩码值时保留库内原值，便于只改模型不动密钥）。

**读取优先级（`_run_llm_gp_pipeline` 内）**：优先读 `factor_llm_config` 表；表为空时若 body 显式传了 `llm_*` 参数则用 body（便于未配置时联调），否则报"请先配置 LLM 增强 GP 的大模型"。

**`_llm_chat(system_prompt, user_prompt) -> str`**（在 `lib/factor_llm_gp.py` 内）：
- 从 `factor_llm_config` 读取 api_key / base_url / model / temperature / max_tokens；
- 用 openai **同步**客户端（`openai.OpenAI`，兼容模式）调用（参考 preprocess.py `_embed_chunks_batch` 的 OpenAI 客户端用法），`response_format={"type":"json_object"}` 约束输出为 JSON；
- 失败重试 2 次；最终失败返回空列表（本轮注入跳过，不中断进化）。

> 注：不直接套 `QwenModel.stream()`（异步），也不读取 AI 助手的 `providers.yaml` / `DASHSCOPE_API_KEY` —— 配置独立、互不干扰，原因见"三、不能直接套用"。

---

## 七、前端页面设计（新增 `miningSubTab === 'llm_gp'`）

在 `templates/factor.html` 顶部子 Tab 栏新增按钮（样式与现有 `ml/gp/svd` 一致，参考 [factor.html L703-714]），`x-show="miningSubTab === 'llm_gp'"` 的内容区采用与 GP 子 Tab 相同的 `grid grid-cols-6 gap-3` 栅格与卡片风格。

**参数布局（自上而下，参照现有 GP 子 Tab 紧凑风格）**：

| 区域 | 参数 | 控件 |
|---|---|---|
| 大模型配置（独立） | api_key / base_url / model(默认 qwen3.7-flash) / temperature / max_tokens + "保存配置"按钮 | 折叠区；页面加载时 `GET /llm_gp/config` 回显（api_key 掩码），保存调 `PUT /llm_gp/config`。**与 AI 助手 provider 配置完全独立** |
| 公共参数 | 股票池 / 池引用 / 训练比例 / 验证比例 / 持有期 / 最大深度 / 复杂度惩罚 / 随机种子 | 同现有 GP |
| 分岛进化 | 岛屿数 / 每岛种群 / 总代数 / 迁移间隔(代) / 每次迁移数 / 迁移拓扑(ring/random/all_to_best) | number / select |
| LLM 基因 | 启用LLM基因(开关) / 注入间隔(代) / 每次注入基因数 / 最多注入轮数 | checkbox / number |
| 筛选与复核 | 低相关阈值(默认0.70) / Warm-Start(开关) / 并行进程数 / 返回候选数 | number / checkbox |
| 操作 | 运行按钮 `runLlmGp()` | 与 GP 同款蓝底白字 |

**结果展示区**：
- 多岛进化曲线（每岛一条线，`llm_gp_evolution_chart`，复用现有图表组件与图例置顶样式）；
- LLM 基因日志区（`llm_gene` 事件流，展示每轮生成的基因表达式 + 类别 + 接受/拒绝数，字体紧凑）；
- 候选结果表（expr / fitness / rank_ic / 相关剔除报告），沿用现有候选表展示与"入库"按钮逻辑。

**Alpine 状态新增**：`miningSubTab` 增加 `'llm_gp'` 分支；新增 `llmGpCfgApiKey / llmGpCfgBaseUrl / llmGpCfgModel / llmGpCfgTemp / llmGpCfgMaxTokens`（大模型配置）+ `llmGpNIslands / llmGpIslandPop / llmGpGenerations / llmGpMigInterval / llmGpMigCount / llmGpTopology / llmGpGeneEnabled / llmGpInjectInterval / llmGpGenesPerInject / llmGpCorrThresh / ...` 及 `llmGpProgress / llmGpGenes / llmGpResult / llmGpLiveCurve` 等；新增 `loadLlmGpConfig()`（GET 回显）/ `saveLlmGpConfig()`（PUT 保存）/ `runLlmGp()`（照抄 `runGp()` 的 SSE 消费模式，[factor.html L4904]），`sessionStorage` 持久化键名前缀 `llmGp`。

---

## 八、实施步骤（顺序执行）

1. **独立大模型配置（前置）**：在 `lib/factor_db.py` 的 `init_tables()` 新增 `factor_llm_config` 表；在 `routes/factor.py` 新增 `GET/PUT /llm_gp/config` 接口（api_key 掩码回显、空/掩码保留原值）。
2. **新建 `lib/factor_llm_gp.py`**：
   - 先写 `GeneRegistry`（含基因终端生成/校验/去重）；
   - 再写 `GeneGenerator` + `_llm_chat` 同步封装（**读取独立配置表 `factor_llm_config`，不读 providers.yaml**）；
   - 再写 `IslandSchedule` 多岛调度（岛内复用 `factor_gp` 的算子与评估）；
   - 收尾 `dedup_by_corr(0.70)` + OOS 复核；
3. **后端接口**：在 `routes/factor.py` 新增 `/mine_llm_gp/stream`，复制 `/mine_gp/stream` 的 SSE 线程框架，`_run_llm_gp_pipeline` 组装 `factor_llm_gp`（大模型参数取自独立配置表）。
4. **前端**：`templates/factor.html` 新增子 Tab 按钮 + 大模型配置折叠区 + 参数区 + 多岛曲线/基因日志/候选表 + `loadLlmGpConfig()`/`saveLlmGpConfig()`/`runLlmGp()`。
5. **自检**（用项目指定环境 python 执行）：
   - 大模型配置独立性与保存/回显（确认 GET 掩码、PUT 空密钥保留原值、不读 providers.yaml）；
   - LLM 基因三道闸验证（构造一组 LLM 返回，含 1 条非法语法、1 条求值失败、1 条重复，确认只接受合法项）；
   - 多岛调度 smoke（`n_islands=3`、`generations=5`、`inject_interval=2` 跑通，确认迁移/注入挂点触发）；
   - 与现有 GP 子 Tab 回归对照（确认 `miningSubTab='gp'` 行为零变化）。

---

## 九、风险与注意

1. **LLM 依赖**：本引擎首次在进化流程引入外部 LLM API 依赖。`gene_enabled=false` 时退化为"纯分岛 GP + 库内 Warm-Start"（仍可用，但不再是 LLM 增强 GP，界面需提示）。
2. **LLM 输出不可信**：三道闸（语法/求值/去重）是硬性要求，缺一不可；LLM 调用失败不中断进化（本轮注入跳过）。
3. **迁移语义**：迁移是"精英拷贝注入 + 替换低适应度个体"，不改种群规模；不做个体销毁，避免早熟丢失优秀基因。
4. **成本**：默认 4 次 LLM 调用（1 首轮 + 3 周期），由 `max_inject_rounds` 封顶。
5. **配置独立**：`factor_llm_config` 只被本引擎读写，不触碰 AI 助手的 `providers.yaml` / `DASHSCOPE_API_KEY`；api_key 存 PostgreSQL、GET 仅回显掩码，避免两处配置互相覆盖或泄露到前端。
6. **与 GP 主线互不影响**：不修改 `evolve()`、现有 GP 子 Tab、`/mine_gp*` 接口的任何行为（遵守"已完成功能不修改"原则）。

---

## 十、复用清单（实现时逐项核对）

**复用（不改代码）**：`formula_to_tree` / `copy_tree` / `crossover` / `subtree_mutation` / `hoist_mutation` / `point_mutation` / `tree_to_str` / `expr_hash` / `fitness_expr` / `dedup_by_corr`（仅改调用阈值 0.70）/ `split_train_test_dates` / `trim_panel_to_dates` / `oos_recheck` / `walk_forward_recheck` / `SPACE_LEVELS` / `GP_FIELDS` / `WINDOW_POOL` / `evaluate_expression` / `load_daily_kline` / `get_pool_stocks` / `get_active_stock_pool` / `factor_db._get_conn`（读独立配置表用）/ `/mine_gp/stream` 的 SSE 线程与事件框架。

**新增（本引擎独有）**：`factor_llm_config` 独立大模型配置表（`factor_db.init_tables()` 幂等建表）/ `GET·PUT /llm_gp/config` 配置接口 / `lib/factor_llm_gp.py`（GeneGenerator / GeneRegistry / IslandSchedule / PeriodicInject / `_llm_chat`）/ `/mine_llm_gp/stream` 接口 / `miningSubTab==='llm_gp'` 子 Tab / 大模型配置折叠区 / 多岛进化曲线与 LLM 基因日志展示。

**明确不复用（避免干扰 AI 助手）**：`agent_config/providers.yaml` / `agent/providers/*`（QwenModel / create_model 工厂）/ `DASHSCOPE_API_KEY` 环境变量。
