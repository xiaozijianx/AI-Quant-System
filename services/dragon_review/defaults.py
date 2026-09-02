# -*- coding: utf-8 -*-
"""龙头复盘默认常量 (自 routes/dragon_review.py 迁移, 逻辑逐字不变)."""
from __future__ import annotations

TOP_N = 3
MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
DEFAULT_VOLUME_MA_DAYS = 20
DEFAULT_VOLUME_RATIO_MA = 1.2
DEFAULT_VOLUME_RATIO_RING = 1.15
MARKET_INDEX_CODE = "000001.SH"

# 全 A 股代码识别条件（SQL 片段，与 CASE-A5 precompute.py 保持一致）：
#   - 沪市 A 股: 60/68/90 开头 .SH（90 为沪市 B 股）
#   - 深市 A 股: 00/30/20 开头 .SZ（20 为深市 B 股）
#   - 北交所:    4/8/92 开头 .BJ
# 排除指数（000xxx.SH 上证/中证指数、399xxx.SZ 深证指数、98xx 北证指数）、
#       ETF/基金（15/16/18.SZ、50/51/52/53/55/56/58.SH）、可转债（11/12/13 开头）
# 不依赖 trade_stock_status（申万分类），确保无分类的新股也能计入大盘统计
A_STOCK_CONDITION = """
    (
        (stock_code LIKE '60%%' AND stock_code LIKE '%%.SH')
        OR (stock_code LIKE '68%%' AND stock_code LIKE '%%.SH')
        OR (stock_code LIKE '90%%' AND stock_code LIKE '%%.SH')
        OR (stock_code LIKE '00%%' AND stock_code LIKE '%%.SZ')
        OR (stock_code LIKE '30%%' AND stock_code LIKE '%%.SZ')
        OR (stock_code LIKE '20%%' AND stock_code LIKE '%%.SZ')
        OR (stock_code LIKE '4%%' AND stock_code LIKE '%%.BJ')
        OR (stock_code LIKE '8%%' AND stock_code LIKE '%%.BJ')
        OR (stock_code LIKE '92%%' AND stock_code LIKE '%%.BJ')
    )
"""

# 板块低位过滤默认值：短周期判断"近期是否急涨"，长周期判断"是否涨了大波后小幅回调"
DEFAULT_SECTOR_SHORT_LOOKBACK = 10     # 板块短窗：看近 N 个交易日累计涨幅
DEFAULT_SECTOR_SHORT_RETURN_PCT = 15.0 # 板块短窗：累计涨幅超过该百分比视为不在低位
DEFAULT_SECTOR_LONG_LOOKBACK = 30      # 板块长窗：看近 N 个交易日累计涨幅
DEFAULT_SECTOR_LONG_RETURN_PCT = 30.0  # 板块长窗：累计涨幅超过该百分比视为不在低位
DEFAULT_SECTOR_MAX_BOARD_LEVEL = 3     # 板块内最高连板不超过 N 板

# 概念低位过滤默认值：短周期判断"近期是否急涨"，长周期判断"是否涨了大波后小幅回调"
DEFAULT_CONCEPT_SHORT_LOOKBACK = 10    # 概念短窗：看近 N 个交易日累计涨幅
DEFAULT_CONCEPT_SHORT_RETURN_PCT = 8.0 # 概念短窗：累计涨幅超过该百分比视为不在低位
DEFAULT_CONCEPT_LONG_LOOKBACK = 30     # 概念长窗：看近 N 个交易日累计涨幅
DEFAULT_CONCEPT_LONG_RETURN_PCT = 20.0 # 概念长窗：累计涨幅超过该百分比视为不在低位
DEFAULT_CONCEPT_MAX_BOARD_LEVEL = 3    # 概念内最高连板不超过 N 板

# 个股低位过滤默认值
DEFAULT_STOCK_GAIN_DAYS = 5           # 个股低位判断：近 N 日涨幅
DEFAULT_STOCK_GAIN_LIMIT = 20.0       # 个股低位判断：涨幅不超过 %
DEFAULT_AMOUNT_WEIGHT = 0.6           # 量能分中“成交量分”的权重，放量分权重 = 1 - 该值
DEFAULT_VOLUME_UP_WEIGHT = 0.4        # 兼容保留，实际使用 1 - amount_weight
DEFAULT_CONCEPT_SIMILARITY_THRESHOLD = 0.4  # 概念亲密度阈值（百分比）

# ============================================================
# 龙头板块/概念复合打分权重默认值
# ============================================================
# 5 个维度：涨停率、涨停数量、平均涨幅、人均成交额、成交额环比放大倍数
DEFAULT_SECTOR_COUNT_WEIGHT = 0.25
DEFAULT_SECTOR_RATIO_WEIGHT = 0.30
DEFAULT_SECTOR_CHANGE_WEIGHT = 0.25
DEFAULT_SECTOR_AMOUNT_WEIGHT = 0.10
DEFAULT_SECTOR_AMOUNT_RATIO_WEIGHT = 0.10

DEFAULT_CONCEPT_COUNT_WEIGHT = 0.25
DEFAULT_CONCEPT_RATIO_WEIGHT = 0.30
DEFAULT_CONCEPT_CHANGE_WEIGHT = 0.25
DEFAULT_CONCEPT_AMOUNT_WEIGHT = 0.10
DEFAULT_CONCEPT_AMOUNT_RATIO_WEIGHT = 0.10

DEFAULT_CONCEPT_MIN_LIMIT_UP = 2      # 概念最少涨停家数（过滤极小概念）
DEFAULT_CONCEPT_MIN_STOCK_COUNT = 10  # 概念最少成分股数

# 大盘情绪过滤默认值
DEFAULT_MAX_LIMIT_DOWN = 10           # 最大跌停家数
DEFAULT_MIN_UP_DOWN_RATIO = 3.0       # 最小涨跌停比（涨停家数 / 跌停家数）
DEFAULT_MIN_RISE_RATIO = 0.5          # 最小上涨家数占比

# 龙头股 4 维打分权重默认值（封单质量已合并进涨停强度）
DEFAULT_LEADER_STRENGTH_WEIGHT = 0.45   # 涨停强度（含板型、首次涨停时间、炸板扣分）
DEFAULT_LEADER_AMOUNT_WEIGHT = 0.30     # 量能强度
DEFAULT_LEADER_TURNOVER_WEIGHT = 0.15   # 换手健康
DEFAULT_LEADER_POSITION_WEIGHT = 0.10   # 位置安全

# 龙头股相关性权重：与板块/概念的联动程度
DEFAULT_LEADER_SECTOR_RELEVANCE_WEIGHT = 0.10   # 板块相关性（申万二级）
DEFAULT_LEADER_CONCEPT_RELEVANCE_WEIGHT = 0.10  # 概念相关性
