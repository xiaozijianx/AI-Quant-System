# -*- coding: utf-8 -*-
# 因子库数据库 CRUD 模块
"""
因子库页面持久化层:
    - factor_base:       因子基类表(指标类型 + 计算模板 + 是否需要周期)
    - factor_library:    具体因子表(基础因子实例 + 复合因子, 含 base_id/factor_type)
    - factor_metrics:    因子性能指标表

复用 lib/backtest_data.py 的 _db_config() 连接 PostgreSQL
"""

from __future__ import annotations
import os
from typing import Any, Dict, List, Optional
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor


def _db_config() -> dict:
    """读 .env 里的 PostgreSQL 配置"""
    return {
        "host":     os.environ.get("WUCAI_SQL_HOST", "localhost"),
        "user":     os.environ.get("WUCAI_SQL_USERNAME", "postgres"),
        "password": os.environ.get("WUCAI_SQL_PASSWORD", ""),
        "database": os.environ.get("WUCAI_SQL_DB", "AI-Quant"),
        "port":     int(os.environ.get("WUCAI_SQL_PORT", "5432")),
        "client_encoding": "UTF8",
    }


def _get_conn():
    """获取 PostgreSQL 连接"""
    return psycopg2.connect(**_db_config())


# ============================================================
# 建表
# ============================================================

def init_tables():
    """创建因子库相关表（幂等，已存在则跳过）"""
    ddl = """
    CREATE TABLE IF NOT EXISTS factor_library (
        id            SERIAL PRIMARY KEY,
        factor_id     VARCHAR(100) UNIQUE NOT NULL,
        name          VARCHAR(200) NOT NULL,
        category      VARCHAR(50) NOT NULL,
        sub_category  VARCHAR(50),
        direction     VARCHAR(10) DEFAULT 'neutral',
        formula       TEXT,
        description   TEXT,
        data_source   VARCHAR(50),
        period        VARCHAR(20),
        origin        VARCHAR(100),
        is_custom     BOOLEAN DEFAULT FALSE,
        is_active     BOOLEAN DEFAULT TRUE,
        created_at    TIMESTAMP DEFAULT NOW(),
        updated_at    TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS factor_metrics (
        id                SERIAL PRIMARY KEY,
        factor_id         VARCHAR(100) REFERENCES factor_library(factor_id) ON DELETE CASCADE,
        eval_date         DATE NOT NULL,
        ic_mean           FLOAT,
        ic_std            FLOAT,
        ir                FLOAT,
        rank_ic_mean      FLOAT,
        rank_ic_ir        FLOAT,
        ic_positive_ratio FLOAT,
        long_short_return FLOAT,
        sharpe            FLOAT,
        max_drawdown      FLOAT,
        turnover          FLOAT,
        eval_period       VARCHAR(40),
        updated_at        TIMESTAMP DEFAULT NOW(),
        UNIQUE(factor_id, eval_date, eval_period)
    );

    -- 历史遗留冗余表 factor_composite 已废弃: 无任何代码/前端调用,
    -- 自定义因子统一存 factor_library(is_custom=true)。这里幂等清理存量表,
    -- 避免因子初始化时残留旧表(不影响自定义因子, 自定义因子全在 factor_library)。
    DROP TABLE IF EXISTS factor_composite;

    -- 因子基类表: 定义指标类型 + 计算方式模板 + 是否需要周期
    --   type=periodic(需指定周期才生效) / fixed(本身即基础因子, 无周期参数)
    --   instance_type=composite(该基类的实例是复合因子) / basic(该基类的实例是基础因子)
    --   category: 基类分组(行情字段/技术指标/K线形态/财务/Barra风格/缠论/龙头/微观结构/派生字段),
    --             供因子构建页基础因子面板分类筛选 (2026-08-15 新增, 由 factor_init 回填)
    CREATE TABLE IF NOT EXISTS factor_base (
        base_id          VARCHAR(50) PRIMARY KEY,
        name             VARCHAR(200) NOT NULL,
        type             VARCHAR(20) NOT NULL DEFAULT 'fixed',
        instance_type    VARCHAR(20) DEFAULT 'composite',
        formula_template TEXT,
        description      TEXT,
        category         VARCHAR(50),
        is_active        BOOLEAN DEFAULT TRUE,
        created_at       TIMESTAMP DEFAULT NOW(),
        updated_at       TIMESTAMP DEFAULT NOW()
    );

    -- factor_library 增加: 基类关联 / 因子类型(basic/composite/custom)
    -- base_id 改为 TEXT 以支持逗号分隔的多个基类/源头因子ID(多因子组合)
    ALTER TABLE factor_library ADD COLUMN IF NOT EXISTS base_id TEXT;
    ALTER TABLE factor_library ALTER COLUMN base_id TYPE TEXT;
    -- 移除已废弃的 dependencies 字段 (依赖关系由公式中的基类实例自动推导)
    ALTER TABLE factor_library DROP COLUMN IF EXISTS dependencies;
    ALTER TABLE factor_library ADD COLUMN IF NOT EXISTS factor_type VARCHAR(20) DEFAULT 'basic';
    -- 评价方式标签 (2026-08-15 路由改造): technical/technical_ts/signal/financial/none
    -- 路由优先读此列, 为空时才回退公式规则推断; 由 factor_init 回填, 用户可在前端修改
    ALTER TABLE factor_library ADD COLUMN IF NOT EXISTS evaluation_type VARCHAR(20);
    -- 兼容旧表: 给 factor_base 补 instance_type / category 列
    ALTER TABLE factor_base ADD COLUMN IF NOT EXISTS instance_type VARCHAR(20) DEFAULT 'composite';
    ALTER TABLE factor_base ADD COLUMN IF NOT EXISTS category VARCHAR(50);

    CREATE INDEX IF NOT EXISTS idx_factor_library_category ON factor_library(category);
    CREATE INDEX IF NOT EXISTS idx_factor_metrics_factor ON factor_metrics(factor_id);
    CREATE INDEX IF NOT EXISTS idx_factor_library_type ON factor_library(factor_type);

    -- 因子评价完整结果表 (持久化单因子/多因子评价结果, 供前端切页后恢复)
    --   eval_key:  单因子=因子ID; 多因子=组合标识(如 sorted(ids) 用逗号连接)
    --   evaluation_type: 评价管线口径(technical/technical_ts/signal/financial),
    --                    同一因子用不同管线评价的结果互不覆盖 (2026-08-15 路由改造)
    --   params:    评价参数快照(JSON), 用于展示"上次评价配置"与"是否可复用"
    --   result:    完整评价结果快照(JSON), 含 IC/分层/PWC/净值等全部图表数据
    CREATE TABLE IF NOT EXISTS factor_eval_result (
        id          SERIAL PRIMARY KEY,
        eval_type   VARCHAR(20) NOT NULL,               -- single / multi
        eval_key    VARCHAR(500) NOT NULL,              -- 单因子=因子ID; 多因子=因子组合标识
        pool_type   VARCHAR(50),
        pool_ref    VARCHAR(200),
        start_date  VARCHAR(20),
        end_date    VARCHAR(20),
        method      VARCHAR(30),
        rebal_period INT,
        n_layers    INT,
        neutralize  VARCHAR(20),
        evaluation_type VARCHAR(20) DEFAULT 'technical',
        params      JSONB,
        result      JSONB,
        created_at  TIMESTAMP DEFAULT NOW(),
        updated_at  TIMESTAMP DEFAULT NOW(),
        UNIQUE(eval_type, eval_key, pool_type, start_date, end_date,
               method, neutralize, evaluation_type)
    );
    CREATE INDEX IF NOT EXISTS idx_factor_eval_result_key ON factor_eval_result(eval_type, eval_key);
    -- 幂等补列: 旧表可能缺 evaluation_type (存量行回填默认值 technical)
    ALTER TABLE factor_eval_result ADD COLUMN IF NOT EXISTS evaluation_type VARCHAR(20) DEFAULT 'technical';
    -- 幂等升级唯一约束: 旧约束(不含evaluation_type)删除后重建为新约束(含evaluation_type),
    -- 使同一因子用不同评价管线(如 technical 与 technical_ts)的结果可共存不互相覆盖
    DO $$
    DECLARE
        cname TEXT;
    BEGIN
        FOR cname IN
            SELECT conname FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'factor_eval_result'
              AND c.contype = 'u'
              AND pg_get_constraintdef(c.oid) LIKE '%neutralize%'
              AND pg_get_constraintdef(c.oid) NOT LIKE '%evaluation_type%'
        LOOP
            EXECUTE format('ALTER TABLE factor_eval_result DROP CONSTRAINT %I', cname);
        END LOOP;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'factor_eval_result'
              AND c.contype = 'u'
              AND pg_get_constraintdef(c.oid) LIKE '%evaluation_type%'
        ) THEN
            EXECUTE 'ALTER TABLE factor_eval_result ADD CONSTRAINT uq_factor_eval_result_v2 '
                    || 'UNIQUE (eval_type, eval_key, pool_type, start_date, end_date, '
                    || 'method, neutralize, evaluation_type)';
        END IF;
    END $$;

    -- 因子包表: 保存一份可复用的多因子选股配置(因子清单 + 合成方式 + 全部参数 + 权重/方向 + ML模型路径)
    --   factor_ids:     选中的因子ID列表(JSON数组)
    --   synth_cfg:      合成可配置参数(筛选/去冗余/方向/PCA/Optuna/ML), 完整JSON
    --   ml_params:      ML 超参(仅 ml_reg/ml_cls 使用)
    --   weights:        最终权重(线性方法); direction: 因子方向; ml_model_path: ML模型落盘路径
    --   result_snapshot: 当次评价结果快照(可选, 用于加载时回看历史)
    CREATE TABLE IF NOT EXISTS factor_package (
        id              SERIAL PRIMARY KEY,
        package_id      VARCHAR(100) UNIQUE NOT NULL,
        name            VARCHAR(200) NOT NULL,
        factor_ids      JSONB NOT NULL,
        method          VARCHAR(30) NOT NULL,
        synth_cfg       JSONB,
        ml_params       JSONB,
        pool_type       VARCHAR(50),
        pool_ref        VARCHAR(200),
        start_date      VARCHAR(20),
        end_date        VARCHAR(20),
        rebal_period    INT,
        n_layers        INT,
        top_n_list      JSONB,
        neutralize      VARCHAR(20),
        ts_normalize_window INT,
        weights         JSONB,
        direction       JSONB,
        ml_model_path   TEXT,
        pca_model_path  TEXT,
        result_snapshot JSONB,
        created_at      TIMESTAMP DEFAULT NOW(),
        updated_at      TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_factor_package_name ON factor_package(name);
    -- 幂等补列: 旧表可能缺 pca_model_path / portfolio_risk_snapshot / ts_normalize_window
    ALTER TABLE factor_package ADD COLUMN IF NOT EXISTS pca_model_path TEXT;
    ALTER TABLE factor_package ADD COLUMN IF NOT EXISTS portfolio_risk_snapshot JSONB;
    ALTER TABLE factor_package ADD COLUMN IF NOT EXISTS ts_normalize_window INT;

    -- LLM 增强 GP 独立大模型配置表 (阶段6.2, 与 AI 助手 providers.yaml 完全隔离)
    --   单行配置(id=1): api_key/base_url/model/temperature/max_tokens
    --   只被 LLM 增强 GP 引擎读写, 不触碰 AI 助手的 provider 配置, 避免互相干扰
    CREATE TABLE IF NOT EXISTS factor_llm_config (
        id          SERIAL PRIMARY KEY,
        api_key     TEXT NOT NULL,
        base_url    TEXT NOT NULL DEFAULT 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        model       VARCHAR(100) NOT NULL,
        temperature FLOAT DEFAULT 0.7,
        max_tokens  INT DEFAULT 2048,
        updated_at  TIMESTAMP DEFAULT NOW()
    );
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(ddl)
        conn.commit()
    finally:
        conn.close()


# ============================================================
# LLM 增强 GP 独立大模型配置 (阶段6.2)
# 只被 lib/factor_llm_gp.py 读写, 与 AI 助手 provider 配置完全隔离
# ============================================================

def get_llm_config() -> Dict[str, Any]:
    """读取 LLM 增强 GP 独立大模型配置 (单行 id=1; 未配置时返回空 dict)"""
    sql = "SELECT api_key, base_url, model, temperature, max_tokens FROM factor_llm_config WHERE id = 1"
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql)
        row = cur.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def save_llm_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """保存 LLM 增强 GP 独立大模型配置 (UPSERT 单行 id=1)

    api_key 传空串/掩码值时保留库内原值 (便于只改模型不动密钥)。
    """
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # 取当前密钥 (掩码/空值时保留)
        cur.execute("SELECT api_key, base_url, model, temperature, max_tokens FROM factor_llm_config WHERE id = 1")
        cur_row = cur.fetchone()
        old = dict(cur_row) if cur_row else {}
        api_key = str(cfg.get("api_key") or "").strip()
        if not api_key or "****" in api_key:
            api_key = old.get("api_key") or api_key  # 掩码/空 → 保留原密钥
        base_url = str(cfg.get("base_url") or old.get("base_url") or
                       "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
        model = str(cfg.get("model") or old.get("model") or "").strip()
        temperature = float(cfg.get("temperature", old.get("temperature", 0.7)))
        max_tokens = int(cfg.get("max_tokens", old.get("max_tokens", 2048)))
        cur.execute(
            """
            INSERT INTO factor_llm_config (id, api_key, base_url, model, temperature, max_tokens, updated_at)
            VALUES (1, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                api_key = EXCLUDED.api_key,
                base_url = EXCLUDED.base_url,
                model = EXCLUDED.model,
                temperature = EXCLUDED.temperature,
                max_tokens = EXCLUDED.max_tokens,
                updated_at = NOW()
            """,
            (api_key, base_url, model, temperature, max_tokens),
        )
        conn.commit()
        return {"api_key": _mask_key(api_key), "base_url": base_url, "model": model,
                "temperature": temperature, "max_tokens": max_tokens}
    finally:
        conn.close()


def _mask_key(api_key: str) -> str:
    """api_key 掩码: 仅保留尾 4 位 (避免前端明文常驻)"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****" + api_key[-4:]
    return api_key[:4] + "****" + api_key[-4:]


# ============================================================
# 因子库 CRUD
# ============================================================

def list_factors(category: Optional[str] = None,
                 is_custom: Optional[bool] = None,
                 search: Optional[str] = None) -> List[Dict[str, Any]]:
    """查询因子列表，支持按类别/自定义/搜索筛选"""
    sql = """
        SELECT l.factor_id, l.name, l.category, l.sub_category, l.direction,
               l.formula, l.data_source, l.period, l.origin, l.is_custom,
               l.base_id, l.factor_type, l.evaluation_type,
               -- 基类类型: 单一base_id时取factor_base.type, 多基类(逗号分隔)时为NULL
               CASE WHEN l.base_id IS NULL OR l.base_id = '' OR position(',' in l.base_id) > 0
                    THEN NULL ELSE b.type END AS base_type,
               -- 基类名: 解析逗号分隔的base_id, 逐个从factor_base和factor_library中查找名称
               COALESCE(
                   (SELECT string_agg(COALESCE(b2.name, l2.name, t.bid), ', ' ORDER BY t.ord)
                    FROM unnest(string_to_array(l.base_id, ',')) WITH ORDINALITY AS t(bid, ord)
                    LEFT JOIN factor_base b2 ON b2.base_id = trim(t.bid)
                    LEFT JOIN factor_library l2 ON l2.factor_id = trim(t.bid)
                   ),
                   l.name
               ) AS base_name,
               l.created_at, l.updated_at,
               m.ic_mean, m.ir, m.rank_ic_mean, m.long_short_return,
               m.sharpe, m.max_drawdown
        FROM factor_library l
        LEFT JOIN factor_base b ON b.base_id = l.base_id
        LEFT JOIN LATERAL (
            SELECT * FROM factor_metrics m2
            WHERE m2.factor_id = l.factor_id
            ORDER BY m2.eval_date DESC LIMIT 1
        ) m ON true
        WHERE l.is_active = true
    """
    params: list = []
    if category:
        sql += " AND l.category = %s"
        params.append(category)
    if is_custom is not None:
        sql += " AND l.is_custom = %s"
        params.append(is_custom)
    if search:
        sql += " AND (l.factor_id ILIKE %s OR l.name ILIKE %s OR l.formula ILIKE %s)"
        params.extend([f"%{search}%"] * 3)
    sql += " ORDER BY l.category, l.factor_id"

    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_factor(factor_id: str) -> Optional[Dict[str, Any]]:
    """查询单个因子详情"""
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM factor_library WHERE factor_id = %s", (factor_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_factor(factor: Dict[str, Any]) -> str:
    """插入或更新因子（按 factor_id 去重）

    evaluation_type 仅在 INSERT 时写入; ON CONFLICT 更新不覆盖该列,
    以保护用户在前端手工设置的评价方式标签(factor_init 重跑 upsert 不冲掉手工值)。
    需要强制改标签请用 update_evaluation_type。
    """
    sql = """
        INSERT INTO factor_library
            (factor_id, name, category, sub_category, direction, formula,
             description, data_source, period, origin, is_custom,
             base_id, factor_type, evaluation_type, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (factor_id) DO UPDATE SET
            name = EXCLUDED.name,
            category = EXCLUDED.category,
            sub_category = EXCLUDED.sub_category,
            direction = EXCLUDED.direction,
            formula = EXCLUDED.formula,
            description = EXCLUDED.description,
            data_source = EXCLUDED.data_source,
            period = EXCLUDED.period,
            origin = EXCLUDED.origin,
            is_custom = EXCLUDED.is_custom,
            base_id = EXCLUDED.base_id,
            factor_type = EXCLUDED.factor_type,
            -- 软删除修复: 用户覆盖保存(is_custom=true, 构建页/自定义保存)视为"重新生成",
            -- 自动重新激活(is_active=true); 而 factor_init 批量重灌(is_custom=false)
            -- 不重置 is_active, 避免把用户已删除的因子在重初始化时复活。
            is_active = CASE WHEN EXCLUDED.is_custom THEN TRUE ELSE factor_library.is_active END,
            updated_at = NOW()
        RETURNING factor_id
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (
            factor["factor_id"], factor["name"], factor.get("category", ""),
            factor.get("sub_category"), factor.get("direction", "neutral"),
            factor.get("formula", ""), factor.get("description", ""),
            factor.get("data_source", ""), factor.get("period", ""),
            factor.get("origin", ""), factor.get("is_custom", False),
            factor.get("base_id"), factor.get("factor_type", "basic"),
            factor.get("evaluation_type"),
        ))
        conn.commit()
        return cur.fetchone()[0]
    finally:
        conn.close()


def update_evaluation_type(factor_id: str, evaluation_type: Optional[str]) -> bool:
    """显式更新因子的评价方式标签 (供前端手工修改; None 表示清除回退自动推断)"""
    valid = {"technical", "technical_ts", "signal", "financial", "none", None}
    if evaluation_type not in valid:
        raise ValueError(f"非法 evaluation_type: {evaluation_type}, 可选 {valid}")
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE factor_library SET evaluation_type = %s, updated_at = NOW() WHERE factor_id = %s",
            (evaluation_type, factor_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_factor(factor_id: str) -> bool:
    """软删除因子"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE factor_library SET is_active = false, updated_at = NOW() WHERE factor_id = %s",
                     (factor_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def hard_delete_factor(factor_id: str) -> bool:
    """硬删除因子 (连同 factor_metrics 级联删除; 用于废弃因子彻底清理)

    注意: factor_eval_result 的 eval_key 为文本, 历史评价快照不会级联删除(成为孤儿, 无害)。
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM factor_library WHERE factor_id = %s", (factor_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ============================================================
# 因子基类 CRUD
# ============================================================

def list_bases() -> List[Dict[str, Any]]:
    """查询所有因子基类"""
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT b.*, COUNT(l.factor_id) AS instance_count
            FROM factor_base b
            LEFT JOIN factor_library l
                ON l.is_active = true
               AND l.base_id IS NOT NULL
               AND (
                   l.base_id = b.base_id
                   OR b.base_id = ANY(string_to_array(l.base_id, ','))
               )
            WHERE b.is_active = true
            GROUP BY b.base_id
            ORDER BY b.type, b.base_id
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_base(base_id: str) -> Optional[Dict[str, Any]]:
    """查询单个因子基类"""
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM factor_base WHERE base_id = %s", (base_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_base(base: Dict[str, Any]) -> str:
    """插入或更新因子基类（按 base_id 去重, 含 category 分组）"""
    sql = """
        INSERT INTO factor_base (base_id, name, type, instance_type, formula_template, description, category, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (base_id) DO UPDATE SET
            name = EXCLUDED.name,
            type = EXCLUDED.type,
            instance_type = EXCLUDED.instance_type,
            formula_template = EXCLUDED.formula_template,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            updated_at = NOW()
        RETURNING base_id
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (
            base["base_id"], base["name"], base.get("type", "fixed"),
            base.get("instance_type", "composite"),
            base.get("formula_template"), base.get("description", ""),
            base.get("category"),
        ))
        conn.commit()
        return cur.fetchone()[0]
    finally:
        conn.close()


# ============================================================
# 因子性能指标 CRUD
# ============================================================

def save_metrics(factor_id: str, metrics: Dict[str, Any]):
    """保存因子性能指标"""
    sql = """
        INSERT INTO factor_metrics
            (factor_id, eval_date, ic_mean, ic_std, ir, rank_ic_mean, rank_ic_ir,
             ic_positive_ratio, long_short_return, sharpe, max_drawdown, turnover,
             eval_period, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (factor_id, eval_date, eval_period) DO UPDATE SET
            ic_mean = EXCLUDED.ic_mean,
            ic_std = EXCLUDED.ic_std,
            ir = EXCLUDED.ir,
            rank_ic_mean = EXCLUDED.rank_ic_mean,
            rank_ic_ir = EXCLUDED.rank_ic_ir,
            ic_positive_ratio = EXCLUDED.ic_positive_ratio,
            long_short_return = EXCLUDED.long_short_return,
            sharpe = EXCLUDED.sharpe,
            max_drawdown = EXCLUDED.max_drawdown,
            turnover = EXCLUDED.turnover,
            updated_at = NOW()
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (
            factor_id, metrics.get("eval_date", datetime.now().date()),
            metrics.get("ic_mean"), metrics.get("ic_std"),
            metrics.get("ir"), metrics.get("rank_ic_mean"),
            metrics.get("rank_ic_ir"), metrics.get("ic_positive_ratio"),
            metrics.get("long_short_return"), metrics.get("sharpe"),
            metrics.get("max_drawdown"), metrics.get("turnover"),
            metrics.get("eval_period", ""),
        ))
        conn.commit()
    finally:
        conn.close()


def get_metrics_history(factor_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    """查询因子性能历史"""
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT * FROM factor_metrics
            WHERE factor_id = %s
            ORDER BY eval_date DESC LIMIT %s
        """, (factor_id, limit))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ============================================================
# 评价完整结果持久化 (供前端切页后恢复)
# ============================================================

def save_eval_result(eval_type: str, eval_key: str, result: Dict[str, Any],
                     params: Optional[Dict[str, Any]] = None) -> bool:
    """保存评价完整结果 (单因子/多因子), 按 (type,key,配置,评价管线) 去重覆盖

    参数:
        eval_type:  "single" / "multi"
        eval_key:   单因子=因子ID; 多因子=因子组合标识
        result:     完整评价结果快照 (JSON可序列化)
        params:     评价参数快照 (pool_type/日期/周期/方法/中性化/evaluation_type等);
                    evaluation_type 为评价管线口径, 同一因子不同管线结果互不覆盖
    """
    params = params or {}
    sql = """
        INSERT INTO factor_eval_result
            (eval_type, eval_key, pool_type, pool_ref, start_date, end_date,
             method, rebal_period, n_layers, neutralize, evaluation_type,
             params, result, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (eval_type, eval_key, pool_type, start_date, end_date,
                     method, neutralize, evaluation_type) DO UPDATE SET
            pool_ref = EXCLUDED.pool_ref,
            rebal_period = EXCLUDED.rebal_period,
            n_layers = EXCLUDED.n_layers,
            params = EXCLUDED.params,
            result = EXCLUDED.result,
            updated_at = NOW()
    """
    import json
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (
            eval_type, eval_key,
            (params.get("pool_type") or "active")[:50],
            (params.get("pool_ref") or "")[:200],
            (params.get("start_date") or "")[:20],
            (params.get("end_date") or "")[:20],
            (params.get("method") or "")[:30],
            int(params.get("rebal_period") or 0),
            int(params.get("n_layers") or 0),
            (params.get("neutralize") or "none")[:20],
            (params.get("evaluation_type") or "technical")[:20],
            json.dumps(params, ensure_ascii=False, default=str),
            json.dumps(result, ensure_ascii=False, default=str),
        ))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_eval_result(eval_type: str, eval_key: str,
                    params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """查询指定类型/因子的最近评价结果 (优先匹配同配置, 否则返回任意最新一条)

    参数:
        eval_type:  "single" / "multi"
        eval_key:   因子ID 或 组合标识
        params:     若提供, 优先返回与该参数匹配(同股票池/日期/周期)的结果
    返回: {params, result, created_at} 或 None
    """
    params = params or {}
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # 1) 优先按同配置精确匹配 (含评价管线口径; 未传时默认technical, miss则走兜底)
        if params.get("pool_type") or params.get("start_date") or params.get("method"):
            cur.execute("""
                SELECT params, result, created_at
                FROM factor_eval_result
                WHERE eval_type = %s AND eval_key = %s
                  AND pool_type = %s AND start_date = %s AND end_date = %s
                  AND method = %s AND neutralize = %s
                  AND evaluation_type = %s
                ORDER BY updated_at DESC LIMIT 1
            """, (
                eval_type, eval_key,
                (params.get("pool_type") or "active")[:50],
                (params.get("start_date") or "")[:20],
                (params.get("end_date") or "")[:20],
                (params.get("method") or "")[:30],
                (params.get("neutralize") or "none")[:20],
                (params.get("evaluation_type") or "technical")[:20],
            ))
            row = cur.fetchone()
            if row:
                return {"params": row["params"], "result": row["result"],
                        "created_at": row["created_at"]}
        # 2) 否则返回该因子最近任意一条
        cur.execute("""
            SELECT params, result, created_at
            FROM factor_eval_result
            WHERE eval_type = %s AND eval_key = %s
            ORDER BY updated_at DESC LIMIT 1
        """, (eval_type, eval_key))
        row = cur.fetchone()
        if not row:
            return None
        return {"params": row["params"], "result": row["result"],
                "created_at": row["created_at"]}
    finally:
        conn.close()


# ============================================================
# 分类列表
# ============================================================

def list_categories() -> List[str]:
    """获取所有因子分类"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT category FROM factor_library WHERE is_active = true ORDER BY category")
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


# ============================================================
# 因子包 CRUD (可复用的多因子选股配置)
# ============================================================

def save_factor_package(pkg: Dict[str, Any]) -> str:
    """保存因子包 (按 package_id 去重覆盖)

    参数:
        pkg: {
            package_id, name, factor_ids(list), method,
            synth_cfg(dict), ml_params(dict),
            pool_type, pool_ref, start_date, end_date,
            rebal_period, n_layers, top_n_list(list), neutralize,
            weights(dict), direction(dict), ml_model_path(str),
            result_snapshot(dict, 可选),
            portfolio_risk_snapshot(dict, 可选),  # F3 组合风险快照
        }
    返回: package_id
    """
    import json
    sql = """
        INSERT INTO factor_package
            (package_id, name, factor_ids, method, synth_cfg, ml_params,
             pool_type, pool_ref, start_date, end_date, rebal_period, n_layers,
             top_n_list, neutralize, ts_normalize_window, weights, direction,
             ml_model_path, pca_model_path, result_snapshot,
             portfolio_risk_snapshot, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (package_id) DO UPDATE SET
            name = EXCLUDED.name,
            factor_ids = EXCLUDED.factor_ids,
            method = EXCLUDED.method,
            synth_cfg = EXCLUDED.synth_cfg,
            ml_params = EXCLUDED.ml_params,
            pool_type = EXCLUDED.pool_type,
            pool_ref = EXCLUDED.pool_ref,
            start_date = EXCLUDED.start_date,
            end_date = EXCLUDED.end_date,
            rebal_period = EXCLUDED.rebal_period,
            n_layers = EXCLUDED.n_layers,
            top_n_list = EXCLUDED.top_n_list,
            neutralize = EXCLUDED.neutralize,
            ts_normalize_window = EXCLUDED.ts_normalize_window,
            weights = EXCLUDED.weights,
            direction = EXCLUDED.direction,
            ml_model_path = EXCLUDED.ml_model_path,
            pca_model_path = EXCLUDED.pca_model_path,
            result_snapshot = EXCLUDED.result_snapshot,
            portfolio_risk_snapshot = EXCLUDED.portfolio_risk_snapshot,
            updated_at = NOW()
        RETURNING package_id
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (
            pkg.get("package_id") or "",
            pkg.get("name") or "未命名因子包",
            json.dumps(pkg.get("factor_ids") or [], ensure_ascii=False, default=str),
            (pkg.get("method") or "equal")[:30],
            json.dumps(pkg.get("synth_cfg") or {}, ensure_ascii=False, default=str),
            json.dumps(pkg.get("ml_params") or {}, ensure_ascii=False, default=str),
            (pkg.get("pool_type") or "active")[:50],
            (pkg.get("pool_ref") or "")[:200],
            (pkg.get("start_date") or "")[:20],
            (pkg.get("end_date") or "")[:20],
            int(pkg.get("rebal_period") or 0),
            int(pkg.get("n_layers") or 0),
            json.dumps(pkg.get("top_n_list") or [], ensure_ascii=False, default=str),
            (pkg.get("neutralize") or "none")[:20],
            int(pkg.get("ts_normalize_window") or 0),
            json.dumps(pkg.get("weights") or {}, ensure_ascii=False, default=str),
            json.dumps(pkg.get("direction") or {}, ensure_ascii=False, default=str),
            pkg.get("ml_model_path") or "",
            pkg.get("pca_model_path") or "",
            json.dumps(pkg.get("result_snapshot") or {}, ensure_ascii=False, default=str),
            json.dumps(pkg.get("portfolio_risk_snapshot") or {}, ensure_ascii=False, default=str),
        ))
        conn.commit()
        return cur.fetchone()[0]
    finally:
        conn.close()


def list_factor_packages() -> List[Dict[str, Any]]:
    """列出所有因子包 (列表页用, 返回精简字段 + 完整配置)"""
    import json
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT * FROM factor_package ORDER BY updated_at DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            for key in ("factor_ids", "synth_cfg", "ml_params", "top_n_list",
                        "weights", "direction", "result_snapshot"):
                if r.get(key):
                    try:
                        r[key] = json.loads(r[key])
                    except Exception:
                        pass
        return rows
    finally:
        conn.close()


def get_factor_package(package_id: str) -> Optional[Dict[str, Any]]:
    """查询单个因子包 (含全部配置, JSON 字段反序列化)"""
    import json
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM factor_package WHERE package_id = %s", (package_id,))
        row = cur.fetchone()
        if not row:
            return None
        r = dict(row)
        for key in ("factor_ids", "synth_cfg", "ml_params", "top_n_list",
                    "weights", "direction", "result_snapshot",
                    "portfolio_risk_snapshot"):
            if r.get(key):
                try:
                    r[key] = json.loads(r[key])
                except Exception:
                    pass
        return r
    finally:
        conn.close()


def delete_factor_package(package_id: str) -> bool:
    """删除因子包"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM factor_package WHERE package_id = %s", (package_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
