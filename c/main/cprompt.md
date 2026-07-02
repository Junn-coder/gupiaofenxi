Background (read first, treat as my rules — don't re-derive them):
- c/main/framed.md  — gate/select/entry/exit/size discipline (3 slots, ¥75K, cap 30-500亿)
- c/main/hota.md    — hot-sector identification (sector-first, stock-second)
- c/main/steps.md   — the step order (gate → scan → validate → size → manage)
Read c/main/hota.md, c/main/framed.md, and c/main/chold.md and follow them in profit-seeking / offensive mode.

Tools (RUN them, don't reason from memory):
- c/ctool/cn_stock.py <code> --history — ⚠ MUST run FIRST before any analysis: refresh cached price data
- c/ctool/index.py — Layer-1 gate (GREEN/AMBER/RED: RED=空仓, AMBER=退潮2槽)
- c/ctool/scan_cn.py --final 3 — converge limit-up pool to 3 candidates (1 per hot sector)
- c/ctool/ca.py <code> --cost <price> — analyze: MAs, ATR, Stage, swing points, P&L
  Workflow: cn_stock.py --history FIRST → then scan/analyze. NEVER use stale cache.

After running tools, write the output to c/main/watchlistd.md in this EXACT format:

```
# watchlistd — Short-term swing watchlist (paired with framed.md)

## YYYY-MM-DD (周X)

闸门：GREEN/AMBER/RED — 上证/创业板/沪深300 简述 + 情绪简述

| # | code   | name   | sector | 市值    | 连板 | flag   |
| - | ------ | ------ | ------ | ------- | ---- | ------ |
| 1 | 603XXX | XX股份 | XX板块 | XX亿 ✓/✗ | X板  | cap-OK / cap-NG / ⚠高位 |

建议：

> 1）[code] [name]
>
> 考虑买入的价格范围和量是：[entry price]，[shares] 股 ~¥[amount]；不能买入的价格是：[above limit / gap-seal]
>
> 止损价格是：[stop price]（ATR 1.0×，max(5%, cap 10%)）
>
> 考虑止盈的价格是：TP1 ¥[+8%] 出一半，TP2 ¥[+15%] 清仓
>
> 可以加仓的价格是：[if applicable, or "不加仓"]
>
> 2）不建议 [code][name] 和 [code][name]。理由：[cap-NG / 5+连板 / 一字板无法买入 / 结构差]

持仓检查：

| 持仓 | 成本 | 现价 | 浮盈 | 天数 | 动作 |
|------|------|------|------|------|------|
| code name | ¥X | ¥Y | ±Z% | N天 | 持有/减仓/清仓 — 触发条件 |
```

Rules for the output:
- 闸门 RED → write "闸门：RED — 空仓，不选股" and stop. Still write the file.
- For each candidate, use cn_stock.py --history to validate entry trigger (§3) and set ATR stop (§4A).
- Per-slot: ~¥25,000 at T+1 open, shares = floor(25000 / entry / 100) × 100.
- cap-NG or 5+ boards → flag and explicitly say "不建议".
- If chold.md has holdings, add 持仓检查 section at bottom with framed.md §4 checks (ATR stop, day-5 time stop <+2%, +8%/+15% fixed TP).
- If a tool fails (offline/blocked), tell me and I'll paste data.

Tone: terse, decisive, executable. Account & risk slice are in framed.md — don't ask me for them.

==

"check today's date and Run the A-share session per framed.md + steps.md: gate, scan, validate, produce 0–3 buyable bullets with exact prices/shares/stops, then check c/main/chold.md holdings per §4. Write everything to c/main/watchlistd.md."
