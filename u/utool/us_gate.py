#!/usr/bin/env python3
"""US market gate check — SPY, VIX, distribution days. Writes to stdout."""
import yfinance as yf
import sys

spy = yf.download('SPY', period='3mo', auto_adjust=False)
vix = yf.download('^VIX', period='1mo', auto_adjust=False)

spy_close = float(spy['Close'].iloc[-1].iloc[0])
spy_50ma = float(spy['Close'].rolling(50).mean().iloc[-1].iloc[0])
vix_close = float(vix['Close'].iloc[-1].iloc[0])
spy_high = float(spy['Close'].max().iloc[0])
ddraw = (spy_close / spy_high - 1) * 100

above = spy_close > spy_50ma

# Determine tier
if vix_close < 20 and above and spy_close / spy_high > 0.90:
    tier = 1
    label = "健康 — 可正常建仓/加仓"
elif vix_close > 30 or not above:
    tier = 3
    label = "高风险 — 只减不加/现金为王"
else:
    tier = 2
    label = "谨慎 — 停止新建仓"

print(f"SPY={spy_close:.0f}  50MA={spy_50ma:.0f}  above={above}  VIX={vix_close:.1f}  距3月高{ddraw:+.1f}%")
print(f"档位: {tier} ({label})")
