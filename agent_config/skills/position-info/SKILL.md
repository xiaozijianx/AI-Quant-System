---
name: position-info
description: "查询当前模拟盘或实盘的持仓信息，包括持仓股数、成本价、当前价、盈亏、可用资金及 ATR（平均真实波幅）。Use when 需要获取某只股票的持仓状态、计算仓位比例、或获取 ATR 用于止损止盈计算。"
---

# position-info 技能

查询当前持仓状态。本技能读取模拟盘/实盘运行时的状态文件，返回持仓明细和 ATR 指标。

## Workflow

### Step 1: 查询持仓信息

```bash
python agent_config/skills/position-info/scripts/query_position.py <股票代码> [盘类型]
```

参数说明：
- `<股票代码>`（必填）：带交易所后缀，如 `600519.SH`、`000858.SZ`
- `[盘类型]`（可选）：`sim`（模拟盘，默认）或 `live`（实盘）

脚本预期输出 JSON，包含以下字段。每个字段都附带 `meaning` 中文描述，帮助理解数值含义。

**账户整体概况（`account_summary`）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_capital` | `{"value": float, "meaning": str}` | 初始本金（来自 state.initial_capital，引擎启动时设置，交易过程中不变） |
| `total_pnl` | `{"value": float, "meaning": str}` | 总盈亏（总资产 - 初始本金，包含已实现利润和未实现浮动盈亏） |
| `total_value` | `{"value": float, "meaning": str}` | 总资产价值（剩余现金 + 持仓市值 = 当前全部资产） |
| `total_market_value` | `{"value": float, "meaning": str}` | 持仓总市值（所有持仓当前市值之和） |
| `available_capital` | `{"value": float, "meaning": str}` | 可用资金（state.capital = 剩余现金，引擎实时维护，可用于买入新股票） |

**该股持仓详情（`position`）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `has_position` | `{"value": bool, "meaning": str}` | 是否持有该股（true=持有，false=未持仓） |
| `volume` | `{"value": int, "meaning": str}` | 持仓股数（0=未持仓） |
| `cost` | `{"value": float, "meaning": str}` | 持仓均价 |
| `cur_price` | `{"value": float, "meaning": str}` | 最新价 |
| `market_value` | `{"value": float, "meaning": str}` | 该股市值 |
| `pnl` | `{"value": float, "meaning": str}` | 该股盈亏金额 |
| `pnl_pct` | `{"value": float, "meaning": str}` | 该股盈亏百分比 |
| `position_ratio` | `{"value": float, "meaning": str}` | 该股持仓占总资金比例(%) |
| `atr_14` | `{"value": float, "meaning": str}` | 14日ATR（平均真实波幅），用于止损止盈计算 |

### ATR 说明

ATR（Average True Range，平均真实波幅）衡量股票的日内波动幅度。ATR 越大表示波动越剧烈。在交易计划中，ATR 可用于：
- **浮动止盈**：从最高点回落 2 倍 ATR 止盈
- **动态止损**：ATR 倍数计算止损宽度

## Error Handling

- **文件不存在**：状态文件（`outputs/live_state.json`）尚未生成，请先启动模拟盘/实盘引擎
- **股票不在持仓中**：`has_position` 为 false，但 `atr_14` 仍会返回
- **ATR 为 0**：K 线数据不足 15 个交易日，无法计算