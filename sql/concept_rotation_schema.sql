-- -*- coding: utf-8 -*-
-- 概念轮动排名日表
-- 用途: 存储每日概念轮动排名、强度得分、phase 等指标, 供概念轮动热力图页面展示
-- 更新策略: 每日增量写入, 全量重建时先 DELETE FROM trade_concept_rotation_daily

DROP TABLE IF EXISTS trade_concept_rotation_daily;

CREATE TABLE trade_concept_rotation_daily (
    trade_date      DATE NOT NULL,
    concept_code    VARCHAR(32)  NOT NULL,
    concept_name    VARCHAR(100) NOT NULL,
    source_prefix   VARCHAR(10),
    rank            SMALLINT NOT NULL,
    composite_rank  SMALLINT NOT NULL,
    score           NUMERIC(14, 6),
    composite_score NUMERIC(14, 6),
    phase           VARCHAR(16),
    mom10_z         NUMERIC(14, 6),
    rs20_z          NUMERIC(14, 6),
    vol_ratio_z     NUMERIC(14, 6),
    roc_20          NUMERIC(14, 6),
    ma20_slope      NUMERIC(14, 6),
    ma20_accel      NUMERIC(14, 6),
    macd_hist       NUMERIC(14, 6),
    hist_delta      NUMERIC(14, 6),
    member_count    SMALLINT,
    updated_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (trade_date, concept_code)
);

CREATE INDEX idx_concept_rotation_date_rank
    ON trade_concept_rotation_daily (trade_date, rank);

CREATE INDEX idx_concept_rotation_concept_date
    ON trade_concept_rotation_daily (concept_code, trade_date);

COMMENT ON TABLE trade_concept_rotation_daily IS '概念轮动每日排名与指标';
COMMENT ON COLUMN trade_concept_rotation_daily.trade_date IS '交易日期';
COMMENT ON COLUMN trade_concept_rotation_daily.concept_code IS '概念编码';
COMMENT ON COLUMN trade_concept_rotation_daily.concept_name IS '概念名称';
COMMENT ON COLUMN trade_concept_rotation_daily.source_prefix IS '概念来源前缀, 用于区分同名概念(TGN/TDGN/GN)';
COMMENT ON COLUMN trade_concept_rotation_daily.rank IS '强度得分排名';
COMMENT ON COLUMN trade_concept_rotation_daily.composite_rank IS '综合得分排名(含 phase 加分)';
COMMENT ON COLUMN trade_concept_rotation_daily.score IS '强度得分: MOM_10_z + RS_20_z + 0.5*VOL_RATIO_z';
COMMENT ON COLUMN trade_concept_rotation_daily.composite_score IS '综合得分(强度得分 + phase 加分)';
COMMENT ON COLUMN trade_concept_rotation_daily.phase IS '轮动象限: accel_up/decel_up/accel_down/decel_down/neutral';
COMMENT ON COLUMN trade_concept_rotation_daily.mom10_z IS '10日动量 Z-score';
COMMENT ON COLUMN trade_concept_rotation_daily.rs20_z IS '20日相对强度 Z-score';
COMMENT ON COLUMN trade_concept_rotation_daily.vol_ratio_z IS '成交量比率 Z-score';
COMMENT ON COLUMN trade_concept_rotation_daily.roc_20 IS '20日变化率(%)';
COMMENT ON COLUMN trade_concept_rotation_daily.ma20_slope IS 'MA20 最小二乘斜率(年化%)';
COMMENT ON COLUMN trade_concept_rotation_daily.ma20_accel IS 'MA20 斜率加速度(年化%)';
COMMENT ON COLUMN trade_concept_rotation_daily.macd_hist IS 'MACD 柱状值';
COMMENT ON COLUMN trade_concept_rotation_daily.hist_delta IS 'MACD 柱状值变化';
COMMENT ON COLUMN trade_concept_rotation_daily.member_count IS '概念成分股数量';
