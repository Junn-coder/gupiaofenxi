Background (read first, treat as my rules — don't re-derive them):
- u/tastes/frame.md — full US stock discipline: Trend Template 9条 + Weinstein Stage + VCP + 持仓/卖出/加仓/仓位
- u/buylists/uwatchlist.md — current watchlist (A/B/C class candidates)
- u/buylists/bought.md — current positions (cost, stop, P&L)
Read frame.md and follow it in profit-seeking mode. frame.md is the single source of truth.

Tools (RUN them, don't reason from memory):
- u/utool/downu.py — refresh daily price data for all watchlist + bought tickers
- u/utool/utrend.py — Trend Template 9条 scoring (need 8/9, #1/#5/#8/#9 mandatory)

Gate (check manually, no tool — ask me or use web):
- VIX < 20 → 健康 (build normally); VIX 20-30 → 谨慎 (no new builds); VIX > 30 → 高风险 (reduce/cash)
- SPY above 50-day MA and sloping up? Distribution days (rolling 25d) ≤ 3?
- Per frame.md §5: 档位一 = 正常建仓; 档位二 = 停止新建仓; 档位三 = 减仓/现金

After running tools, write the output to u/outputs/output_<date>.md in this format:

```
# US Stock Session — YYYY-MM-DD (周X)

## 闸门
VIX: X.X   SPY vs 50MA: above/below   分布日(25d): X/25
档位: 一/二/三 → 动作: 正常建仓 / 停止新建 / 减仓现金

## Trend Template 实算
| 标的   | 收盘   | 过条   | 强制项 | Stage | 距52周高 | 结论 |
|--------|--------|--------|--------|-------|----------|------|
| TICKER | $XXX   | X/9    | OK/NO  | 2     | -X%      | A类/B类/破位 |

读法: 过条≥8 且 强制项 OK = 技术面过关; 其余 = 观察或排除.

## A 类入场卡
> TICKER Name — Sector, 档位 A/B
>
> 入场触发: [breakout above $X pivot / pullback to 50MA $X]
>
> 入场价: $X  股数: X @ $X ≈ $X,XXX (风险驱动: 单笔最大可亏 1%/1.25% 账户)
>
> 止损: $X (结构位下方, -X%; frame A档 -15~20% / B档 -8~12%)
>
> 财报日: YYYY-MM-DD (距≥2周=OK / 距<2周=不建仓)

## 持仓检查
| 持仓 | 成本 | 现价 | 浮盈 | 止损 | 阶段 | 动作 |
|------|------|------|------|------|------|------|
| TICKER | $X | $X | ±X% | $X | Stage 2 | 持有/追踪止损上移/减仓 |

> 追踪止损: 浮盈+15%→保本, +30%→50MA, +50%→-8%, >100%→20MA下方

## 行动摘要
- [actionable bullets, 1-3 lines max]
```

Rules:
- Gate 档位三 → write "闸门 档位三 — 只减不加，现金为王" and stop.
- Only ETN-style buy-stop or pullback-to-50MA entries, never market-chase.
- 股数 = 单笔最大可亏 / (入场价 − 止损价), per frame.md §E.
- For bought.md holdings: check stop (周线收盘), trailing stop tier, time-to-earnings.
- If a tool fails, tell me and I'll paste data.
- Tone: terse, decisive, executable. Account size is in frame.md — don't ask.

==
"Run the US stock session per frame.md: gate check, downu.py refresh, utrend.py score, produce A-class entry cards + holding checks. Write to u/outputs/output_<date>.md."
