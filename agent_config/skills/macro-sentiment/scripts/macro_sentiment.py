#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宏观情绪与风险指标分析

功能：获取A股市场情绪指标和全球宏观恐慌指标，计算综合恐慌/贪婪评分，
      为投资决策提供宏观维度的情绪参考。

监控指标体系：
  A股情绪维度：
    - 上证50ETF QVIX（中国波指/恐慌指数）：衡量A股大盘蓝筹的隐含波动率
    - 上证指数近期表现：近10日涨跌幅，判断趋势
    - 北向资金净买额：外资流入/流出情况
    - 融资余额：市场杠杆情绪
  全球宏观维度：
    - VIX恐慌指数（FRED）：标普500隐含波动率
    - 美国10年期国债收益率（akshare）：全球资产定价之锚

用法：
    python macro_sentiment.py
    python macro_sentiment.py --mode china
    python macro_sentiment.py --mode global --output_dir outputs/news/
"""

import argparse
import json
import os
from datetime import datetime

import akshare as ak
import requests

# ── 全局指标阈值参考 ──────────────────────────────────

# 中国波指 QVIX 阈值（%）
# QVIX 是上证50ETF期权隐含波动率指数，类似 VIX
QVIX_THRESHOLDS = [
    ("极度恐慌", 35),
    ("恐慌", 28),
    ("焦虑", 22),
    ("正常", 16),
    ("平静", 0),
]

# VIX 恐慌指数阈值
VIX_THRESHOLDS = [
    ("极度恐慌", 35),
    ("恐慌", 25),
    ("焦虑", 20),
    ("正常", 15),
    ("平静", 0),
]

# 美国10年期国债收益率阈值
TREASURY_THRESHOLDS = [
    ("高利率压制", 4.8),
    ("偏紧", 4.4),
    ("分水岭", 4.3),
    ("宽松预期", 3.8),
]

# FRED 序列 ID
FRED_SERIES = {"VIX": "VIXCLS"}


# ── 辅助函数 ──


def _fred_latest(series_id: str) -> tuple:
    """从 FRED 公开 CSV 获取最后一笔有效观测值。"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        return None, None, str(e)

    last_val, last_date = None, None
    for line in resp.text.strip().splitlines():
        if line.startswith("DATE"):
            continue
        parts = line.split(",", 1)
        if len(parts) < 2:
            continue
        raw = parts[1].strip()
        if raw == "" or raw == ".":
            continue
        try:
            last_val = float(raw)
            last_date = parts[0].strip()
        except ValueError:
            continue
    return last_val, last_date, None


def _classify(value: float, thresholds: list) -> str:
    """根据阈值列表判断等级。"""
    for level, threshold in thresholds:
        if value >= threshold:
            return level
    return thresholds[-1][0]


def _safe_val(v):
    """将可能非 JSON 可序列化的值转为字符串。"""
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, (datetime,)):
        return v.strftime("%Y-%m-%d")
    return str(v) if not isinstance(v, (dict, list)) else v


def _clean_for_json(obj):
    """递归清洗数据结构中的非 JSON 可序列化类型。"""
    if isinstance(obj, dict):
        return {k: _clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_for_json(v) for v in obj]
    return _safe_val(obj)


# ── 数据获取函数 ──


def fetch_qvix() -> dict:
    """
    获取上证50ETF QVIX（中国波指/恐慌指数）。

    上证50ETF QVIX 是上交所发布的波动率指数，基于50ETF期权价格计算，
    反映市场对上证50ETF未来30日波动率的预期，是中国版的"VIX"。
    """
    try:
        df = ak.index_option_50etf_qvix()
        if df is None or df.empty:
            return {"qvix": None, "error": "QVIX 数据为空"}

        latest = df.iloc[-1]
        qvix_close = float(latest["close"])
        qvix_date = str(latest["date"])

        level = _classify(qvix_close, QVIX_THRESHOLDS)
        print(f"[QVIX] {qvix_close:.2f}%, 等级: {level}, 日期: {qvix_date}")
        return {
            "qvix": round(qvix_close, 2),
            "unit": "%",
            "date": qvix_date,
            "level": level,
            "description": "上证50ETF波动率指数（中国波指），衡量A股大盘蓝筹的恐慌程度",
            "source": "akshare.index_option_50etf_qvix",
        }
    except Exception as e:
        print(f"[QVIX] 获取失败: {e}")
        return {"qvix": None, "error": str(e)}


def fetch_shanghai_index() -> dict:
    """获取上证指数近期表现（近10日涨跌幅）。"""
    try:
        df = ak.stock_zh_index_daily(symbol="sh000001")
        if df is None or df.empty:
            return {"shanghai_index": None, "error": "上证指数数据为空"}

        recent = df.tail(10)
        latest_close = float(recent.iloc[-1]["close"])
        latest_date = str(recent.iloc[-1]["date"]).split()[0]
        prev_close = float(recent.iloc[0]["close"])
        change_pct = ((latest_close - prev_close) / prev_close) * 100

        trend = "上涨" if change_pct > 1 else ("下跌" if change_pct < -1 else "震荡")
        print(f"[上证指数] {latest_close:.2f}, 近10日涨跌幅: {change_pct:.2f}%, 趋势: {trend}")
        return {
            "latest_close": round(latest_close, 2),
            "date": latest_date,
            "10d_change_pct": round(change_pct, 2),
            "trend": trend,
            "description": "上证指数近10日涨跌幅，反映A股整体走势方向",
        }
    except Exception as e:
        print(f"[上证指数] 获取失败: {e}")
        return {"shanghai_index": None, "error": str(e)}


def fetch_north_flow() -> dict:
    """
    获取北向资金净买额（沪股通+深股通）。

    北向资金 = 沪股通净买额 + 深股通净买额，反映外资对A股的配置态度。
    """
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is None or df.empty:
            return {"north_flow": None, "error": "北向资金数据为空"}

        # 过滤北向资金（沪股通 + 深股通）
        north = df[df["资金方向"] == "北向"]
        # 取最新交易日
        latest_date = north["交易日"].iloc[-1]
        latest = north[north["交易日"] == latest_date]

        total_net = latest["成交净买额"].sum()
        # 单位确认：通常为亿元
        total_net = float(total_net)

        signal = "外资流入" if total_net > 0 else "外资流出"
        print(f"[北向资金] 净买额: {total_net:.2f} 亿元, 日期: {latest_date}")
        return {
            "net_buy": round(total_net, 2),
            "unit": "亿元",
            "date": latest_date,
            "signal": signal,
            "source": "akshare.stock_hsgt_fund_flow_summary_em",
        }
    except Exception as e:
        print(f"[北向资金] 获取失败: {e}")
        return {"north_flow": None, "error": str(e)}


def fetch_margin() -> dict:
    """获取深市融资余额（反映市场杠杆情绪）。"""
    try:
        df = ak.stock_margin_szse()
        if df is None or df.empty:
            return {"margin": None, "error": "融资融券数据为空"}
        columns = df.columns.tolist()
        print(f"[融资融券] 数据列: {columns}")

        # 取最新一条
        latest = df.iloc[-1]
        balance = float(latest["融资余额"])
        total = float(latest["融资融券余额"])

        # 计算趋势（与5日前比较）
        if len(df) >= 5:
            prev = float(df.iloc[-5]["融资余额"])
            change_pct = ((balance - prev) / prev) * 100
            trend = "加杠杆" if change_pct > 0.5 else ("去杠杆" if change_pct < -0.5 else "平稳")
        else:
            change_pct = 0
            trend = "数据不足"

        print(f"[融资余额] {balance:.2f} 亿元, 近5日变化: {change_pct:.2f}%, 趋势: {trend}")
        return {
            "margin_balance": round(balance, 2),
            "total_balance": round(total, 2),
            "unit": "亿元",
            "5d_change_pct": round(change_pct, 2),
            "trend": trend,
            "source": "akshare.stock_margin_szse",
        }
    except Exception as e:
        print(f"[融资融券] 获取失败: {e}")
        return {"margin": None, "error": str(e)}


def fetch_vix() -> dict:
    """获取VIX恐慌指数（FRED VIXCLS）。"""
    value, date, error = _fred_latest(FRED_SERIES["VIX"])
    if value is None:
        return {"vix": None, "error": error or "FRED VIXCLS 数据获取失败"}

    risk_level = _classify(value, VIX_THRESHOLDS)
    print(f"[VIX] {value:.2f}, 风险等级: {risk_level}, 日期: {date}")
    return {
        "vix": round(value, 2),
        "date": date,
        "risk_level": risk_level,
        "description": "衡量美股市场的恐慌程度",
        "source": "FRED (VIXCLS)",
    }


def fetch_us_treasury_10y() -> dict:
    """获取美国10年期国债收益率。"""
    try:
        df = ak.bond_zh_us_rate(start_date="20240101")
        if df is None or df.empty:
            return {"us10y": None, "error": "国债收益率数据为空"}
        columns = df.columns.tolist()
        print(f"[10Y国债] 数据列: {columns}")

        target_col = None
        for col in columns:
            if "美国" in col and "10年" in col and "10年-" not in col:
                target_col = col
                break
        if target_col is None:
            return {"us10y": None, "error": "未找到美国10年国债收益率列"}

        valid = df.dropna(subset=[target_col])
        if valid.empty:
            return {"us10y": None, "error": "美国10年国债收益率全部为空"}

        latest = valid.iloc[-1]
        yield_value = float(latest[target_col])
        yield_date = str(latest["日期"]) if "日期" in columns else ""

        risk_level = _classify(yield_value, TREASURY_THRESHOLDS)
        print(f"[10Y国债] {yield_value:.3f}%, 等级: {risk_level}")
        return {
            "us10y": round(yield_value, 3),
            "unit": "%",
            "date": yield_date,
            "risk_level": risk_level,
            "description": "全球资产定价之锚",
            "source": "akshare.bond_zh_us_rate",
        }
    except Exception as e:
        print(f"[10Y国债] 获取失败: {e}")
        return {"us10y": None, "error": str(e)}


# ── 综合评分 ──


def compute_composite_score(china_indicators: list) -> dict:
    """
    根据A股指标计算综合恐慌/贪婪评分（0-100）。

    评分规则：
      QVIX（中国波指）：
        < 16 -> +10 (极低波动，平静)
        16-22 -> +5 (正常偏低)
        22-28 -> 0 (正常)
        28-35 -> -10 (偏高，恐慌预期)
        > 35 -> -20 (极高，极度恐慌)

      北向资金净买额：
        > 50亿 -> +10 (大幅流入)
        0-50亿 -> +5 (小幅流入)
        -50亿-0 -> -5 (小幅流出)
        < -50亿 -> -10 (大幅流出)

      融资余额变化：
        > 0.5% -> +5 (加杠杆，偏乐观)
        -0.5%~0.5% -> 0 (平稳)
        < -0.5% -> -5 (去杠杆，偏谨慎)
    """
    score = 50
    score_details = []

    for ind in china_indicators:
        if ind.get("value") is None:
            continue

        name = ind["name"]
        value = ind["value"]

        if name == "qvix":
            if value < 16:
                delta, note = 10, "QVIX波动率极低，市场过度平静"
            elif value < 22:
                delta, note = 5, "QVIX波动率正常偏低，市场情绪偏乐观"
            elif value < 28:
                delta, note = 0, "QVIX波动率处于正常区间"
            elif value < 35:
                delta, note = -10, "QVIX波动率偏高，市场存在恐慌预期"
            else:
                delta, note = -20, "QVIX波动率极高，市场极度恐慌"
            score += delta
            score_details.append({"indicator": "QVIX中国波指", "value": value, "score_delta": delta, "note": note})

        elif name == "north_flow":
            if value >= 50:
                delta, note = 10, "北向资金大幅流入，外资看好A股"
            elif value >= 0:
                delta, note = 5, "北向资金小幅流入，外资偏积极"
            elif value >= -50:
                delta, note = -5, "北向资金小幅流出，外资偏谨慎"
            else:
                delta, note = -10, "北向资金大幅流出，外资避险"
            score += delta
            score_details.append({"indicator": "北向资金", "value": value, "score_delta": delta, "note": note})

        elif name == "margin_change":
            if value >= 0.5:
                delta, note = 5, "融资余额上升，市场加杠杆偏向乐观"
            elif value >= -0.5:
                delta, note = 0, "融资余额平稳，杠杆情绪中性"
            else:
                delta, note = -5, "融资余额下降，市场去杠杆偏向谨慎"
            score += delta
            score_details.append({"indicator": "融资余额变化", "value": value, "score_delta": delta, "note": note})

    score = max(0, min(100, score))

    if score >= 80:
        overall = "极度贪婪"
        action = "市场可能过热，注意回调风险"
    elif score >= 65:
        overall = "贪婪"
        action = "市场情绪偏乐观，可顺势但控制仓位"
    elif score >= 45:
        overall = "中性"
        action = "市场情绪平衡，按策略正常操作"
    elif score >= 30:
        overall = "恐慌"
        action = "市场存在恐慌，可关注超跌反弹机会"
    else:
        overall = "极度恐慌"
        action = "市场极度恐慌，历史上往往是中长期买入良机"

    return {
        "composite_fear_greed_index": score,
        "overall_sentiment": overall,
        "action_suggestion": action,
        "score_details": score_details,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── 主函数 ──


def main():
    parser = argparse.ArgumentParser(description="宏观情绪与风险指标分析")
    parser.add_argument("--mode", default="all", choices=["all", "china", "global"],
                        help="数据范围: all(默认,A股+全球), china(仅A股), global(仅全球)")
    parser.add_argument("--output_dir", default="./data", help="输出目录")
    args = parser.parse_args()

    print("=" * 60)
    print("  宏观情绪与风险指标分析")
    print(f"  模式: {args.mode}")
    print("=" * 60)

    result = {
        "mode": args.mode,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    china_indicators = []

    # ── A股市场情绪 ──
    if args.mode in ("all", "china"):
        print("\n[1/4] 获取上证50ETF QVIX（中国波指）...")
        qvix = fetch_qvix()
        result["china_qvix"] = qvix
        if qvix.get("qvix") is not None:
            china_indicators.append({"name": "qvix", "value": qvix["qvix"]})

        print("\n[2/4] 获取上证指数...")
        result["shanghai_index"] = fetch_shanghai_index()

        print("\n[3/4] 获取北向资金流向...")
        nf = fetch_north_flow()
        result["north_flow"] = nf
        if nf.get("net_buy") is not None:
            china_indicators.append({"name": "north_flow", "value": nf["net_buy"]})

        print("\n[4/4] 获取融资融券余额...")
        mg = fetch_margin()
        result["margin"] = mg
        if mg.get("5d_change_pct") is not None:
            china_indicators.append({"name": "margin_change", "value": mg["5d_change_pct"]})

        # 计算综合评分
        print("\n[计算] 综合恐慌/贪婪指数...")
        composite = compute_composite_score(china_indicators)
        result["composite"] = composite

    # ── 全球宏观指标 ──
    if args.mode in ("all", "global"):
        print("\n[全球1/2] 获取VIX恐慌指数...")
        result["vix"] = fetch_vix()

        print("\n[全球2/2] 获取美国10年期国债收益率...")
        result["us10y"] = fetch_us_treasury_10y()

    # ── 保存输出 ──
    os.makedirs(args.output_dir, exist_ok=True)
    date_tag = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(args.output_dir, f"macro_sentiment_{date_tag}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(_clean_for_json(result), f, ensure_ascii=False, indent=2)
    print(f"\n[保存] {output_file}")

    # 打印摘要
    print(f"\n{'=' * 60}")
    if "composite" in result:
        c = result["composite"]
        print(f"  综合恐慌/贪婪指数: {c['composite_fear_greed_index']}/100")
        print(f"  整体情绪: {c['overall_sentiment']}")
        print(f"  建议操作: {c['action_suggestion']}")
        for d in c.get("score_details", []):
            print(f"  [{d['indicator']}] {d['value']} -> {d['note']}")
    if "china_qvix" in result and result["china_qvix"].get("qvix"):
        print(f"  中国波指 QVIX: {result['china_qvix']['qvix']}% ({result['china_qvix']['level']})")
    if "vix" in result and result["vix"].get("vix"):
        print(f"  VIX: {result['vix']['vix']} ({result['vix']['risk_level']})")
    if "us10y" in result and result["us10y"].get("us10y"):
        print(f"  10Y国债: {result['us10y']['us10y']}% ({result['us10y']['risk_level']})")
    print(f"{'=' * 60}")

    # 输出结构化结果
    summary = {
        "status": "success",
        "output_file": output_file,
    }
    if "composite" in result:
        summary["fear_greed_index"] = result["composite"]["composite_fear_greed_index"]
        summary["overall_sentiment"] = result["composite"]["overall_sentiment"]
        summary["action_suggestion"] = result["composite"]["action_suggestion"]
    print(f"\n[结果] {json.dumps(summary, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    main()