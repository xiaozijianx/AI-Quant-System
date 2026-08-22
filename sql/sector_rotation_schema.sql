-- -*- coding: utf-8 -*-
-- 板块轮动排名日表
-- 用途: 存储每日板块轮动排名、强度得分、phase 等指标, 供板块轮动热力图页面展示
-- 更新策略: 每日增量写入, 全量重建时先 DELETE FROM trade_sector_rotation_daily WHERE sector_level = ?

DROP TABLE IF EXISTS trade_sector_rotation_daily;

CREATE TABLE trade_sector_rotation_daily (
    trade_date      DATE NOT NULL,
    sector_name     VARCHAR(128) NOT NULL,
    sector_level    SMALLINT NOT NULL DEFAULT 2,
    rank            SMALLINT NOT NULL,
    composite_rank  SMALLINT NOT NULL,
    score           NUMERIC(14, 6),
    composite_score NUMERIC(14, 6),
    phase           VARCHAR(16),
    mom21_z         NUMERIC(14, 6),
    rs60_z          NUMERIC(14, 6),
    vol_ratio_z     NUMERIC(14, 6),
    roc_20          NUMERIC(14, 6),
    ma20_slope      NUMERIC(14, 6),
    ma20_accel      NUMERIC(14, 6),
    macd_hist       NUMERIC(14, 6),
    hist_delta      NUMERIC(14, 6),
    member_count    SMALLINT,
    updated_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (trade_date, sector_name, sector_level)
);

CREATE INDEX idx_sector_rotation_date_level_rank
    ON trade_sector_rotation_daily (trade_date, sector_level, rank);

CREATE INDEX idx_sector_rotation_sector_date
    ON trade_sector_rotation_daily (sector_name, sector_level, trade_date);

COMMENT ON TABLE trade_sector_rotation_daily IS '板块轮动每日排名与指标';
COMMENT ON COLUMN trade_sector_rotation_daily.trade_date IS '交易日期';
COMMENT ON COLUMN trade_sector_rotation_daily.sector_name IS '板块名称';
COMMENT ON COLUMN trade_sector_rotation_daily.sector_level IS '板块级别: 1=申万一级, 2=申万二级';
COMMENT ON COLUMN trade_sector_rotation_daily.rank IS '强度得分排名';
COMMENT ON COLUMN trade_sector_rotation_daily.composite_rank IS '综合得分排名(含 phase 加分)';
COMMENT ON COLUMN trade_sector_rotation_daily.score IS '等权合成强度得分';
COMMENT ON COLUMN trade_sector_rotation_daily.composite_score IS '综合得分(强度得分 + phase 加分)';
COMMENT ON COLUMN trade_sector_rotation_daily.phase IS '轮动象限: accel_up/decel_up/accel_down/decel_down/neutral';
COMMENT ON COLUMN trade_sector_rotation_daily.mom21_z IS '21日动量 Z-score';
COMMENT ON COLUMN trade_sector_rotation_daily.rs60_z IS '60日相对强度 Z-score';
COMMENT ON COLUMN trade_sector_rotation_daily.vol_ratio_z IS '成交量比率 Z-score';
COMMENT ON COLUMN trade_sector_rotation_daily.roc_20 IS '20日变化率(%)';
COMMENT ON COLUMN trade_sector_rotation_daily.ma20_slope IS 'MA20 最小二乘斜率(年化%)';
COMMENT ON COLUMN trade_sector_rotation_daily.ma20_accel IS 'MA20 斜率加速度(年化%)';
COMMENT ON COLUMN trade_sector_rotation_daily.macd_hist IS 'MACD 柱状值';
COMMENT ON COLUMN trade_sector_rotation_daily.hist_delta IS 'MACD 柱状值变化';
COMMENT ON COLUMN trade_sector_rotation_daily.member_count IS '板块成分股数量';
