Background (read first — treat as my rules, don't re-derive):
- u/tastes/frame.md — single source of truth: Trend Template 9条 + Weinstein Stage + VCP + 持仓/卖出/加仓/仓位
- u/buylists/uwatchlist.md — 主数据库: 全量 TT 表 + 逐赛道分析 (每周更新, 买入时不看)
- u/outputs/current.md — 每日战报: 闸门 + A类入场卡 + 行动摘要 (买入前必看)
- u/buylists/bought.md — current positions (cost, stop, P&L)

两文件分工:
  uwatchlist.md = "有哪些票" — 全景扫描, 长期跟踪
  current.md   = "今天能不能买" — 闸门 + 入场价/止损/仓位, 每日更新
  TT 表只在 uwatchlist.md 维护, current.md 只写 A 类入场卡 + 行动摘要.

Tools (RUN them — don't reason from memory):
- u/utool/us_gate.py — gate: SPY vs 50MA, VIX, 档位判定
- u/utool/downu.py — refresh daily price data for all watchlist + bought tickers
- u/utool/utrend.py — Trend Template 9条 scoring (need 8/9, #1/#5/#8/#9 mandatory)

每日工作流 (两步):
  第一步: downu.py 刷新 → utrend.py 扫描 → 更新 uwatchlist.md 的 TT 表
  第二步: us_gate.py 闸门 → 从 uwatchlist.md A 类中挑出可操作的 → 写 current.md

---

## current.md 输出格式 (每日战报 — 精简, 买入前看)

```
# US Stock Daily Brief — YYYY-MM-DD (周X)

> 全量 TT 表 + 逐赛道分析 → uwatchlist.md

## 闸门
VIX: X.X   SPY: $X vs 50MA $X   分布日(25d): X/25
档位: 一/二/三 → 动作

## A 类入场卡

(每只标注两个方向: 突破买入 / 回踩买入)

> TICKER — Name, Sector  [← 最接近触发 标注]
>
> 突破买入: [breakout above $X pivot, vol ≥1.5x 20d avg]  入场 $X  止损 $X (-X%)
>
> 回踩买入: [pullback to 50MA $X, hold + bullish candle + above-avg vol]  入场 $X-$X  止损 $X (-X%)
>
> 仓位: X 股 @ $X ≈ $X,XXX (A档 ≤30% / B档 ≤20%)
>
> 今日: [action]

## 持仓

[active positions or "无活跃持仓"]

## 行动摘要
- [1-3 actionable bullets]

---
REPORT_COMPLETE
```

---

## uwatchlist.md 输出格式 (主数据库 — 每周更新)

TT 表分三档: A类(9/9+强制OK) / 观察(8/9) / 排除(<8/9或基本面不达标)
每只标的下方附 1-2 行赛道分析. 入场价/止损/仓位不写在这里.
模板见 uwatchlist.md 当前内容.

---

Rules:
- Gate 档位三 → current.md 写 "闸门 档位三 — 只减不加，现金为王" 并跳过入场卡.
- Only buy-stop or pullback-to-50MA entries, never market-chase.
- 股数 = 单笔最大可亏 / (入场价 − 止损价), per frame.md §E.
- 量规则: 1.5-5.0x 20日均量; <1.5x 缩量不算, ≥5.0x 衰竭量放弃.
- 距50MA规则: 5-40% (理想 5-15%); >40% 不追.
- 均线边缘规则: 当 150MA 与 200MA 差距 < 1% 时，TT 评分即使 9/9 也不建仓（均线即将死叉，信号脆弱）。
- For bought.md holdings: check stop (周线收盘), trailing stop tier, time-to-earnings.
- If a tool fails, tell me and I'll paste data.
- Tone: terse, decisive, executable. Account size is in frame.md — don't ask.

==
"Run the US stock session: (1) downu.py refresh → utrend.py scan → update uwatchlist.md TT table. (2) us_gate.py gate → write current.md with gate + A-class entry cards + action summary."
