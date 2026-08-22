# RL 因子挖掘引擎实施方案（第六阶段 · 独立引擎子页 · 深度复刻 AlphaMaster）

> 版本：v2（2026-08-18）
> 状态：待评审（前置依赖已就绪）
> 对应主线设计：`因子挖掘页面设计方案.md` 阶段 6.1（其他引擎，独立子页备选）
> 定位：与 GP 主线（阶段 1~5）、LLM 增强 GP（阶段 6.2，已落地）**互不并列**的独立引擎，独立子 Tab，不修改现有 GP / LLM-GP 子 Tab 行为。
> 方案来源：AlphaMaster（github.com/rosemarycox5334-debug/AlphaMaster，AGPL-3.0）——基于深度神经网络强化学习的量化因子挖掘中心。
> 复刻原则：**深度复刻 AlphaMaster 的核心算法与工程机制**（REINFORCE 策略梯度 + Looped Transformer 自回归生成 + 约束采样 + StackVM 执行 + 多目标奖励 + Elite Replay + 熵坍塌重启 + checkpoint 断点续训）。本地设施仅在**语义等价**时复用（表达式求值 / GPU 整树求值 / 截面 IC 评价 / 三段分段 / 去冗余 / 入库），不等价则按 AlphaMaster 原样实现。
> 前置依赖（2026-08-18 已完成）：本方案依赖的算子/因子补充已按 [AlphaMaster特征算子与因子库映射方案.md](./AlphaMaster特征算子与因子库映射方案.md) 阶段一、二全部落地（17 个算子 + 2 个基础因子 + 27 个复合因子 + 22 个参数化基类 + price_position 退化 + rsi/adx/cci/willr/atr/reversal type 修正），RL 词表可直接从本系统因子库/算子表派生。RL 引擎本身（lib/factor_rl/ 包 + /mine_rl/stream 接口 + miningSubTab==='rl' 子 Tab）尚未实施。

---

## 一、AlphaMaster 全流程详解（复刻依据）

### 1.1 总体流程（训练 → 回测 → 实时）

```
数据层: Parquet K线文件 {品种}_{周期}.parquet
  → ParquetDataManager.load() 读 OHLCV + time
  → 时间戳去重/排序 → raw_dict {open,high,low,close,volume,time} 形状 [N=1, T]
  → target_ret[n,t] = log(open[t+2]/open[t+1])（未来2根开盘收益，最后2位补0）
  → feat_tensor = MT5FeatureEngineer.compute_features(raw_dict) 形状 [N, F=30, T]

模型层: AlphaGPT（Looped Transformer 3层×3循环, d_model=96, nhead=4, SwiGLU, RMSNorm）
  → 输入: 公式 token 序列前缀 [B, L]
  → 输出: 下一个 token 的 logits [B, vocab_size]

训练层: AlphaEngine.train()（REINFORCE 策略梯度）
  每步:
    Part A 采样 n_new 条新公式（ConstrainedSampler 约束自回归采样）
    Part B 从 Elite Pool 按得分加权采样 n_elite 条历史最优公式（回放）
    Part C 全部公式 → StackVM 执行 → MT5Backtest 多目标评分（Walk-Forward 折叠）
    Part D 策略梯度更新: loss = -Σ(log_prob × advantage) - entropy_coeff × entropy
    Part D2 熵监控（初始 token 分布熵）
    Part E 日志/训练历史/策略实时保存
    Part F 迁移 hook（Island 模式）
    Part G 熵坍塌检测 → 重启（best snapshot 恢复 + 噪声扰动）

输出层: strategies/best_{symbol}.json（vocab_version + formula token 序列 + best_score）
  → 回测/实时共用同一公式（StackVM 执行 → tanh(factor) 连续仓位）
```

### 1.2 各模块计算方式详解

#### 1.2.1 特征工程（model_core/features.py，30 特征）

| 类别 | 特征 | 计算方式 |
|---|---|---|
| 趋势 (0-4) | RET / RET5 / RET20 / MA_DIFF / SLOPE20 | 对数收益 / 5期收益 / 20期收益 / 价格-MA20 / 20期线性回归斜率 |
| 波动 (5-8) | ATR / RVOL / HL_RANGE / VOL_REGIME | 真实波幅均值 / 20期对数收益滚动std / (H-L)/C / 波动状态 |
| 反转 (9-13) | DEV / DEV60 / RSI14 / PRESSURE / AC1 | 价格偏离MA20 / 偏离MA60 / RSI归一化[-1,1] / 买卖压力 / 20期自相关 |
| 量 (14-16) | VOL_RATIO / VOL_Z / PV_CORR | 量比 / 量滚动zscore / 量价相关 |
| 交叉资产 (17-19) | REL_RET5 / REL_RET20 / REL_VOL | 相对宽品种集的收益/波动 |

**关键实现细节**：
- 全部**因果滚动**（unfold 滑动窗口），无 look-ahead；
- `_robust_norm`：滚动 median/MAD 归一化（窗口 200），warm-up 期输出 0（中性），避免饱和到 ±5 常数；
- 输出统一 `nan_to_num`，clip 到 ±5。

#### 1.2.2 算子库（model_core/ops.py，66 算子）

| 类别 | 算子 |
|---|---|
| 基础算术 (12) | ADD / SUB / MUL / DIV / NEG / ABS / SIGN / GATE(3元) / JUMP / DECAY / DELAY1 / MAX3 |
| 时序 (10) | TS_MEAN_5/10/20 / TS_STD_5/10/20 / TS_RANK_5/10/20 / TS_CORR_10 |
| 趋势动量 (6+) | MOMENTUM_5/10 / TS_SUM_5/10/20 / TS_MAX_10/20 / TS_MIN_10/20 / TS_ZSCORE_10/20 / TS_QUANTILE_10 / TS_SKEW_10 / DELTA / DELTA_5 / TS_ARGMAX / TS_ARGMIN / DECAY_LINEAR_5 / DECAY_EXP_5 / SCALE / TS_COVARIANCE / TS_PRODUCT / SIGNED_POWER / CLIP / SQRT / POWER / SIGNED_LOG / SIGMOID / TANH_SQUASH / WINSORIZE / WMA / EMA_5/20 / IF_GT |
| 截面 (3) | CS_RANK / CS_SCALE / CS_NEUTRALIZE（沿 N 维逐时间步，N=1 时恒等退化） |

**关键实现细节**：
- 统一契约：输入 [N,T] → 输出 [N,T]；
- 二元/三元算子入口形状校验（ShapeError）；
- 全部因果（`_ts_delay` 左补零、`_ts_rolling` unfold 滑动窗口）；
- 数值安全：DIV 加 1e-6、nan_to_num、clamp 防溢出。

#### 1.2.3 词表（model_core/vocab.py）

- token id 分段：特征 [0, F-1]，算子 [F, F+O-1]，`operator_offset = feature_count`；
- `VOCAB_VERSION = "v" + sha256("\n".join(token_names)).hexdigest()[:12]`（确定性派生）；
- 版本不匹配抛 `VocabVersionMismatchError`，拒绝加载旧 checkpoint / 策略文件。

#### 1.2.4 StackVM 执行器（model_core/vm.py）

- 栈式执行：特征 token 压栈，算子 token 弹 arity 个操作数 → 计算 → 压栈；
- 最终输出标准化 `_normalize_output`：
  - N>1：截面 zscore（每时间步跨品种），clip [-3,3]；
  - N=1：滚动时序 zscore（窗口 500，因果），warm-up 期输出 0；
- 恒正感染模型：`POSITIVE_ONLY_OPS`（TS_RANK/ABS 等恒正）、`INFECTED_PROPAGATING_OPS`（TS_MEAN/TS_SUM/TS_MAX 等传播）、`SIGN_RESTORE_OPS`（SUB/DIV/NEG/TS_ZSCORE/CS_NEUTRALIZE 等恢复）——防止因子退化为 beta。

#### 1.2.5 约束采样器（model_core/engine.py ConstrainedSampler）

- 栈深度约束：`delta = 1 - arity`，采样时保证 `new_depth >= 1` 且未来能收束到深度 1；
- 恒正感染约束：感染链 >= 2 禁传播算子，>= 3 强制恢复或结束；
- 对 logits 逐 batch 施加 mask（非法 token 置 -1e9）→ Categorical 采样 → **100% 合法公式**。

#### 1.2.6 多目标奖励（model_core/backtest.py MT5Backtest）

**评分框架**（组合级）：
```
final_score =
    0.35 × portfolio_sortino      # 组合风险调整收益
  + 0.20 × portfolio_calmar       # 回撤控制
  + 0.15 × ts_ic_stability        # 时序IC稳定性（IR）
  + 0.10 × symbol_consistency     # 品种一致性
  + 0.10 × cost_stress            # 2倍成本压力测试
  + 0.10 × turnover_quality       # 换手率质量
  - complexity_penalty            # 公式长度惩罚
  - correlation_penalty           # 因子相关性惩罚（engine 施加）
```

**`_multi_objective` 按 REWARD_MODE 分三套权重**：
- `standard`：0.60×ann_ret + 0.15×sortino + 0.10×calmar + 0.10×ts_ic + 0.05×turnover + 惩罚项；
- `ftmo`（默认）：0.75×ann_ret + 0.05×sortino + 0.10×calmar + 0.02×ts_ic + 0.03×sym_cons + 0.02×cost_stress + 0.03×turnover + 惩罚项（年化收益优先，控制 MDD 贴近 10% Max Loss）；
- `forex`：0.25×ann_ret + 0.05×sortino + 0.05×calmar + 0.25×ts_ic + 0.20×reversal_bonus + 0.15×symmetry + 0.05×turnover + 惩罚项（均值回归偏好）。

**关键实现细节**：
- `position = tanh(factor)` 连续仓位（strategy_manager/signal.py），`pnl = position × target_ret - turnover × cost_rate`；
- `_sortino`：下行标准差地板 = 全序列 std 的 20%（防稀疏 PnL 刷分），clip ±20；
- `_calmar`：年化收益 / 最大回撤，clip ±10；
- `_ts_ic_stability`：每品种 factor[t] vs ret[t+1] 相关，IR = mean/std，clip ±3；
- `_symbol_consistency`：无交易品种 >40% 重罚 -3，任何品种 Sortino<-2 罚 -2，正收益比例决定奖惩；
- `_cost_stress`：2 倍成本下 Sortino 是否仍 >0；
- `_turnover_quality`：每 12 bar 一笔为最优（高斯型奖励），持有期奖励；
- `_beta_neutral_penalty`：>85% 同方向重罚（防 beta 因子）；
- `_half_consistency_bonus`：前后半段 Sortino 同号奖励 / 反号重罚；
- `_exposure_penalty`：平均持仓 <10% 线性惩罚；
- `_turnover_penalty`：换手率 >0.2 梯度惩罚；
- Walk-Forward 折叠：rolling window（train_start=(k-1)×fold_size），val 段 OOS Sortino 门控（<=0 乘 0.1~0.5 惩罚，>0 乘最多 1.2 奖励）。

#### 1.2.7 训练循环（model_core/engine.py AlphaEngine.train）

**Part A 采样**：`inp_new = zeros(n_new, 1)`，逐 token 自回归：
```
for si in range(MAX_FORMULA_LEN):
    logits = model(inp_new)                    # [B, vocab]
    logits = sampler.apply_mask_to_logits(...) # 约束采样
    dist = Categorical(logits)
    a = dist.sample()
    lp_new.append(dist.log_prob(a))
    tok_new.append(a)
    ent_new.append(dist.entropy())
    inp_new = cat([inp_new, a.unsqueeze(1)], dim=1)
    # 更新栈深度 / 感染链
```

**Part B Elite Replay**：从 `_elite_pool`（Top-60，按得分指数加权 + 旧 elite 衰减）采样 n_elite 条，同样自回归计算 log_prob（**回放公式的 log_prob 用当前模型重算**，保证梯度正确）。

**Part C 评估**：全部公式（新 + 回放）→ `vm.execute(fml, feat)` → 常数/非法判 -2.0/-5.0 → Walk-Forward 折叠 `bt.evaluate_fold` → 训练段得分（用于梯度）+ 验证段得分（用于选冠军）→ IC 门控（`_apply_ic_gate`：IC>thresh 乘 1.15，IC<-thresh 乘 0.75）→ 重复惩罚（`_repetition_penalty`）→ 相关性惩罚（`_apply_corr_penalty`，与 factor_pool 中已有因子相关 >0.85 乘 0.8）。

**Part D 策略梯度更新**：
```
batch_mean = rewards.mean(); batch_std = rewards.std().clamp(min=0.1)
baseline = EMA(batch_mean) if REWARD_EMA_BASELINE else batch_mean   # Fix 3
adv = (rewards - baseline) / (batch_std + 1e-5)
policy_loss = -Σ(lp_new × adv_new) - Σ(lp_elite × adv_elite × ELITE_REWARD_SCALE)
entropy_coeff = ENTROPY_COEFF_MAX / (1 + entropy)^POWER
entropy_floor_loss = λ × max(0, thresh - entropy)   # Fix 1: H→0 时熵项归零问题
loss = policy_loss - entropy_coeff × mean_entropy + entropy_floor_loss
opt.zero_grad(); loss.backward()
clip_grad_norm_(params, 1.0); opt.step()
lord_opt.step()   # LoRD 低秩正则化（Newton-Schulz）
```

**Part G 熵坍塌检测与重启**：
```
if entropy < ENTROPY_COLLAPSE_THRESH: low_entropy_streak += 1
else: low_entropy_streak = 0
if low_entropy_streak >= ENTROPY_COLLAPSE_STEPS:
    restart_count += 1
    if restart_count % FULL_RESET_EVERY == 0 or entropy < 0.3:
        full_reset()   # 完全随机初始化
    elif best_snapshot:
        model.load_state_dict(best_snapshot)
        add_noise(restart_noise)   # 部分重置（PARTIAL_RESET_LAYERS）或全参数扰动
    opt = AdamW(model.parameters(), lr=1e-3)
```

**自适应噪声**：best 停滞时 `noise = base + BOOST × 0.1 × min(stagnation_ratio, 3)`，clamp 到 [NOISE_MIN, NOISE_MAX]。

**冠军更新**：验证段得分 > best_score 且通过 OOS 门控（train_val > 0.5 且 val < train×0.5 时拒绝；exposure < 0.05 时拒绝）→ 更新 best_score / best_formula / best_snapshot / factor_pool / elite_pool / 实时保存策略。

**Checkpoint**：每 20 步保存（模型权重 + 优化器状态 + best_score + best_formula + best_snapshot + factor_pool + elite_pool + 训练历史 + vocab_version），`load_checkpoint` 校验 vocab_version 后恢复。

#### 1.2.8 训练入口（train_file.py）

- 单品种 Parquet 训练；`--from-scratch` 清 checkpoint 重训（保留已有策略作为分数下限）；
- 自动续训：扫描 `checkpoints/ckpt_{symbol}_step_*.pt` 取最新恢复；
- 策略保存：`strategies/best_{symbol}.json`（vocab_version + formula + best_score + 元数据），磁盘已有更高分不覆盖。

#### 1.2.9 Web 层（web/）

- `training_manager.py`：子进程管理训练任务（start/stop/status/tail_log），日志落盘；
- `app.py`：FastAPI，三步界面（01 模型训练 / 02 策略回测 / 03 实时分析）；
- 训练曲线实时读取 `training_history_{symbol}.json`。

### 1.3 与本系统的关键差异（复刻时必须适配）

| 维度 | AlphaMaster | 本系统（CASE-AI量化系统） | 复刻处理 |
|---|---|---|---|
| 数据维度 | [N 品种, F 特征, T 时间]，单品种 N=1 | [T 日期, N 股票, F 特征] 面板 | 数据加载复用本地 `load_daily_kline` / `get_pool_stocks`，构建 [N, F, T] 张量 |
| 目标收益 | `log(open[t+2]/open[t+1])`（未来2根开盘） | 截面未来 rebal_period 日收益 | 复用本地 `future_returns` / `run_ic_timeseries_panel` 的收益口径 |
| 评价口径 | 组合回测（Sortino/Calmar/时序IC） | 截面 RankIC/ICIR/分层/多空 | **奖励适配为截面 RankIC 系**（见 5.4），其余机制（Elite Replay/熵重启/checkpoint）原样复刻 |
| 特征 | 30 个固定特征（MT5FeatureEngineer） | 300+ 因子库 + 基础字段 | 从本地 `GP_FIELDS` + 高频基础因子派生特征集（见 5.1） |
| 算子 | 66 个（ops.py） | 表达式引擎算子表（ts_*/cs_*/基类） | 从本地算子表派生词表（见 5.1），保证公式可被本地引擎求值 |
| 公式执行 | StackVM（token 栈式） | 表达式引擎 `evaluate_expression` + GPU 整树求值 | **深度复刻 StackVM**（token 序列直接执行，不转回表达式树），与 AlphaMaster 完全一致 |
| 训练设备 | CPU（实测 GPU 慢 2.3 倍） | 有 GPU 设施（factor_gpu_evaluator） | 模型训练默认 CPU（同 AlphaMaster），公式求值走本地 GPU 路径（可选） |
| 输出 | best_{symbol}.json（token 序列） | 因子库候选（表达式字符串） | token 序列 → 表达式字符串 → 复用 `upsert_factor` 入库 |

---

## 二、深度复刻目标与定位

1. **独立引擎**：新增 `lib/factor_rl.py`（深度复刻 AlphaMaster 的 model_core 全套：vocab / ops / vm / alphagpt / engine / backtest / signal），不修改现有 `evolve()` 与 GP / LLM-GP 子 Tab。
2. **独立子界面**：因子挖掘页新增 `miningSubTab === 'rl'` 子 Tab，与现有 `ml / gp / llm_gp / svd` 同层并列。
3. **复刻边界（原则）**：
   - **核心算法机制**（REINFORCE / Looped Transformer / ConstrainedSampler / StackVM / 多目标奖励 / Elite Replay / 熵坍塌重启 / 自适应噪声 / checkpoint）→ **按 AlphaMaster 原样深度复刻**；
   - **本地语义等价设施** → 复用（数据加载、三段分段、去冗余、入库、GPU 求值）；
   - **本地不等价设施** → 按 AlphaMaster 实现（StackVM 执行器、token 词表、约束采样器、策略梯度训练循环）。

---

## 三、复刻 / 复用 / 适配矩阵

| 能力点 | AlphaMaster 实现 | 本系统现有 | 处理 |
|---|---|---|---|
| 公式表示 | token 序列（RPN，StackVM 执行） | 表达式树（dict 树） | **深度复刻**：token 词表 + StackVM 执行器（lib/factor_rl/vm.py），不转回表达式树 |
| 特征集 | 30 特征（MT5FeatureEngineer） | GP_FIELDS + 300+ 因子库 | **适配**：从本地派生特征集（基础字段 + 高频基础因子），实现本地版特征计算 |
| 算子集 | 66 算子（ops.py） | 表达式引擎算子表 | **适配**：从本地算子表派生词表，算子实现按 AlphaMaster 语义（因果滚动）重写 |
| 生成模型 | AlphaGPT（Looped Transformer） | 无 | **深度复刻**：lib/factor_rl/alphagpt.py（同结构：d_model=96, 3层×3循环, SwiGLU, RMSNorm） |
| 约束采样 | ConstrainedSampler（栈深度+感染约束） | 无 | **深度复刻**：lib/factor_rl/sampler.py |
| 公式执行 | StackVM（token 栈式） | evaluate_expression / PanelTensorCompiler | **深度复刻**：lib/factor_rl/vm.py（token 直接执行，输出标准化同 AlphaMaster） |
| 奖励 | 多目标（Sortino/Calmar/时序IC/一致性/成本/换手） | 截面 RankIC/ICIR/分层 | **适配**：奖励 = 截面 RankIC 系（见 5.4），多目标框架（IC 门控/复杂度惩罚/相关性惩罚）原样复刻 |
| 训练循环 | REINFORCE + Elite Replay + 熵重启 + 自适应噪声 + EMA baseline | 无 | **深度复刻**：lib/factor_rl/trainer.py（Part A~G 全流程） |
| 正则化 | LoRD（Newton-Schulz 低秩衰减） | 无 | **深度复刻**：lib/factor_rl/lord.py |
| 断点续训 | checkpoint（模型+优化器+elite+best） | 无 | **深度复刻**：lib/factor_rl/checkpoint.py |
| 多起点 | Island（多引擎+精英迁移） | LLM-GP 有 Island 调度 | **复刻**：lib/factor_rl/island.py（首版可单岛，Island 作为可选） |
| 数据加载 | ParquetDataManager | load_daily_kline / get_pool_stocks | **复用**：本地数据源，构建 [N, F, T] 张量 |
| 三段分段 / OOS | split_train_test_dates / oos_recheck | 相同 | **复用** |
| 去冗余 | dedup_by_corr | 相同 | **复用** |
| 入库 | best_{symbol}.json | upsert_factor | **复用**：token → 表达式字符串 → upsert_factor |
| 接口 | Web 子进程管理 | /mine_gp/stream（SSE） | **复用**：SSE 线程框架，新增 /mine_rl/stream |
| 前端 | 独立 Web 三步界面 | miningSubTab 子 Tab | **适配**：新增 miningSubTab === 'rl'，复用现有卡片/图表风格 |

---

## 四、总体架构

```
因子挖掘页 (templates/factor.html)
  └─ miningSubTab === 'rl'        ← 新增独立子 Tab
        │  fetch/EventSource
        ▼
routes/factor.py
  └─ POST /mine_rl/stream         ← 新增 SSE 流式接口
        │
        ▼
lib/factor_rl/                    ← 新增包：深度复刻 AlphaMaster model_core
  ├─ vocab.py        FormulaVocab（token 词表 + 版本控制）
  ├─ ops.py          算子库（从本地算子表派生 + AlphaMaster 语义实现）
  ├─ features.py     特征集（从本地字段/因子派生）
  ├─ vm.py           StackVM 执行器（token 栈式 + 输出标准化 + 感染模型）
  ├─ alphagpt.py     AlphaGPT 生成模型（Looped Transformer）
  ├─ sampler.py      ConstrainedSampler（栈深度 + 感染约束）
  ├─ backtest.py     多目标奖励（适配截面 RankIC 系）
  ├─ lord.py         LoRD 低秩正则化
  ├─ trainer.py      AlphaEngine 训练循环（Part A~G）
  ├─ checkpoint.py   checkpoint 保存/加载
  └─ island.py       Island 多起点（可选）
        │
        ▼
lib/factor_gp.py                  ← 复用：split_train_test_dates / oos_recheck /
                                      walk_forward_recheck / dedup_by_corr
lib/factor_engine.py              ← 复用：evaluate_expression（求值兜底/校验）
lib/factor_db.py                  ← 复用：upsert_factor（候选入库）
lib/backtest_data.py              ← 复用：load_daily_kline（数据源）
```

**数据流**：
1. 前端提交参数 → `/mine_rl/stream` 启动后台线程。
2. 线程内加载面板（复用本地数据源）→ 构建 [N, F, T] 特征张量 + 目标收益张量。
3. 构建词表（从本地搜索空间派生）→ 初始化 AlphaGPT + ConstrainedSampler + StackVM。
4. 训练循环（深度复刻 AlphaMaster Part A~G）：采样 → 执行 → 多目标评分 → 策略梯度更新 → Elite Replay → 熵监控重启 → checkpoint。
5. 收尾：elite pool + 最终采样 → dedup_by_corr → 测试段 OOS 复核 → token 转表达式 → 返回候选（可入库）。

---

## 五、新增模块详细设计（深度复刻）

### 5.1 词表与特征/算子派生（vocab.py / features.py / ops.py）

**词表结构**（复刻 AlphaMaster vocab.py）：
```
token id 分段：
  [0, F-1]        特征 token（F 个）
  [F, F+O-1]      算子 token（O 个）
VOCAB_VERSION = "v" + sha256("\n".join(token_names)).hexdigest()[:12]
```

**特征 token 派生**（适配本系统，遵循"基础因子/复合因子/基类"设计，详见 [AlphaMaster特征算子与因子库映射方案.md](./AlphaMaster特征算子与因子库映射方案.md)）：
- **基础字段**：`Open / High / Low / Close / Volume / Amount / VWAP / Turnover / IdioRet / Value / TotalRet`（复用 GP_FIELDS，作为恒等叶子）；
- **基础因子**（固定参数基类实例，instance_type=basic，能直接计算）：从因子库挑选，如 `macd() / kdj() / bbands() / TALIB_MFI() / TALIB_PPO() / TALIB_UO() / TALIB_AROONOSC() / obv_slope_10d` 等（复用 `calc_factor` 计算）；
- **复合因子**（参数化基类实例 + 可调周期固定基类实例 + 多基类组合，instance_type=composite，依赖基类）：从因子库挑选，如 `returns(1/5/20) / momentum(5/10/20) / volatility(20) / amplitude(1) / volume_ratio(20) / price_volume_corr(10) / bias(20) / rsi(14) / atr(14) / cci(14) / willr(14) / adx(14) / cs_Demean(returns(5)) / cs_Rank(returns(5)) / cs_Zscore(returns(20)) / ts_Skewness(returns(1),20)` 等（复用 `calc_factor` 计算）；
- **特征计算**：基础字段直接取面板值；基础因子/复合因子用 `calc_factor` 预计算后转 [N, T] 张量；
- **补充原则**：若 AlphaMaster 特征在本系统缺失，按映射方案补充——基础因子缺失 → 同时注册因子表 + 基类表（固定参数基类实例）；复合因子缺失 → 依赖已存在的基类或本轮补充的基类（参数化基类实例）。

**算子 token 派生**（适配本系统，语义复刻 AlphaMaster）：
- 算术：`ADD / SUB / MUL / DIV / NEG / ABS / SIGN / GATE / JUMP / DECAY / DELAY1 / MAX3`（复刻 AlphaMaster 语义）；
- 时序：`TS_MEAN_5/10/20 / TS_STD_5/10/20 / TS_RANK_5/10/20 / TS_CORR_10 / TS_SUM_5/10/20 / TS_MAX_10/20 / TS_MIN_10/20 / TS_ZSCORE_10/20 / TS_QUANTILE_10 / TS_SKEW_10 / DELTA / DELTA_5 / TS_ARGMAX / TS_ARGMIN / DECAY_LINEAR_5 / DECAY_EXP_5 / SCALE / TS_COVARIANCE / TS_PRODUCT / SIGNED_POWER / CLIP / SQRT / POWER / SIGNED_LOG / SIGMOID / TANH_SQUASH / WINSORIZE / WMA / EMA_5/20 / IF_GT`（复刻 AlphaMaster 语义，全部因果滚动）；
- 截面：`CS_RANK / CS_SCALE / CS_NEUTRALIZE`（沿 N 维逐时间步，N=1 恒等退化）。

**算子实现**：按 AlphaMaster ops.py 的语义重写（`_ts_delay` 左补零、`_ts_rolling` unfold 滑动窗口、`_op_gate` 条件门、`_op_jump` 因果 expanding zscore + tanh 软化、`_op_decay` 归一化指数衰减、`_op_wma` 加权移动平均、`_delta` 差分、`_ts_argmax/argmin` 位置归一化、`_decay_linear/exp` 加权平均、`_scale` 因果 L1 归一化、`_ts_covariance/product`、`_signed_power` 带符号乘方、`_cs_rank/scale/neutralize` 截面算子）。

### 5.2 StackVM 执行器（vm.py，深度复刻）

**复刻 AlphaMaster vm.py 全部逻辑**：
- 栈式执行：特征 token 压栈，算子 token 弹 arity 个操作数 → 计算 → 压栈；
- 非法公式（栈不收敛 / 形状错误 / 异常）返回 None；
- 输出标准化 `_normalize_output`：
  - N>1：截面 zscore（每时间步跨股票），clip [-3,3]；
  - N=1：滚动时序 zscore（窗口 500，因果），warm-up 期输出 0；
- 恒正感染模型：`POSITIVE_ONLY_OPS` / `INFECTED_PROPAGATING_OPS` / `SIGN_RESTORE_OPS` 三集合 + `validate_formula_structure` 校验。

### 5.3 生成模型（alphagpt.py，深度复刻）

**复刻 AlphaMaster alphagpt.py 全部结构**：
- `AlphaGPT`：token_emb(vocab_size, 96) + pos_emb(1, 20, 96) + LoopedTransformer(3层×3循环, nhead=4, dim_ff=192, SwiGLU, RMSNorm) + ln_f + MTPHead(96, vocab_size)；
- `LoopedTransformerLayer`：MultiheadAttention + RMSNorm + SwiGLU FFN，循环 num_loops 次；
- `RMSNorm` / `SwiGLU` / `MTPHead`（单 head，返回 (logits, None)）；
- `NewtonSchulzLowRankDecay`（LoRD：Newton-Schulz 迭代求最小奇异向量方向，对 attention 参数做低秩衰减）；
- `StableRankMonitor`（稳定秩监控）。

### 5.4 多目标奖励（backtest.py，适配截面口径）

**适配原则**：多目标框架（IC 门控 / 复杂度惩罚 / 相关性惩罚 / Walk-Forward 折叠 / OOS 门控）**原样复刻**；核心指标从"组合回测 Sortino/Calmar"适配为"截面 RankIC 系"（本系统评价语义）。

**奖励计算（每条公式）**：
```
reward = w_ic × mean_rank_ic + w_ir × rank_ic_ir + w_layered × 分层单调性
         - parsimony × 公式长度
```

| 分量 | 计算 | 权重（默认） | 说明 |
|---|---|---|---|
| `mean_rank_ic` | 复用 `factor_gpu_evaluator.mean_rank_ic`（GPU）或 `run_ic_timeseries_panel`（CPU） | 1.0 | 截面 RankIC 均值，主指标 |
| `rank_ic_ir` | IC 均值 / IC 标准差 | 0.3 | 稳定性 |
| 分层单调性 | 复用分层回测的 Q5-Q1 单调性得分 | 0.2 | 单调性 |
| 复杂度惩罚 | `parsimony × 公式长度` | 0.001 | 防过拟合 |

**复刻 AlphaMaster 的辅助机制**：
- `_apply_ic_gate`：|IC| < 阈值奖励打折；IC < 0 不判死（方向由 direction 字段表达）；
- `_repetition_penalty`：相邻重复 token 惩罚；
- `_apply_corr_penalty`：与 factor_pool 已有因子相关 > 阈值乘 0.8；
- Walk-Forward 折叠：rolling window，训练段得分用于梯度，验证段得分用于选冠军（OOS 门控）；
- 常数/非法公式：-2.0 / -5.0。

### 5.5 训练循环（trainer.py，深度复刻）

**复刻 AlphaEngine.train() 的 Part A~G 全流程**（见 1.2.7 详解），关键超参：

| 参数 | 默认 | 说明 |
|---|---|---|
| `batch_size` | 192 | 每步采样公式数（AlphaMaster 192） |
| `train_steps` | 2000 | 训练步数（A 股日线数据量小于外汇 H1，可调） |
| `max_formula_len` | 8 | 公式 token 长度上限 |
| `lr` | 1e-3 | AdamW 学习率 |
| `entropy_coeff_max` | 1.0 | 熵正则系数上限 |
| `entropy_collapse_thresh` | 0.15 × ln(vocab_size) | 熵坍塌阈值（相对值） |
| `entropy_collapse_steps` | 20 | 连续低熵步数触发重启 |
| `max_restarts` | 10 | 最大重启次数（超过后强扰动继续训练） |
| `restart_noise` | 0.25 | 重启时参数扰动幅度 |
| `elite_pool_size` | 60 | 历史最优公式回放池大小 |
| `elite_replay_frac` | 0.25 | 每步回放比例 |
| `elite_reward_scale` | 1.2 | 回放公式奖励缩放 |
| `reward_ema_decay` | 0.95 | EMA baseline 衰减 |
| `adaptive_noise` | true | best 停滞时自动增大扰动 |
| `full_reset_every` | 3 | 每 3 次重启做 1 次完全随机初始化 |
| `partial_reset_layers` | (ln_f, mtp_head, blocks, token_emb) | 重启时部分重置的层 |
| `use_lord` | true | LoRD 低秩正则化 |

### 5.6 Checkpoint 断点续训（checkpoint.py，深度复刻）

- 保存内容：模型权重 / 优化器状态 / best_score / best_formula / best_snapshot / factor_pool / elite_pool / 训练历史 / vocab_version；
- 存储位置：`data/factor_rl_checkpoints/`；
- 加载时校验 vocab_version（不匹配抛错拒绝加载）；
- 接口：`/mine_rl/stream` 支持 `resume=true`（有 checkpoint 续训）/ `resume=false`（从头训练，保留已有策略作为分数下限）。

### 5.7 Island 多起点（island.py，可选）

- 复刻 AlphaMaster island_engine.py：N 个独立 AlphaEngine，每 `migration_interval` 步交换 Top-K elite（去重后注入各岛，替换低分 elite）；
- 同步全局最优到各岛 best_snapshot（restart 时从全局最优恢复）；
- 首版默认单岛（N_ISLANDS=1），Island 作为可选开关。

### 5.8 收尾筛选（复用）

- 汇聚 elite pool + 最终采样批次 → token 转表达式字符串（`_decode_formula`）→ 表达式去重；
- `dedup_by_corr(candidates, corr_thresh)` 低相关筛选（复用 factor_gp.py，默认 0.8）；
- 测试段 `oos_recheck` / 可选 `walk_forward_recheck` 复核（复用）；
- 输出 Top-N 候选（expr / rank_ic / icir / 分层 / 方向 / OOS 结果），与 GP 候选表结构一致，可直接入库。

---

## 六、后端接口设计

### 6.1 `POST /api/factor/mine_rl/stream`（新增，SSE 流式）

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

  "batch_size": 192,
  "train_steps": 2000,
  "max_formula_len": 8,
  "lr": 0.001,
  "entropy_coeff_max": 1.0,
  "elite_pool_size": 60,
  "elite_replay_frac": 0.25,
  "max_restarts": 10,
  "restart_noise": 0.25,
  "use_lord": true,

  "reward_ic_weight": 1.0,
  "reward_ir_weight": 0.3,
  "reward_layered_weight": 0.2,
  "parsimony": 0.001,

  "space_level": "L0",
  "corr_thresh": 0.8,
  "use_warm_start": true,
  "resume": false,
  "n_islands": 1,
  "random_state": 42,
  "return_candidates": 20
}
```

**SSE 事件流**（复用现有 `/mine_gp/stream` 的 `heartbeat/progress/done/error` 框架，新增事件）：

| 事件 | 载荷 | 说明 |
|---|---|---|
| `progress` | `{step, train_steps, best_score, avg_reward, entropy, unique_formulas}` | 每步一次，前端画训练曲线 |
| `restart` | `{restart_count, max_restarts, entropy, noise}` | 每次熵坍塌重启时推送 |
| `elite` | `{pool_size, top_score, top_formula}` | 每 100 步推送一次 elite 池状态 |
| `done` | 候选结果（含 dedup 报告、OOS 结果、训练曲线） | 结束 |
| `error` | `{error}` | 异常 |

### 6.2 训练曲线持久化

- 训练历史（step / avg_reward / best_score / entropy / elite_pool_size）随结果返回，前端画曲线；
- 与 GP 的 `evolution_curve` 结构对齐，前端可复用现有图表组件。

---

## 七、前端页面设计（新增 `miningSubTab === 'rl'`）

在 `templates/factor.html` 顶部子 Tab 栏新增按钮（样式与现有 `ml/gp/llm_gp/svd` 一致），`x-show="miningSubTab === 'rl'"` 的内容区采用与 GP 子 Tab 相同的 `grid grid-cols-6 gap-3` 栅格与卡片风格。

**参数布局（自上而下，参照现有 GP 子 Tab 紧凑风格）**：

| 区域 | 参数 | 控件 |
|---|---|---|
| 公共参数 | 股票池 / 池引用 / 训练比例 / 验证比例 / 持有期 / 随机种子 | 同现有 GP |
| 训练参数 | 每步采样数(192) / 训练步数(2000) / 公式长度上限(8) / 学习率(0.001) / 熵系数上限(1.0) / LoRD正则(开关) | number / checkbox |
| 探索控制 | 精英池大小(60) / 精英回放比例(0.25) / 最大重启次数(10) / 重启噪声(0.25) | number |
| 奖励权重 | IC权重(1.0) / IR权重(0.3) / 分层权重(0.2) / 复杂度惩罚(0.001) | number |
| 筛选与复核 | 低相关阈值(0.8) / Warm-Start(开关) / 断点续训(开关) / 岛屿数(1) / 返回候选数(20) | number / checkbox |
| 操作 | 运行按钮 `runRl()` | 与 GP 同款蓝底白字 |

**结果展示区**：
- 训练曲线（best_score / avg_reward / entropy 三条线，`rl_training_chart`，复用现有图表组件）；
- 重启日志区（`restart` 事件流，展示每次熵坍塌重启的步数/噪声/熵值）；
- 候选结果表（expr / rank_ic / icir / 分层 / 方向 / OOS 结果），沿用现有候选表展示与"入库"按钮逻辑。

**Alpine 状态新增**：`miningSubTab` 增加 `'rl'` 分支；新增 `rlBatchSize / rlTrainSteps / rlMaxLen / rlLr / rlEntropyMax / rlEliteSize / rlEliteFrac / rlMaxRestarts / rlRestartNoise / rlIcWeight / rlIrWeight / rlLayeredWeight / rlParsimony / rlCorrThresh / rlResume / rlNIslands / ...` 及 `rlProgress / rlResult / rlLiveCurve / rlRestartLog` 等；新增 `runRl()`（照抄 `runGp()` 的 SSE 消费模式，[factor.html L4904]），`sessionStorage` 持久化键名前缀 `rl`。

---

## 八、实施步骤（顺序执行）

1. **新建 `lib/factor_rl/` 包**（深度复刻 AlphaMaster model_core）：
   - `vocab.py`（词表派生 + 版本控制）→ `ops.py`（算子库）→ `features.py`（特征集）→ `vm.py`（StackVM）→ `alphagpt.py`（生成模型）→ `sampler.py`（约束采样）→ `backtest.py`（多目标奖励，适配截面口径）→ `lord.py` → `trainer.py`（Part A~G）→ `checkpoint.py` → `island.py`（可选）。
2. **后端接口**：在 `routes/factor.py` 新增 `/mine_rl/stream`，复制 `/mine_gp/stream` 的 SSE 线程框架，`_run_rl_pipeline` 组装 `factor_rl`。
3. **前端**：`templates/factor.html` 新增子 Tab 按钮 + 参数区 + 训练曲线/重启日志/候选表 + `runRl()`。
4. **自检**（用项目指定环境 python 执行）：
   - 词表/算子/特征派生正确性（token 名称唯一、版本确定性、算子形状契约）；
   - StackVM 执行正确性（随机 token 序列 1000 条，全部合法可执行，输出无 NaN/Inf）；
   - ConstrainedSampler 合法性（采样 1000 条，全部能被 StackVM 执行）；
   - 奖励计算与现有 GP 口径对齐（同一公式，RL 奖励的 mean_rank_ic 与 GP 的 fitness 一致）；
   - 训练 smoke（`batch_size=32`、`train_steps=50` 跑通，确认 loss 下降、best_score 更新、checkpoint 保存/加载、熵监控触发）；
   - 与现有 GP / LLM-GP 子 Tab 回归对照（确认 `miningSubTab='gp' / 'llm_gp'` 行为零变化）。

---

## 九、风险与注意

1. **训练耗时**：RL 训练是串行循环（每步采样→执行→评分→更新），A 股日线数据量下 2000 步 × 192 条公式的执行量较大。缓解：公式执行走本地 GPU 整树求值路径（可选）；默认参数已按 CPU 可训设计（模型小、公式短，AlphaMaster 实测 CPU 比 GPU 快）。
2. **奖励口径一致性**：奖励必须与现有评价体系一致（截面 RankIC），否则生成的因子与因子库/多因子页口径冲突。自检项 4 专门核对。
3. **过拟合风险**：RL 可能记住训练段高 IC 公式。缓解：Walk-Forward 折叠 + 验证段 OOS 门控 + 复杂度惩罚 + 测试段复核（与 GP 同套防过拟合体系）。
4. **词表变更**：词表（特征/算子集合）变更会使旧 checkpoint 失效。缓解：词表版本控制（5.1），版本不匹配拒绝加载。
5. **与 GP 主线互不影响**：不修改 `evolve()`、现有 GP / LLM-GP 子 Tab、`/mine_gp*` / `/mine_llm_gp*` 接口的任何行为（遵守"已完成功能不修改"原则）。
6. **依赖**：需要 torch（本系统已有，`factor_gpu_torch.py` 依赖）；不引入额外 RL 框架（gym/stable-baselines 等），REINFORCE 自实现（深度复刻 AlphaMaster，约 200 行核心逻辑）。
7. **AGPL-3.0 许可**：AlphaMaster 采用 AGPL-3.0。本方案深度复刻其算法架构与工程机制，若直接移植代码需注意许可合规（建议以"算法复刻 + 本地重写"方式实现，避免逐行复制）。

---

## 十、复用清单（实现时逐项核对）

**复用（不改代码）**：`split_train_test_dates` / `trim_panel_to_dates` / `oos_recheck` / `walk_forward_recheck` / `dedup_by_corr` / `SPACE_LEVELS` / `GP_FIELDS` / `WINDOW_POOL` / `evaluate_expression`（求值兜底/校验）/ `load_daily_kline` / `get_pool_stocks` / `get_active_stock_pool` / `calc_factor`（预计算基础因子特征）/ `factor_gpu_evaluator`（mean_rank_ic 奖励计算，可选）/ `upsert_factor` / `/mine_gp/stream` 的 SSE 线程与事件框架 / 前端图表组件与候选表展示。

**深度复刻（新增，按 AlphaMaster 实现）**：`lib/factor_rl/` 包（vocab / ops / features / vm / alphagpt / sampler / backtest / lord / trainer / checkpoint / island）+ `/mine_rl/stream` 接口 + `miningSubTab==='rl'` 子 Tab + 训练曲线/重启日志展示 + checkpoint 存储目录。

**明确不复用（语义不等价）**：AlphaMaster 的 MT5 数据管线（本系统用本地 PostgreSQL 数据源）；AlphaMaster 的组合回测奖励（本系统用截面 RankIC 系）；AlphaMaster 的 30 特征 / 66 算子词表（本系统从本地搜索空间派生，保证公式可被本地引擎求值、可被因子库消费）。