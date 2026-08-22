# -*- coding: utf-8 -*-
# LLM 增强 GP 引擎 (阶段6.2, 独立于 GP 主线的多岛进化引擎)
"""
来源: 东吴证券金工《AI因子挖掘的双路径实践与Skill沉淀》(2026-06)
核心四支柱 (本引擎忠实实现, 缺一不可):
  1. LLM 子表达式基因供给: LLM 从量价结构提取有金融逻辑的子表达式, 经三道闸验证后注册
  2. 分岛进化: 多岛屿独立做 选择/交叉/变异, 岛间周期性迁移精英 (环形拓扑)
  3. 周期性 LLM 注入: 每隔若干代用 LLM 生成新基因注入种群, 维持多样性
  4. 低相关筛选: 收尾 dedup_by_corr(corr_thresh=0.70)

设计约定:
  - 与 GP 主线 (lib/factor_gp.evolve) 互不影响: 只复用其 算子函数/适应度/去冗余,
    不复用其 单岛主循环 (多岛需独立种群/独立RNG/跨代迁移与注入挂点)。
  - LLM 基因以 "warm 个体" 形式注入种群 ({'t':'field','name':expr,'_warm':True}),
    与现有 warm_start_formulas 完全同机制 (原子表达式构件嵌入树), 不改动 factor_gp。
  - 独立大模型配置: 读 lib/factor_db.get_llm_config() (factor_llm_config 表),
    与 AI 助手 providers.yaml 完全隔离, 互不读取/互不覆盖。
"""

from __future__ import annotations

import json
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from lib.factor_gp import (
    SPACE_LEVELS, WINDOW_POOL, GP_FIELDS, GP_ARITH_BINARY, GP_ARITH_UNARY,
    GP_TS_OPS, GP_TS_RAW, GP_CS_OPS,
    random_tree, tree_to_str, copy_tree, crossover,
    subtree_mutation, hoist_mutation, point_mutation, expr_hash, tree_size,
    fitness_expr, _is_bare_field, dedup_by_corr, expr_length_penalty,
    formula_to_tree,                       # LLM 基因前缀转中缀后转树 (GPU 判定/编译)
    _pool_init, _pool_eval_expr,   # 个体并行进程池 worker (阶段3.3 同款, Windows spawn 可 pickle)
    _pool_eval_expr_new,           # 回退组新语义 worker (mean_rank_ic, 与 GPU 组同口径; 对齐 GP 主线 P1#8)
)
from lib.factor_engine import validate_expression, evaluate_expression

# 多进程并行 (复用 GP 主线 _pool_init/_pool_eval_expr; Windows spawn 下需模块级可 pickle 函数)
from concurrent.futures import ProcessPoolExecutor

# 基础字段别名 (prompt 中给出人类可读含义)
_FIELD_MEANING = {
    "Open": "开盘价", "High": "最高价", "Low": "最低价", "Close": "收盘价",
    "Volume": "成交量(手)", "Amount": "成交额(元)", "VWAP": "成交均价",
    "Turnover": "换手率", "IdioRet": "个股特质收益", "Value": "对数市值",
    "TotalRet": "累计收益",
}

# LLM 每次生成条数上限 (防止一次性生成过多, 与 genes_per_inject 解耦)
_GENE_BATCH_MAX = 30

# LLM 调用失败重试次数
_LLM_RETRY = 2


# ============================================================
# 一、独立大模型配置读取
# ============================================================

def load_llm_config() -> Dict[str, Any]:
    """读取 LLM 增强 GP 独立大模型配置 (factor_llm_config 表, 单行 id=1)

    未配置/缺模型或密钥时返回 {} (由调用方提示"请先配置大模型")。
    """
    try:
        from lib.factor_db import get_llm_config
        cfg = get_llm_config()
    except Exception:
        return {}
    if not cfg:
        return {}
    if not cfg.get("api_key") or not cfg.get("model"):
        return {}
    return cfg


# ============================================================
# 二、LLM 子表达式基因生成器 (四支柱 1)
# ============================================================

def _build_system_prompt() -> str:
    """构造 LLM 基因生成系统提示词 (算子白名单/语法/七类维度/JSON 输出要求)"""
    fields_desc = "; ".join(f"{f}: {_FIELD_MEANING.get(f, f)}" for f in GP_FIELDS)
    ts_ops = ", ".join(GP_TS_OPS + GP_TS_RAW)
    cs_ops = ", ".join(GP_CS_OPS)
    arith_ops = ", ".join(GP_ARITH_BINARY + GP_ARITH_UNARY)
    windows = ", ".join(str(w) for w in WINDOW_POOL)
    return (
        "你是一位量化因子研究专家, 任务是从股票的价量结构数据中, 设计有金融逻辑的因子子表达式。\n"
        f"可用基础字段(全部大写): {fields_desc}\n"
        f"可用单参带窗时序算子(需窗口参数, 窗口只能从 {{{windows}}} 中取): {ts_ops}\n"
        f"可用双参带窗时序算子(两个字段或子表达式+窗口, 窗口只能从 {{{windows}}} 中取): ts_Corr(字段A,字段B,窗口) 两序列滚动相关性\n"
        f"可用单参无窗时序算子: {GP_TS_RAW}\n"
        f"可用截面算子(横截面处理): {cs_ops}\n"
        f"可用算术算子: {arith_ops} (add=加, sub=减, mul=乘, div=除, abs=绝对值)\n"
        "表达式语法(参考示例):\n"
        "  ts_Mean(ts_PctChange(Close,1),10)    过去10日收益率均值(动量)\n"
        "  div(ts_Mean(Volume,5),ts_Mean(Volume,20))  量能变化(放量/缩量)\n"
        "  sub(Close,Open)                       实体大小\n"
        "  div(Close,ts_Max(High,20))            价格相对20日高位位置\n"
        "  ts_Stdev(ts_PctChange(Close,1),20)    波动率\n"
        "  div(sub(Close,ts_Delay(Close,20)),ts_Sum(abs(ts_Delta(Close,1)),20))  路径效率\n"
        "  ts_Corr(Close,Volume,20)              量价相关性\n"
        "要求:\n"
        "1. 每个子表达式必须包含至少一个时序或截面算子, 不能是裸字段或纯常数。\n"
        "2. 只使用上述字段与算子, 窗口只能来自给定窗口池。\n"
        "3. 表达式要符合金融逻辑(动量/反转/量能/K线形态/价格位置/波动率/路径效率/量价协同等), 简洁且稳健。\n"
        "4. 只输出 JSON, 格式: {\"genes\":[{\"category\":\"类别\",\"expr\":\"表达式\",\"logic\":\"金融逻辑说明\"}]}\n"
        "   category 取值限定: 动量/反转/量能/K线形态/价格位置/波动率/路径效率/量价协同。"
    )


def _build_user_prompt(k: int) -> str:
    """构造 LLM 基因生成用户提示词 (请求生成 k 条子表达式)"""
    return (
        f"请基于上述价量字段与算子, 生成 {k} 条有金融逻辑的因子子表达式。"
        "尽量覆盖不同的金融逻辑类别, 避免大量重复结构, 输出上述 JSON 格式。"
    )


def _llm_chat(system_prompt: str, user_prompt: str, cfg: Dict[str, Any]) -> str:
    """同步调用 LLM (openai 兼容模式, 独立配置), 失败重试; 最终失败返回空串

    不读取 AI 助手的 providers.yaml / agent 模块, 配置完全独立。
    """
    content = ""
    for _ in range(_LLM_RETRY + 1):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
            resp = client.chat.completions.create(
                model=cfg["model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=float(cfg.get("temperature", 0.7)),
                max_tokens=int(cfg.get("max_tokens", 2048)),
                response_format={"type": "json_object"},
            )
            content = (resp.choices[0].message.content or "").strip()
            if content:
                break
        except Exception:
            continue
    return content


def _parse_llm_output(text: str) -> List[Dict[str, str]]:
    """解析 LLM 返回 JSON (容错: 剥离 markdown 代码块/杂散文本)"""
    if not text:
        return []
    txt = text.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        # 去掉可能的 json 语言标记行
        lines = txt.splitlines()
        if lines and lines[0].lstrip().lower().startswith("json"):
            txt = "\n".join(lines[1:]).strip()
    try:
        obj = json.loads(txt)
    except Exception:
        # 截取第一个 { 到最后一个 } 再试
        s, e = txt.find("{"), txt.rfind("}")
        if s < 0 or e <= s:
            return []
        try:
            obj = json.loads(txt[s:e + 1])
        except Exception:
            return []
    if not isinstance(obj, dict):
        return []
    genes = obj.get("genes")
    if not isinstance(genes, list):
        return []
    out = []
    for g in genes:
        if isinstance(g, dict) and g.get("expr"):
            out.append({
                "category": str(g.get("category") or "其他")[:20],
                "expr": str(g["expr"]).strip(),
                "logic": str(g.get("logic") or "")[:200],
            })
    return out


# 算术前缀函数 -> 中缀运算符 (LLM 基因用前缀 add/sub/mul/div, GP 树 tree_to_str 用中缀)
_ARITH_PREFIX_SYMBOL = {"add": "+", "sub": "-", "mul": "*", "div": "/"}


def _split_top_level_comma(s: str) -> List[str]:
    """按顶层逗号切分 (忽略嵌套括号内的逗号, 如 ts_Mean(Volume,5) 的逗号)"""
    parts: List[str] = []
    depth = 0
    cur: List[str] = []
    for c in s:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    if cur:
        parts.append("".join(cur))
    return parts


def _to_infix_arith(expr: str) -> str:
    """LLM 基因算术前缀转中缀 (与 GP 树 tree_to_str 输出格式一致, 供 GPU 判定/编译)

    例: div(ts_Mean(Volume,5),ts_Mean(Volume,20)) -> (ts_Mean(Volume,5)/ts_Mean(Volume,20))
        add(sub(Close,Open),ts_Mean(Close,5))     -> ((Close-Open)+ts_Mean(Close,5))
    add/sub/mul/div 为二元前缀函数; abs/ts_*/cs_* 前缀本身与 tree_to_str 一致, 原样保留。
    随机树的中缀表达式不含 add(/div( 前缀, 原样返回, 不影响现有路径。
    """
    out: List[str] = []
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        matched = False
        for name, sym in _ARITH_PREFIX_SYMBOL.items():
            # 匹配二元前缀函数名 add( sub( mul( div(, 且前一字符不是标识符字符(避免误伤字段/算子名)
            if expr.startswith(name + "(", i) and (
                    i == 0 or not (expr[i - 1].isalnum() or expr[i - 1] == "_")):
                body_start = i + len(name) + 1
                depth = 1
                j = body_start
                while j < n and depth > 0:
                    if expr[j] == "(":
                        depth += 1
                    elif expr[j] == ")":
                        depth -= 1
                    j += 1
                body = expr[body_start:j - 1]
                parts = _split_top_level_comma(body)
                if len(parts) == 2:
                    out.append("(" + _to_infix_arith(parts[0].strip())
                               + sym + _to_infix_arith(parts[1].strip()) + ")")
                    i = j
                    matched = True
                    break
        if matched:
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _validate_gene(expr: str, panel: Dict[str, pd.DataFrame],
                   seen_hashes: set, max_length: int = 32) -> bool:
    """LLM 基因四道闸验证 (语法/节点数/求值/去重), 通过返回 True

    1. 语法闸: validate_expression 校验 DSL 合法
    2. 节点数闸: 解析统计 tree_size, 超过 max_length 拒绝 (对齐 GP 主线 P4, 防超长因子注入)
    3. 求值闸: evaluate_expression 求值非空且非空率 >= 5%
    4. 去重闸: 表达式哈希未在注册表出现
    """
    if not expr or len(expr) > 200:
        return False
    if _is_bare_field(expr):
        return False
    ok, _ = validate_expression(expr)
    if not ok:
        return False
    # 节点数闸: 解析失败或超限均拒绝 (字符串原子无法受 GP 结构树 max_depth 约束, 须入口把关)
    if max_length and max_length > 0:
        _ct = formula_to_tree(expr)
        if _ct is None or tree_size(_ct) > max_length:
            return False
    h = expr_hash(expr)
    if h in seen_hashes:
        return False
    try:
        fv = evaluate_expression(expr, panel)
    except Exception:
        return False
    if fv is None or len(fv) == 0 or fv.dropna(how="all").empty:
        return False
    if float(fv.notna().mean().mean()) < 0.05:
        return False
    seen_hashes.add(h)
    return True


def generate_llm_genes(panel: Dict[str, pd.DataFrame],
                       cfg: Dict[str, Any],
                       k: int,
                       seen_hashes: set,
                       max_length: int = 32) -> Tuple[List[Dict[str, Any]], int, int]:
    """生成一批 LLM 子表达式基因, 返回 (genes, accepted, rejected)

    genes: [{expr, category, logic}] 已通过四道闸; 每轮调用失败返回空列表。
    """
    k = max(1, min(int(k), _GENE_BATCH_MAX))
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(k)
    text = _llm_chat(system_prompt, user_prompt, cfg)
    items = _parse_llm_output(text)
    genes: List[Dict[str, Any]] = []
    accepted, rejected = 0, 0
    for it in items:
        expr = it["expr"]
        if _validate_gene(expr, panel, seen_hashes, max_length):
            genes.append({"expr": expr, "category": it["category"], "logic": it["logic"]})
            accepted += 1
        else:
            rejected += 1
    return genes, accepted, rejected


# ============================================================
# 三、分岛进化调度器 (四支柱 2) + 周期性 LLM 注入 (四支柱 3)
# ============================================================

class _Island:
    """单个岛屿: 独立种群 + 独立 RNG + 独立适应度缓存 + 独立最优/hall"""

    def __init__(self, idx: int, pop: List[Dict], rng: random.Random,
                 space: Dict[str, Any], max_depth: int, max_length: int = 32):
        self.idx = idx
        self.pop = pop
        self.rng = rng
        self.space = space
        self.max_depth = max_depth
        self.max_length = max_length
        self.cache: Dict[str, Tuple[Optional[float], Optional[Dict]]] = {}
        self.seen: set = set()          # 跨代见过的表达式哈希 (防重复)
        self.hall: Dict[str, Dict[str, Any]] = {}  # 跨代高适应度个体
        self.curve: List[Dict[str, Any]] = []
        self.best_overall: Tuple[Optional[float], Optional[str]] = (None, None)

    def eval_pop(self, panel: Dict[str, pd.DataFrame],
                 prices_panel: Dict[str, pd.DataFrame],
                 rebal_period: int, min_warmup: int,
                 ts_normalize_window: Optional[int],
                 marketcap_proxy_lookback: Optional[int],
                 parsimony: float) -> List[Tuple[Optional[float], Optional[Dict]]]:
        """评估本岛全部个体 (命中缓存直接复用; 未命中调用 fitness_expr)"""
        fit_list: List[Tuple[Optional[float], Optional[Dict]]] = []
        for ind in self.pop:
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            h = expr_hash(expr)
            pair = self.cache.get(h)
            if pair is None:
                pair = fitness_expr(
                    expr, panel, prices_panel, rebal_period, min_warmup,
                    ts_normalize_window, marketcap_proxy_lookback, parsimony)
                self.cache[h] = pair
            fit_list.append(pair)
        return fit_list

    def evolve_one_generation(self, fit_list: List[Tuple[Optional[float], Optional[Dict]]],
                              panel: Dict[str, pd.DataFrame],
                              prices_panel: Dict[str, pd.DataFrame],
                              population_size: int,
                              tournament_size: int,
                              p_crossover: float,
                              p_subtree_mutation: float,
                              p_hoist_mutation: float,
                              p_point_mutation: float) -> None:
        """推进本岛一代 (评估已由调用方完成): 记录曲线/最优/hall + 生成下一代

        东吴分岛进化不设"岛级早停" (各岛全程保持进化, 靠周期迁移/注入维持多样性),
        故无早停返回值。
        """
        rng = self.rng
        valid = sorted(
            [(i, f) for i, (f, _r) in enumerate(fit_list) if f is not None],
            key=lambda x: x[1], reverse=True)
        if not valid:
            return
        gen_best_fit = valid[0][1]
        gen_avg_fit = float(np.mean([f for _, f in valid]))

        # 更新本岛全局最优
        if self.best_overall[0] is None or gen_best_fit > self.best_overall[0]:
            bi = valid[0][0]
            ind = self.pop[bi]
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            self.best_overall = (gen_best_fit, expr)

        self.curve.append({
            "gen": len(self.curve) + 1,
            "best_fitness": round(float(gen_best_fit), 6),
            "avg_fitness": round(float(gen_avg_fit), 6),
            "best_expr": (self.best_overall[1] if self.best_overall[1] else ""),
        })

        # hall_of_fame: 每代 top 若干个体跨代收集 (收尾时取多样候选)
        for i, f in valid[:max(10, population_size // 4)]:
            ind = self.pop[i]
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            if _is_bare_field(expr):
                continue
            old = self.hall.get(expr)
            if old is None or f > old.get("fitness", -1e9):
                self.hall[expr] = {"expr": expr, "fitness": f,
                                   "result": fit_list[i][1] or {}}

        # 精英保留 + 锦标赛选择 + 交叉/变异
        elite_size = max(1, int(population_size * 0.1))
        elite_idx = [i for i, _ in valid[:elite_size]]
        new_pop: List[Dict] = [copy_tree(self.pop[i]) for i in elite_idx]

        def _select_fitness(idx: int) -> float:
            f = fit_list[idx][0]
            if f is None:
                return -1e9
            ind = self.pop[idx]
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            if _is_bare_field(expr):
                f = f * 0.3
            return f

        def _tournament() -> Dict:
            contenders = [rng.choice(valid) for _ in range(min(tournament_size, len(valid)))]
            best = max(contenders, key=lambda x: _select_fitness(x[0]))[0]
            return self.pop[best]

        while len(new_pop) < population_size:
            r = rng.random()
            if r < p_crossover:
                a, b = _tournament(), _tournament()
                child = crossover(rng, a, b, self.max_depth)
            elif r < p_crossover + p_subtree_mutation:
                a = _tournament()
                child = subtree_mutation(rng, a, self.max_depth, self.space)
            elif r < p_crossover + p_subtree_mutation + p_hoist_mutation:
                a = _tournament()
                child = hoist_mutation(rng, a, self.max_depth)
            elif r < p_crossover + p_subtree_mutation + p_hoist_mutation + p_point_mutation:
                a = _tournament()
                child = point_mutation(rng, a, self.space)
            else:
                # reproduction 直接复制
                a = _tournament()
                child = copy_tree(a)
            expr = child["name"] if child.get("_warm") else tree_to_str(child)
            h = expr_hash(expr)
            if h in self.seen and len(self.seen) > 16:
                child = point_mutation(rng, child, self.space)
                expr = child["name"] if child.get("_warm") else tree_to_str(child)
                h = expr_hash(expr)
            self.seen.add(h)
            # 阶段 P4: max_length 节点数上限 —— 超限回退复制父代 (对齐 QuantGplearn max_length)
            # 兼容 _warm 字符串个体: 解析其公式统计节点数, 解析失败视为 0 (跳过检查)。
            if self.max_length and self.max_length > 0:
                if child.get("_warm"):
                    _ct = formula_to_tree(child["name"])
                    _n = tree_size(_ct) if _ct is not None else 0
                else:
                    _n = tree_size(child)
                if _n > self.max_length:
                    child = copy_tree(a)
                    expr = child["name"] if child.get("_warm") else tree_to_str(child)
                    h = expr_hash(expr)
                    self.seen.add(h)
            new_pop.append(child)

        self.pop = new_pop

    def top_exprs(self, n: int) -> List[Tuple[str, float]]:
        """取本岛当前种群 Top-N (expr, fitness) (迁移/注入用)"""
        ranked = []
        for ind in self.pop:
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            fit = (self.cache.get(expr_hash(expr)) or (None, None))[0]
            if fit is not None:
                ranked.append((expr, fit))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:n]

    def bottom_exprs(self, n: int) -> List[Tuple[str, float]]:
        ranked = []
        for ind in self.pop:
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            fit = (self.cache.get(expr_hash(expr)) or (None, None))[0]
            if fit is not None:
                ranked.append((expr, fit))
        ranked.sort(key=lambda x: x[1])
        return ranked[:n]


def _init_island_pop(rng: random.Random, space: Dict[str, Any], max_depth: int,
                     size: int, warm_formulas: List[str],
                     warm_ratio: float = 0.3,
                     max_length: int = 32) -> List[Dict]:
    """初始化单岛种群: 库内公式 Warm-Start + 随机树 (与现有 evolve 同机制)"""
    pop: List[Dict] = []
    warm_count = int(size * warm_ratio)
    for s in list(warm_formulas)[:warm_count]:
        # 阶段 P4: 注入前按 max_length 过滤超限基因 (解析公式统计节点数)
        if max_length and max_length > 0:
            _ct = formula_to_tree(s)
            if _ct is not None and tree_size(_ct) > max_length:
                continue
        pop.append({"t": "field", "name": s, "_warm": True})
    while len(pop) < size:
        pop.append(random_tree(rng, max_depth, space))
    return pop


def _migrate(islands: List[_Island], topology: str, count: int) -> List[Dict[str, Any]]:
    """岛间迁移: 取源岛精英拷贝迁入目标岛, 替换目标岛低适应度个体 (种群规模恒定)

    topology: ring(i→i+1) / random(随机配对) / all_to_best(全部迁往当前最优岛)
    返回迁移事件列表 [{gen, from_island, to_island, count, exprs}]
    """
    n = len(islands)
    if n < 2 or count <= 0:
        return []
    events: List[Dict[str, Any]] = []
    if topology == "random":
        order = list(range(n))
        rng = random.Random(0)
        rng.shuffle(order)
        pairs = [(order[i], order[(i + 1) % n]) for i in range(n)]
    elif topology == "all_to_best":
        best_idx = max(range(n), key=lambda i: islands[i].best_overall[0] or -1e9)
        pairs = [(i, best_idx) for i in range(n) if i != best_idx]
    else:  # ring
        pairs = [(i, (i + 1) % n) for i in range(n)]
    for src_idx, dst_idx in pairs:
        src, dst = islands[src_idx], islands[dst_idx]
        migrants = src.top_exprs(count)
        if not migrants:
            continue
        # 目标岛最低适应度个体索引 (从 pop 中按缓存适应度找)
        bottom = dst.bottom_exprs(count)
        bottom_set = {expr for expr, _ in bottom}
        # 替换目标岛 pop 中的对应个体为迁移精英 (warm 个体: 表达式字符串)
        replaced = 0
        new_pop = []
        for ind in dst.pop:
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            if replaced < len(migrants) and expr in bottom_set:
                m_expr, m_fit = migrants[replaced]
                new_pop.append({"t": "field", "name": m_expr, "_warm": True})
                replaced += 1
            else:
                new_pop.append(ind)
        # 若替换不足 (bottom 集合匹配不完整), 补充替换
        for m_expr, _ in migrants[replaced:]:
            if not new_pop:
                break
            # 替换 pop 中一个非迁移来源的低适应度个体 (首个适应度最低者)
            worst_i = -1
            worst_f = None
            for i, ind in enumerate(new_pop):
                e = ind["name"] if ind.get("_warm") else tree_to_str(ind)
                f = (dst.cache.get(expr_hash(e)) or (None, None))[0]
                if f is None:
                    continue
                if worst_f is None or f < worst_f:
                    worst_f = f
                    worst_i = i
            if worst_i >= 0:
                new_pop[worst_i] = {"t": "field", "name": m_expr, "_warm": True}
        dst.pop = new_pop
        events.append({
            "from_island": src_idx, "to_island": dst_idx,
            "count": len(migrants),
            "exprs": [e for e, _ in migrants],
        })
    return events


def _inject_genes(islands: List[_Island], genes: List[Dict[str, Any]]) -> None:
    """周期 LLM 注入: 新基因以 warm 个体替换每岛低适应度个体"""
    if not genes:
        return
    for island in islands:
        bottom = island.bottom_exprs(len(genes))
        bottom_set = {expr for expr, _ in bottom}
        new_pop = []
        replaced = 0
        for ind in island.pop:
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            if replaced < len(genes) and expr in bottom_set:
                g = genes[replaced]
                new_pop.append({"t": "field", "name": g["expr"], "_warm": True})
                island.seen.add(expr_hash(g["expr"]))
                replaced += 1
            else:
                new_pop.append(ind)
        # 补充替换 (bottom 匹配不全时)
        for g in genes[replaced:]:
            worst_i, worst_f = -1, None
            for i, ind in enumerate(new_pop):
                e = ind["name"] if ind.get("_warm") else tree_to_str(ind)
                f = (island.cache.get(expr_hash(e)) or (None, None))[0]
                if f is None:
                    continue
                if worst_f is None or f < worst_f:
                    worst_f, worst_i = f, i
            if worst_i >= 0:
                new_pop[worst_i] = {"t": "field", "name": g["expr"], "_warm": True}
                island.seen.add(expr_hash(g["expr"]))
        island.pop = new_pop


# ============================================================
# 四、收尾筛选 (四支柱 4): 汇聚各岛候选 + 低相关筛选 + 去重
# ============================================================

def _finalize_candidates(islands: List[_Island], population_size: int,
                         corr_thresh: float,
                         panel: Dict[str, pd.DataFrame],
                         prices_panel: Dict[str, pd.DataFrame],
                         rebal_period: int, min_warmup: int,
                         ts_normalize_window: Optional[int],
                         filter_bare_fields: bool) -> Tuple[List[Dict], Dict[str, Any]]:
    """汇聚各岛 hall_of_fame + 末代 Top-N, 过滤裸字段/去重/低相关筛选 (<0.70)"""
    candidate_exprs: List[str] = []
    candidate_fit: Dict[str, float] = {}
    candidate_result: Dict[str, Dict] = {}
    for island in islands:
        hof_sorted = sorted(island.hall.values(), key=lambda x: x.get("fitness", 0), reverse=True)
        for h in hof_sorted:
            expr = h["expr"]
            if expr in candidate_fit:
                continue
            candidate_exprs.append(expr)
            candidate_fit[expr] = h["fitness"]
            candidate_result[expr] = h["result"] or {}
        # 末代 Top-N (补充 hall 未覆盖的最终代表现; 直接用本岛缓存, 避免重复评估)
        top_n = island.top_exprs(max(10, population_size // 2))
        for expr, f in top_n:
            if expr in candidate_fit:
                continue
            fit = f
            res = (island.cache.get(expr_hash(expr)) or (None, None))[1] or {}
            if fit is not None:
                candidate_exprs.append(expr)
                candidate_fit[expr] = fit
                candidate_result[expr] = res
    candidates = []
    for expr in candidate_exprs:
        candidates.append({
            "expr": expr,
            "fitness": round(float(candidate_fit[expr]), 6),
            "rank_ic_mean": candidate_result[expr].get("rank_ic_mean"),
            "rank_ic_ir": candidate_result[expr].get("rank_ic_ir"),
            "layered": candidate_result[expr].get("layered", {}),
            "samples": candidate_result[expr].get("samples"),
        })
    if filter_bare_fields:
        candidates = [c for c in candidates if not _is_bare_field(c["expr"])]
    seen_c = set()
    dedup = []
    for c in candidates:
        h = expr_hash(c["expr"])
        if h not in seen_c:
            seen_c.add(h)
            dedup.append(c)
    candidates = dedup
    dedup_report: Dict[str, Any] = {"enabled": False, "corr_thresh": None,
                                    "removed_n": 0, "removed": []}
    if corr_thresh and corr_thresh > 0 and len(candidates) >= 2:
        candidates, dedup_report = dedup_by_corr(
            candidates, panel, prices_panel,
            rebal_period=rebal_period, min_warmup=min_warmup,
            ts_normalize_window=ts_normalize_window,
            corr_thresh=corr_thresh,
        )
        dedup_report["enabled"] = True
    # 并行/GPU 求值产出的 result 为轻量 (仅 rank_ic_mean, 无 layered/ICIR), 收尾时对
    # 最终保留候选补算完整展示指标 (与纯 CPU 路径口径一致); 候选量少, 开销可接受。
    if candidates:
        for c in candidates:
            if c.get("layered") is not None:
                continue
            try:
                full = fitness_expr(
                    c["expr"], panel, prices_panel, rebal_period, min_warmup,
                    ts_normalize_window, marketcap_proxy_lookback, parsimony)
                if full is not None and full[1]:
                    c["rank_ic_mean"] = full[1].get("rank_ic_mean", c.get("rank_ic_mean"))
                    c["rank_ic_ir"] = full[1].get("rank_ic_ir")
                    c["layered"] = full[1].get("layered", {})
                    c["samples"] = full[1].get("samples")
            except Exception:
                pass
    return candidates, dedup_report


# ============================================================
# 五、多岛进化主入口
# ============================================================

def run_llm_gp_evolution(
    panel: Dict[str, pd.DataFrame],
    prices_panel: Dict[str, pd.DataFrame],
    n_islands: int = 4,
    island_pop_size: int = 60,
    generations: int = 40,
    max_depth: int = 4,
    rebal_period: int = 5,
    min_warmup: int = 60,
    ts_normalize_window: Optional[int] = None,
    marketcap_proxy_lookback: Optional[int] = None,
    parsimony: float = 0.001,
    max_length: int = 32,
    tournament_size: int = 5,
    p_crossover: float = 0.9,
    p_subtree_mutation: float = 0.02,
    p_hoist_mutation: float = 0.01,
    p_point_mutation: float = 0.02,
    migration_interval: int = 10,
    migrate_count: int = 6,
    migration_topology: str = "ring",
    inject_interval: int = 10,
    genes_per_inject: int = 12,
    max_inject_rounds: int = 3,
    gene_enabled: bool = True,
    space_level: str = "L0",
    random_state: int = 42,
    warm_start_formulas: Optional[List[str]] = None,
    corr_thresh: float = 0.70,
    filter_bare_fields: bool = True,
    llm_config: Optional[Dict[str, Any]] = None,
    use_gpu_tensor: bool = False,   # 树内向量化: GPU 整树张量求值 (需 CUDA 可用, 初始化失败自动回退 CPU)
    gpu_streams: int = 2,           # GPU 树间多流并发数 (阶段 P2#8 同步 LLM-GP): 1=退化为原串行, 默认 2
    n_jobs: int = 1,                # 个体并行: 并行评估进程数 (1=串行; >1 多进程加速, 复用 GP 主线 worker)
    island_parallel: bool = True,   # 岛间并行: 各岛未缓存个体合并为统一任务池一次并行评估 (默认开启)
    gene_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    migration_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """LLM 增强 GP 多岛进化 (训练段) — 独立引擎主入口

    四支柱完整实现: LLM 基因供给 / 分岛进化 / 周期 LLM 注入 / 低相关筛选(<0.70)。

    Returns:
        {
          "candidates", "dedup_report", "island_curves", "evolution_curve",
          "best", "best_fitness", "n_islands", "generations", "gene_rounds",
          "migration_events", "space_level",
        }
    """
    n_islands = max(1, int(n_islands))
    island_pop_size = max(10, int(island_pop_size))
    generations = max(1, int(generations))
    space = SPACE_LEVELS.get(str(space_level).upper(), SPACE_LEVELS["L0"])
    warm_formulas: List[str] = warm_start_formulas or []

    # ---- 树内向量化 (GPU 整树求值): 构建 GPU 求值上下文 ----
    # 与 GP 主线 use_gpu_tensor 同口径: 可 GPU 化的个体在主进程整树张量求值 (数据级并行,
    # 每个算子对整个 T×N 面板做 torch 矩阵运算), 不可 GPU 化的个体回退 CPU evaluate_expression;
    # 初始化失败自动回退纯 CPU, 不影响正确性。
    _gpu_ctx: Optional[Dict[str, Any]] = None
    _GPU_FIELDS = ["Open", "High", "Low", "Close", "Volume", "Amount", "VWAP",
                   "Turnover", "IdioRet", "Value", "TotalRet"]
    if use_gpu_tensor and island_parallel:
        try:
            from lib.factor_gpu_evaluator import (
                TensorPanel, PanelTensorCompiler, gpu_supported, mean_rank_ic,
            )
            import torch as _t
            # 数据真正上 GPU: 此前未传 device 面板建在 CPU 上 (与 GP 主线同问题, 修复);
            # CUDA 不可用时回退 CPU (与原行为一致)。
            _gpu_device = "cuda" if _t.cuda.is_available() else "cpu"
            _gpu_panel = TensorPanel.from_panel(panel, fields=_GPU_FIELDS, device=_gpu_device)
            _gpu_compiler = PanelTensorCompiler(_gpu_panel)
            _gpu_target = _gpu_panel.future_returns(rebal_period)
            _gpu_mask = _gpu_panel._global_mask(_gpu_panel.values)
            _gpu_mc = _gpu_panel.marketcap_proxy(marketcap_proxy_lookback) \
                if marketcap_proxy_lookback else None
            _gpu_ctx = {
                "compiler": _gpu_compiler, "target": _gpu_target,
                "mask": _gpu_mask, "mc_proxy": _gpu_mc,
                "dates": _gpu_panel.dates, "symbols": _gpu_panel.symbols,
                "gpu_supported": gpu_supported, "mean_rank_ic": mean_rank_ic,
            }
        except Exception:
            _gpu_ctx = None  # GPU 求值器初始化失败回退纯 CPU 路径

    # ---- 阶段 P2#7 同步: 编译函数复用缓存 (同表达式避免重复整树编译, 与 GP 主线同机制) ----
    _compile_cache: Dict[str, Any] = {}
    # 阶段 P1#8 同步: 回退组新语义上下文 (随 _pool_init 传入 worker, 供 _pool_eval_expr_new
    # 以 mean_rank_ic 与 GPU 组同口径求值, 保证同代所有个体适应度语义一致)
    _gpu_new_ctx: Optional[Dict[str, Any]] = None
    if use_gpu_tensor and _gpu_ctx is not None:
        _gpu_new_ctx = {
            "fields": _GPU_FIELDS,
            "dtype": str(_gpu_panel.values.dtype),   # float32 (CUDA 默认) 或 float64 (CPU)
            "rebal_period": rebal_period,
            "marketcap_proxy_lookback": marketcap_proxy_lookback,
            "neutralize_styles": False,   # LLM-GP 未启用风格中性化
            "style_cfg": None,
            "fitness_mode": "rank_ic",
        }

    # ---- 个体并行 (进程池, 复用 GP 主线 worker): n_jobs>1 时批量评估不可 GPU 化个体 ----
    # 岛间并行由 _eval_islands_parallel 的"跨岛统一任务池"实现: 所有岛的未缓存个体
    # 合并一次并行, 各岛评估互不阻塞。
    _executor: Optional[ProcessPoolExecutor] = None
    _use_parallel = False
    if island_parallel and n_jobs and n_jobs > 1:
        try:
            _executor = ProcessPoolExecutor(
                max_workers=int(n_jobs),
                initializer=_pool_init,
                initargs=(panel, prices_panel, rebal_period, min_warmup,
                          ts_normalize_window, marketcap_proxy_lookback, parsimony,
                          _gpu_new_ctx),   # 阶段 P1#8 同步: 回退组新语义上下文
            )
            _use_parallel = True
        except Exception:
            _executor = None
            _use_parallel = False  # 进程池创建失败回退串行

    # 独立 RNG (与 GP 主线互不影响; 各岛独立 RNG 保证岛屿间进化轨迹不同)
    base_rng = random.Random(random_state)
    islands: List[_Island] = []
    seen_hashes: set = set()
    for s in warm_formulas:
        seen_hashes.add(expr_hash(s))
    for i in range(n_islands):
        rng = random.Random(random_state + 1000 + i * 7919)
        pop = _init_island_pop(rng, space, max_depth, island_pop_size,
                                warm_formulas, max_length=max_length)
        islands.append(_Island(i, pop, rng, space, max_depth, max_length))

    gene_rounds: List[Dict[str, Any]] = []
    migration_events: List[Dict[str, Any]] = []
    inject_round = 0

    def _run_gene_round(round_idx: int, k: int, tag: str) -> int:
        """执行一轮 LLM 基因生成并注入各岛, 返回成功生成数 (LLM 失败不中断进化)"""
        nonlocal inject_round
        if not gene_enabled or not llm_config:
            return 0
        genes, accepted, rejected = generate_llm_genes(
            panel, llm_config, k, seen_hashes, max_length)
        _inject_genes(islands, genes)
        round_info = {"round": round_idx, "tag": tag, "k": k,
                      "accepted": accepted, "rejected": rejected,
                      "genes": [{"expr": g["expr"], "category": g["category"],
                                 "logic": g["logic"]} for g in genes]}
        gene_rounds.append(round_info)
        if gene_cb is not None:
            try:
                gene_cb(round_info)
            except Exception:
                pass
        inject_round += 1
        return len(genes)

    # 首轮 LLM 基因注入 (进化开始前, round 0)
    if gene_enabled and llm_config:
        _run_gene_round(0, genes_per_inject, "init")

    # ---- 并行评估 (三路并行): 树内向量化(GPU) + 个体并行(进程池) + 岛间并行(跨岛合并) ----
    def _eval_one_gpu(expr: str, tree: Optional[Dict]) -> Tuple[Optional[float], Optional[Dict]]:
        """GPU 整树求值: 可 GPU 化个体用编译器整树张量求值 (树内向量化),
        不可 GPU 化个体回退 CPU evaluate_expression; 返回 (fitness, 轻量 result)"""
        try:
            import torch as _t
            from lib.factor_engine import evaluate_expression
            ctx = _gpu_ctx
            # 阶段6.3 加速: GPU 求值无需梯度, 关闭 autograd 免构建计算图 (对齐 QuantGplearn no_grad)
            with _t.no_grad():
                if tree is not None and ctx["gpu_supported"](tree):
                    # 阶段 P2#7 同步: 复用已编译求值函数, 避免同一表达式重复整树编译 (对齐 GP 主线)
                    _h = expr_hash(expr)
                    f_compiled = _compile_cache.get(_h)
                    if f_compiled is None:
                        f_compiled = ctx["compiler"].compile(tree)
                        _compile_cache[_h] = f_compiled
                    f = f_compiled()
                else:
                    fv = evaluate_expression(expr, panel)
                    wide = fv.reindex(index=ctx["dates"], columns=ctx["symbols"])
                    f = _t.as_tensor(wide.to_numpy(dtype=np.float64),
                                     dtype=ctx["target"].dtype,
                                     device=ctx["target"].device)
                fit = ctx["mean_rank_ic"](f, ctx["target"], ctx["mask"],
                                          ctx["mc_proxy"], None, "rank_ic")
                if not np.isfinite(fit):
                    return None, None
                return (abs(fit) - expr_length_penalty(expr, parsimony),
                        {"expr": expr, "rank_ic_mean": float(fit)})
        except Exception:
            return None, None

    def _gpu_forward(expr: str, tree: Dict) -> Optional[Any]:
        """GPU 树间多流并发 (阶段 P2#8 同步 LLM-GP): 仅前向整树张量求值 (compile 缓存复用 + 闭包执行), 无同步

        返回 [T,N] 因子张量; 编译/求值失败返回 None。前向是纯张量运算 (无 .item()/numpy),
        可在指定 CUDA 流上异步执行, 使多棵树的 kernel 交错运行 (树间并行, 无需深度对齐/批量化)。
        """
        try:
            import torch as _t
            ctx = _gpu_ctx
            with _t.no_grad():
                _h = expr_hash(expr)
                f_compiled = _compile_cache.get(_h)
                if f_compiled is None:
                    f_compiled = ctx["compiler"].compile(tree)
                    _compile_cache[_h] = f_compiled
                return f_compiled()
        except Exception:
            return None

    def _gpu_fitness(expr: str, f: Optional[Any]) -> Tuple[Optional[float], Optional[Dict]]:
        """GPU 树间多流并发 (阶段 P2#8 同步 LLM-GP): 仅适应度 (mean_rank_ic + 惩罚), 含同步点

        前向已完成 (f 就绪张量); 此处为标量提取等同步点, 逐棵调用。f 为 None 时返回 (None, None)。
        """
        if f is None:
            return None, None
        try:
            import torch as _t
            ctx = _gpu_ctx
            with _t.no_grad():
                fit = ctx["mean_rank_ic"](f, ctx["target"], ctx["mask"],
                                          ctx["mc_proxy"], None, "rank_ic")
                if not np.isfinite(fit):
                    return None, None
                return (abs(fit) - expr_length_penalty(expr, parsimony),
                        {"expr": expr, "rank_ic_mean": float(fit)})
        except Exception:
            return None, None

    def _eval_islands_parallel(islands: List[_Island]) -> List[List[Tuple[Optional[float], Optional[Dict]]]]:
        """跨岛统一并行评估 (岛间并行: 各岛未缓存个体合并为统一任务池一次提交, 各岛评估互不阻塞)

        分派优先级:
          1. 个体并行: 不可 GPU 化个体先异步提交进程池 (新语义 worker _pool_eval_expr_new,
             与 GPU 组 mean_rank_ic 同口径), 与 GPU 组真并发执行 (对齐 GP 主线 P1#8)
          2. 树内向量化: 可 GPU 化个体在主进程整树张量求值 (GPU 数据级并行)
          3. 串行: 进程池不可用/中途失败时, GPU 开启按 mean_rank_ic 兜底、否则逐个体 fitness_expr
        结果写回各岛 fitness 缓存 (与 _Island.eval_pop 同缓存语义)。
        """
        nonlocal _use_parallel   # 进程池失败时置 False 回退串行 (改写外层闭包变量)
        fit_lists: List[List[Optional[Tuple[Optional[float], Optional[Dict]]]]] = [[] for _ in islands]
        todo: List[Tuple[int, int, str, Optional[Dict]]] = []   # (island_idx, pop_idx, expr, tree)
        for i, island in enumerate(islands):
            for idx, ind in enumerate(island.pop):
                expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
                h = expr_hash(expr)
                if h in island.cache:
                    fit_lists[i].append(island.cache[h])
                else:
                    fit_lists[i].append(None)
                    todo.append((i, idx, expr, None if ind.get("_warm") else ind))
        if not todo:
            return fit_lists
        # 分派: 可 GPU 化个体走主进程张量求值, 其余走进程池/串行
        # 随机树(tree!=None)直接用原树; LLM 基因(前缀 add/sub/mul/div)先转中缀再判 GPU
        gpu_todo: List[Tuple[int, str, Optional[Dict]]] = []
        cpu_todo: List[Tuple[int, str, Optional[Dict]]] = []
        for pos, (_i, _idx, expr, tree) in enumerate(todo):
            gpu_tree = tree
            if gpu_tree is None and _gpu_ctx is not None:
                gpu_tree = formula_to_tree(_to_infix_arith(expr))
            if _gpu_ctx is not None and gpu_tree is not None and _gpu_ctx["gpu_supported"](gpu_tree):
                gpu_todo.append((pos, expr, gpu_tree))
            else:
                cpu_todo.append((pos, expr, None))
        results: List[Optional[Tuple[Optional[float], Optional[Dict]]]] = [None] * len(todo)
        # 1) CPU 回退组先异步提交进程池 (新语义 worker, GPU 组执行期间进程池同时计算 = 真并发)
        pool_futures: Optional[Dict[int, Any]] = None
        if cpu_todo and _use_parallel and _executor is not None:
            try:
                pool_futures = {_pos: _executor.submit(_pool_eval_expr_new, expr)
                                for _pos, expr, _t in cpu_todo}
            except Exception:
                pool_futures = None
                _use_parallel = False   # 进程池中途失败: 回退主线程兜底
        # 2) GPU 树内向量化 (主进程整树张量求值; GPU 核执行与进程池回退组的 CPU 计算并发)
        # 阶段 P2#8 同步 (LLM-GP): 树间多流并发 (CUDA stream, 不 pad/不对齐深度; 多棵树 kernel 交错)。
        # 前向段批量异步提交到 gpu_streams 个流 (无同步, kernel 交错执行);
        # 适应度段逐棵取标量 (每棵 .item() 只等本流尾部, 其余流继续);
        # 分波 W=2*gpu_streams 限流, 控制整代 [T,N] 结果张量驻留显存上界 (与 GP 主线同口径)。
        if _gpu_panel.device.type == "cuda" and gpu_streams >= 2:
            import torch as _t
            streams = [_t.cuda.Stream() for _ in range(gpu_streams)]
            W = max(gpu_streams, min(2 * gpu_streams, len(gpu_todo)))
            for base in range(0, len(gpu_todo), W):
                seg = gpu_todo[base:base + W]
                fwd: List[Optional[Any]] = [None] * len(seg)
                # 阶段1: 本波所有树前向异步提交到各自流 (无同步, kernel 交错)
                for j, (pos, expr, tree) in enumerate(seg):
                    s = streams[j % gpu_streams]
                    with _t.cuda.stream(s):
                        fwd[j] = _gpu_forward(expr, tree)
                # 阶段2: 本波各树适应度 (逐棵 .item() 只等本流尾部, 其余流继续)
                for j, (pos, expr, tree) in enumerate(seg):
                    with _t.cuda.stream(streams[j % gpu_streams]):
                        results[pos] = _gpu_fitness(expr, fwd[j])
        else:
            # 原串行路径 (CPU 设备 / gpu_streams<2): 逐棵整树求值兜底
            for pos, expr, tree in gpu_todo:
                results[pos] = _eval_one_gpu(expr, tree)
        # 3) 收集回退组结果
        if pool_futures is not None:
            for _pos, expr, _t in cpu_todo:
                try:
                    results[_pos] = pool_futures[_pos].result()
                except Exception:
                    results[_pos] = (None, None)
        elif cpu_todo:
            if _gpu_ctx is not None:
                # GPU 开启但进程池不可用: 主线程按 GPU 同口径 (mean_rank_ic) 兜底, 保证语义一致
                for _pos, expr, _t in cpu_todo:
                    results[_pos] = _eval_one_gpu(expr, None)
            else:
                for _pos, expr, _t in cpu_todo:
                    results[_pos] = fitness_expr(
                        expr, panel, prices_panel, rebal_period, min_warmup,
                        ts_normalize_window, marketcap_proxy_lookback, parsimony)
        # 4) 写回各岛缓存与 fit_list
        for pos, (i, idx, expr, _t) in enumerate(todo):
            pair = results[pos]
            if pair is None:
                pair = (None, None)
            island = islands[i]
            island.cache[expr_hash(expr)] = pair
            fit_lists[i][idx] = pair
        return fit_lists

    # ---- 多岛进化主循环 ----
    for gen in range(generations):
        # 评估: 并行开启时跨岛统一并行评估 (岛间并行 + 个体并行 + 树内向量化),
        # 否则逐岛串行评估 (原逻辑, island.eval_pop)
        if _use_parallel or _gpu_ctx is not None:
            fit_lists = _eval_islands_parallel(islands)
        else:
            fit_lists = []
            for island in islands:
                fit_lists.append(island.eval_pop(
                    panel, prices_panel, rebal_period, min_warmup,
                    ts_normalize_window, marketcap_proxy_lookback, parsimony))
        for island, fit_list in zip(islands, fit_lists):
            island.evolve_one_generation(
                fit_list, panel, prices_panel, island_pop_size,
                tournament_size, p_crossover, p_subtree_mutation,
                p_hoist_mutation, p_point_mutation)
            if progress_cb is not None:
                try:
                    best_fit = island.curve[-1]["best_fitness"] if island.curve else None
                    avg_fit = island.curve[-1]["avg_fitness"] if island.curve else None
                    progress_cb({
                        "gen": gen + 1,
                        "generations": generations,
                        "island_idx": island.idx,
                        "n_islands": n_islands,
                        "best_fitness": best_fit,
                        "avg_fitness": avg_fit,
                        "best_expr": island.best_overall[1] or "",
                    })
                except Exception:
                    pass

        # 岛间迁移 (周期)
        if (gen + 1) % migration_interval == 0 and n_islands >= 2:
            events = _migrate(islands, migration_topology, migrate_count)
            for ev in events:
                ev = dict(ev)
                ev["gen"] = gen + 1
                ev["topology"] = migration_topology
                migration_events.append(ev)
                if migration_cb is not None:
                    try:
                        migration_cb(ev)
                    except Exception:
                        pass

        # 周期性 LLM 注入 (四支柱 3)
        if (gen + 1) % inject_interval == 0 and inject_round < max_inject_rounds:
            _run_gene_round(inject_round, genes_per_inject, "periodic")

    # 关闭进程池 (并行任务已全部完成)
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=False)

    # ---- 收尾: 汇聚各岛候选 + 低相关筛选 ----
    candidates, dedup_report = _finalize_candidates(
        islands, island_pop_size, corr_thresh, panel, prices_panel,
        rebal_period, min_warmup, ts_normalize_window, filter_bare_fields)

    island_curves = [i.curve for i in islands]
    # 全局综合曲线: 各岛同代 best 取最大值 / avg 取均值 (前端单线总览)
    n_curve = max((len(c) for c in island_curves), default=0)
    evolution_curve: List[Dict[str, Any]] = []
    for g in range(1, n_curve + 1):
        bests, avgs = [], []
        for c in island_curves:
            if len(c) >= g:
                bests.append(c[g - 1]["best_fitness"])
                avgs.append(c[g - 1]["avg_fitness"])
        evolution_curve.append({
            "gen": g,
            "best_fitness": round(float(max(bests)), 6) if bests else None,
            "avg_fitness": round(float(np.mean(avgs)), 6) if avgs else None,
        })

    best_expr, best_fitness = None, None
    for island in islands:
        if island.best_overall[0] is not None and (
                best_fitness is None or island.best_overall[0] > best_fitness):
            best_fitness = island.best_overall[0]
            best_expr = island.best_overall[1]

    return {
        "candidates": candidates,
        "dedup_report": dedup_report,
        "island_curves": island_curves,
        "evolution_curve": evolution_curve,
        "best": best_expr,
        "best_fitness": best_fitness,
        "n_islands": n_islands,
        "generations": len(evolution_curve),
        "gene_rounds": gene_rounds,
        "migration_events": migration_events,
        "space_level": space_level,
    }
