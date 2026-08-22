# GPU 树间多流并发实施方案

## 一、目标

把 GP 主线与 LLM 增强 GP 的 GPU 评估组从"**逐棵同步串行**"改为"**多棵树同时在 GPU 上运行**"。

约束（用户明确要求）：
- **不做 padding、不做深度对齐、不做算子合并/批量**。
- 每棵树仍是独立的单树张量程序（`[T,N]` 整面板求值），只是让多棵树的 kernel 在 GPU 上**交错执行**。
- 数值结果与改造前完全一致（仅调度交错，不改变任何张量运算）。

## 二、可行性论证：GPU 为什么支持"不 pad 的多树同时算"

GPU 的调度单元是 **kernel（每个节点一个 kernel）**，不是"整棵树"。

- 当前实现把一代所有可 GPU 树的 kernel **全部排在默认流（stream 0）**上，同流内 kernel 天然串行；
- 且每棵树在 `_eval_one_gpu` 内部"前向 + mean_rank_ic"结束后立即 `.item()` 同步，**下一棵树的前向 kernel 在上一棵完全收尾前根本没被提交**。

因此"只能串行"并非 GPU 的物理限制，而是"**默认流排队 + 逐棵同步**"这两点的结果。

**CUDA stream（多流）机制**：把不同树的 kernel 分别提交到不同流，GPU 调度器会交错执行——树 A 的第一个节点 kernel 结束后，树 B 的第一个 kernel 可立即顶上，直到 SM 被占满。这不需要 pad，因为不做算子合并；每棵树还是独立的 `[T,N]` 张量程序，只是排队进了不同的流。这正是"多棵树同时算、不用 pad"的可行路径，torch 原生支持：

```python
s = torch.cuda.Stream()
with torch.cuda.stream(s):
    f = compiled_tree()      # 该树所有 kernel 进入 stream s, 不立即同步
```

## 三、当前串行的三个点（需改造的根因）

1. **所有 kernel 落默认流**：`_eval_all` 里 GPU 组 `for ... _eval_one_gpu(...)` 逐棵执行，每棵树的 kernel 都在当前默认流排队（[factor_gp.py](../lib/factor_gp.py) 的闭包 `fn(sub[0](), sub[1]())` 未指定流）。
2. **fitness 是同步点**：`mean_rank_ic` 末尾 `float(out.item())`（[factor_gpu_evaluator.py](../lib/factor_gpu_evaluator.py#L567)）强制设备同步；`_eval_one_gpu` 把它和"前向求值"捆成一个原子调用，导致 Python 循环被 `.item()` 阻塞，下一棵树的前向无法提前提交。
3. **逐棵立即取标量**：`_eval_one_gpu` 返回 Python 标量适应度，主循环被迫逐棵等待。

## 四、方案：两阶段 + 分波多流

核心思路：把 `_eval_one_gpu` 拆成"**前向**（纯张量、开销最大、可异步）"与"**适应度**（含 `.item()` 同步点）"两段。前向段批量异步提交到 K 个流（无同步，kernel 交错）；适应度段逐棵取标量（每棵 `.item()` 只等自己流的尾部，其它流继续）。

**分波（wave）限流**：整代前向结果张量 `f` 全部驻留会爆显存（M 棵树 × `[T,N]` float32）。采用"波"调度：每波 W 棵树（W = 2×gpu_streams），波内前向并发、波内适应度收集，再进下一波。显存上界 = W 棵树的在飞中间张量。

### 4.1 factor_gp.py 改动

**(a) `evolve()` 新增参数**

```python
use_gpu_tensor: bool = False,
gpu_streams: int = 2,        # 新增: 树间多流并发数 (仅 CUDA + use_gpu_tensor 生效; 1=退化为原串行)
```

仅在 `_gpu_ctx is not None` 且面板设备为 cuda 时启用多流。

**(b) 拆分 `_eval_one_gpu` 为两段**

```python
def _gpu_forward(expr, tree) -> Optional[Tensor]:
    """仅前向: compile 缓存复用 + 闭包求值, 返回 [T,N] 张量; 无任何同步"""
    try:
        with _t.no_grad():
            h = expr_hash(expr)
            f_compiled = _compile_cache.get(h)
            if f_compiled is None:
                f_compiled = ctx["compiler"].compile(tree)
                _compile_cache[h] = f_compiled
            return f_compiled()
    except Exception:
        return None

def _gpu_fitness(expr, f: Optional[Tensor]) -> Tuple[Optional[float], Optional[Dict]]:
    """适应度: mean_rank_ic + 惩罚 + 行为描述子; 含同步点 (.item()/描述子取 numpy)"""
    if f is None:
        return None, None
    try:
        with _t.no_grad():
            fitness = ctx["mean_rank_ic"](f, ctx["target"], ctx["mask"],
                                          ctx["mc_proxy"], ctx.get("style_proxy"),
                                          _fitness_mode)
            if _pca_qd:
                try:
                    _behav_cache[expr_hash(expr)] = _factor_behavior_desc(f)
                except Exception:
                    pass
            if not np.isfinite(fitness):
                return None, None
            return (abs(fitness) - expr_length_penalty(expr, parsimony),
                    {"expr": expr, "rank_ic_mean": float(fitness)})
    except Exception:
        return None, None
```

> 注意：`_eval_one_gpu` 中 **fallback 分支**（`evaluate_expression` + reindex + 转张量）属于"前向"，也放进 `_gpu_forward`；但该分支天然含 `.cpu()/numpy` 同步，只走回退组（进程池/串行），不进多流并发组，不影响主收益。

**(c) `_eval_all` GPU 组改分波多流**

```python
if _gpu_ctx is not None and len(todo_exprs) >= 3:
    ... # 拆 gpu_idx/gpu_exprs/gpu_trees 与 fb_* (逻辑不变)
    # 回退组先异步提交进程池 (逻辑不变)
    ...
    # ---- GPU 组: 多流并发 (树间 kernel 交错, 不 pad 不对齐) ----
    if _gpu_cuda and gpu_streams >= 2:
        streams = [_t.cuda.Stream() for _ in range(gpu_streams)]
        W = max(gpu_streams, min(2 * gpu_streams, len(gpu_trees)))
        for base in range(0, len(gpu_trees), W):
            seg = list(zip(gpu_idx, gpu_exprs, gpu_trees))[base:base + W]
            fwd = [None] * len(seg)
            # 阶段1: 本波所有树前向异步提交到各自流 (无同步, kernel 交错)
            for j, (idx, expr, tree) in enumerate(seg):
                s = streams[j % gpu_streams]
                with _t.cuda.stream(s):
                    fwd[j] = _gpu_forward(expr, tree)
            # 阶段2: 本波各树适应度 (逐棵 .item() 只等本流尾部, 其余流继续)
            for j, (idx, expr, tree) in enumerate(seg):
                with _t.cuda.stream(streams[j % gpu_streams]):
                    pair = _gpu_fitness(expr, fwd[j])
                fitness_cache[expr_hash(expr)] = pair
                results[idx] = pair
    else:
        # 原串行路径 (gpu_streams=1 / CPU 设备 / 流创建失败): 逐棵 _eval_one_gpu 兜底
        for idx, expr, tree in zip(gpu_idx, gpu_exprs, gpu_trees):
            pair = _eval_one_gpu(expr, tree)
            fitness_cache[expr_hash(expr)] = pair
            results[idx] = pair
    ... # 收集回退组结果 (逻辑不变)
```

### 4.2 factor_llm_gp.py 改动

`_eval_islands_parallel` 的 GPU 组（[factor_llm_gp.py](../lib/factor_llm_gp.py#L905-L906)）按同样方式改造：
- 在 `evolve`（LLM-GP 版）增加 `gpu_streams: int = 2` 参数；
- 拆 `_gpu_forward`/`_gpu_fitness`（fitness_mode 固定 "rank_ic"）；
- GPU 组改分波多流；回退组进程池并发逻辑（已存在）保持不变。

### 4.3 路由接线（routes/factor.py）

- GP 主线调用点（[factor.py](../routes/factor.py#L934) `_run_evolve_once`）透传 `gpu_streams=gpu_streams`；
- LLM-GP 调用点（[factor.py](../routes/factor.py#L1504)）透传 `gpu_streams=gpu_streams`；
- 请求解析处从入参读取 `gpu_streams`（默认 2，范围 1~4，非法值钳制为 1~4）。

### 4.4 前端（可选增强）

按用户"设置放在当前页面"的偏好，在 GP 主线 / LLM-GP 页面参数区新增"GPU 并发流数"控件（默认 2，范围 1~4）。若不想动前端，后端默认值即可生效（不传则用 2）。

## 五、正确性保证

- **数值逐位不变**：流并发只改变 kernel 调度交错，不改变任何张量运算；每棵树独立、无共享可变状态，跨流无数据竞争。`gpu_streams=1` 时退化为原串行路径，应与改造前逐位一致。
- **缓存语义不变**：`fitness_cache` / `island.cache` 写入点、`_behav_cache` 写入点不变。
- **异常兜底不变**：compile/前向失败 → `fwd=None` → 该树 `(None, None)`，与原 `try/except` 语义一致；波内某树失败不影响其它树。
- **流创建失败兜底**：`torch.cuda.Stream()` 或设备非 cuda 时走原串行 `_eval_one_gpu` 路径。

## 六、验收/验证（Agu-2 环境）

- 用 `E:\anaconda\envs\Agu-2\python.exe` 执行。
- 同一 `random_state` 下对比三档：
  - `gpu_streams=1`（关流，退化为原串行）vs 改造前 baseline：`evolution_curve` / `candidates` / 候选因子逐位一致；
  - `gpu_streams=2` vs `gpu_streams=1`：`candidates` 完全一致（证明并发未改变结果）。
- 页面端到端跑一次 LLM-GP 与 GP 主线，确认进度输出正常、结果与改造前一致。
- 显存观测：分波 W 控制在 2×gpu_streams，确认峰值显存未爆。

## 七、实测结果（Agu-2 环境，RTX 3070 8GB，60 股 × 243 日，2026-08-19）

### 7.1 全链路 evolve 扫描（population=40, generations=3, 关进程池, 同一 random_state=42）

| gpu_streams | 耗时 | 代均 | 峰值alloc(实占) | 峰值resv(缓存池) | 候选数 | 与 gpu_streams=1 一致 | best |
|---|---|---|---|---|---|---|---|
| 1（原串行） | 20.22s | 0.85s | 12.0MB | 24MB | 11 | 基线 | 0.10299 |
| 2 | 18.64s | 0.73s | 12.2MB | 192MB | 11 | 完全一致 | 0.10299 |
| 4 | 18.59s | 0.72s | 12.4MB | 334MB | 11 | 完全一致 | 0.10299 |
| 8 | 18.73s | 0.75s | 12.8MB | 470MB | 11 | 完全一致 | 0.10299 |
| 16 | 18.83s | 0.73s | 13.7MB | 552MB | 11 | 完全一致 | 0.10299 |
| 32 | 18.60s | 0.73s | 13.7MB | 488MB | 11 | 完全一致 | 0.10299 |
| 64 | 18.52s | 0.72s | 13.7MB | 488MB | 11 | 完全一致 | 0.10299 |
| 128 | 18.63s | 0.75s | 13.7MB | 488MB | 11 | 完全一致 | 0.10299 |
| 256 | 18.57s | 0.73s | 13.7MB | 488MB | 11 | 完全一致 | 0.10299 |

> alloc = `torch.cuda.max_memory_allocated()`（张量实际占用，本面板极小）；resv = `torch.cuda.max_memory_reserved()`（缓存分配器预留池，随流数增多而预留更多空闲块，但非实际占用，且到 32 后即封顶不再增长）。结束后 `allocated/reserved` 均回落 0，无泄漏。

### 7.2 流创建上限探针（纯 `torch.cuda.Stream()` 创建）

| streams | 结果 |
|---|---|
| 512 / 1024 / 2048 / 4096 / 8192 | 全部创建成功，单次 <0.1s，alloc=resv=0MB（句柄仅占宿主内存，不占显存） |

即"能设多大"没有硬性失败点——8192 个流也能建，端到端 256 流结果仍与串行逐位一致。

### 7.3 结论

1. **正确性成立**：1~256 全档与串行候选逐位一致，多流不改变任何结果。
2. **显存不是限制**：张量实占仅 ~14MB；resv 缓存池最大 ~552MB（16 流）后封顶，8GB 卡上毫无压力。**"最大能设多少"的答案：没有显存上限，设多大都安全；但再大也无意义**。
3. **性能只在 2 流处有一次性收益（1.08x），再大即平台期（1.00x）**：20.2s→18.6s 来自"前向与适应度分段 + 提前批量提交"，2 流已吃满该收益；>2 流的 kernel 交错无排队可重叠——因 GPU 已接近满载（93.5%），纯属浪费（根因详见 7.4）。
4. **推荐取值：默认 2 即可；页面可调范围建议 1~4**（文档原建议），路由层已按 1~64 钳制兜底，超范围也不会出错。

### 7.4 若继续追求加速，真正瓶颈与下一步（2026-08-19 用 CUDA event 精测修正）

- **真正瓶颈是 GPU 计算本身（93.5%），不是 CPU**（修正此前"GPU 微秒级、CPU 是瓶颈"的推测）。
  实测（60 股 × 243 日 × 80 棵随机树，RTX 3070）：
  - GPU 纯 kernel 总执行 1417ms（17.7ms/棵），占墙钟 1515ms 的 **93.5%**；
  - CPU 侧全部开销（闭包调用 + launch 间隙 + 逐棵同步）仅 99ms（6.5%）；
  - 80 棵 `.item()` 同步合计 9.45ms（0.6%）——**item 完全不是瓶颈**（逐棵各等各的、互不依赖，但量太小）。
- **多流不加速的根因**：GPU 是固定吞吐流水线，多流交错只改变 kernel 排布、不改变总计算量；GPU 已接近满载（93.5%），无空闲可填，故 2~256 流全部 1.00x。只有多核 CPU 多进程是真并行（每核独立流水线，总吞吐随核数增长，即此前 GPU+2 进程池 2.08x 的来源）。
- **下一步（按性价比）**：
  a) **减少总计算量**：把一棵树内部同构小 kernel 合并成大 kernel / `torch.compile` 编译融合，减少 launch 次数与中间张量——直击 93.5% 大头；
  b) 缩面板（`max_samples` 降采样）或缩树规模；
  c) 换更强 GPU（算力翻倍直接翻倍）；
  d) 加 CPU 进程池核数（对"不可 GPU 化/回退组"个体仍有效）。
- 本次交付（GP 主线多流 + `gpu_streams` 参数）已正确落地、结果零扰动；默认值 2 即可，建议上限 4（再大无收益、纯浪费）。

## 八、遗留说明

- 本次仅改 GP 主线（factor_gp.py 多流实现 + routes/factor.py 路由透传 `gpu_streams`，默认 2、钳制 1~64）；LLM-GP（factor_llm_gp.py）按用户要求未改，待主线方案确认后再同步。
- 前端页面控件尚未接入（后端默认 2 已生效），如需页面可调再补。

