#!/usr/bin/env python3
"""Fallback: write raw tool output to bought.md, preserving 持仓/已平仓."""
import os, re, sys

date = os.environ.get("BRIEF_DATE", "unknown")
bought_path = os.environ.get("BOUGHT_PATH", "u/bought.md")
report_path = os.environ.get("REPORT_PATH", "/tmp/us_report.txt")

text = open(bought_path, encoding="utf-8").read() if os.path.exists(bought_path) else ""
m = re.search(r'\n## 当前持仓.*', text, re.DOTALL)
preserved = m.group(0) if m else ""

header = f"# US Stock Daily Brief — {date} (美东)\n\n> 全量 TT 表 + 逐赛道分析 → uwatchlist.md\n\n"
raw = open(report_path, encoding="utf-8").read()

open(bought_path, "w", encoding="utf-8").write(header + raw + "\n\n" + preserved)
print(f"Fallback wrote {bought_path} ({len(header + raw + preserved)} chars)")
