#!/usr/bin/env python3
"""
Generate formatted bought.md via DeepSeek API.

Reads raw tool output + frame.md + uprompt.md + bought.md,
calls DeepSeek chat API, writes u/bought.md preserving
持仓 and 已平仓 sections from the existing file.
"""

import os, sys, json, argparse, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent   # u/utool -> u/

API_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"
MAX_TOKENS = 4096
TEMPERATURE = 0.3   # low temp for consistent formatting


def read_file(path):
    p = Path(path)
    if not p.exists():
        return f"(file not found: {p.name})"
    return p.read_text(encoding="utf-8")


def build_prompt(raw_report, frame, uprompt, bought):
    """Assemble the user message with all context."""
    return f"""=== RAW TOOL OUTPUT ===
{raw_report}

=== FRAME.MD (trading rules) ===
{frame}

=== UPROMPT.MD (output format specification) ===
{uprompt}

=== BOUGHT.MD (current state) ===
{bought}

---
Generate the daily brief per uprompt.md format.
IMPORTANT:
- Write ONLY 闸门 + A类入场卡 + 行动摘要 sections
- Do NOT write 当前持仓 or 已平仓 — those are preserved from the existing file
- A-class entry cards: both directions (突破买入 / 回踩买入)
- Buy-stop prices, stop-loss, position sizing per frame.md risk rules
- Chinese for commentary, English for tickers/numbers
- Terse, decisive, executable
- Output ONLY the markdown, no preamble."""


def call_deepseek(system_prompt, user_message):
    api_key = os.environ.get("_API_KEY")
    if not api_key:
        raise RuntimeError("_API_KEY not set")

    # Use curl to avoid adding requests as dependency for akshare env
    import urllib.request
    import urllib.error

    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(API_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"]
        return content
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"API error {e.code}: {body}")


def extract_sections(text):
    """Split text into: top (before ## 当前持仓), holdings (## 当前持仓), closed (## 已平仓)."""
    import re
    top = text
    holdings = ""
    closed = ""

    m = re.search(r'\n## 当前持仓.*', text, re.DOTALL)
    if m:
        top = text[:m.start()]
        rest = m.group(0)
        c = re.search(r'\n## 已平仓.*', rest, re.DOTALL)
        if c:
            holdings = rest[:c.start()]
            closed = c.group(0)
        else:
            holdings = rest
    return top, holdings, closed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(ROOT / "bought.md"),
                    help="Path to raw tool output (default: u/bought.md)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw_report = read_file(args.report)
    frame = read_file(ROOT / "frame.md")
    uprompt = read_file(ROOT / "uprompt.md")
    bought = read_file(ROOT / "bought.md")

    # Preserve 持仓 and 已平仓 from existing bought.md
    _, holdings, closed = extract_sections(bought)

    system_prompt = (
        "You are an expert US stock trading analyst. "
        "Generate a daily brief in the EXACT format specified in UPROMPT.MD. "
        "Apply all rules from FRAME.MD strictly. "
        "Output valid markdown only — no explanations before or after."
    )

    user_message = build_prompt(raw_report, frame, uprompt, bought)
    result = call_deepseek(system_prompt, user_message)

    # Merge AI output with preserved sections
    ai_top, _, _ = extract_sections(result)  # strip any AI-generated sections
    final = ai_top.rstrip() + "\n\n" + holdings.rstrip()
    if closed.strip():
        final += "\n\n" + closed.rstrip()

    if args.dry_run:
        print(final)
    else:
        out = ROOT / "bought.md"
        out.write_text(final, encoding="utf-8")
        print(f"✓ Wrote {out}  ({len(final)} chars)")


if __name__ == "__main__":
    main()
