#!/usr/bin/env python3
"""
Generate formatted current.md via DeepSeek API.

Reads raw tool output + frame.md + uprompt.md + bought.md,
calls DeepSeek chat API, writes u/current.md in the manual style
(闸门 + A类入场卡双方向 + 持仓检查 + 行动摘要).

Usage:
    python build_brief.py                        # uses u/current.md (raw tool output)
    python build_brief.py --report /tmp/us_report.txt  # explicit input
    python build_brief.py --dry-run               # print to stdout, don't write

Env:
    _API_KEY           required
    Workspace root is inferred as two dirs above this script.

Cost: ~$0.01-0.02 per run (DeepSeek V3 chat).
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


def build_prompt(raw_report, frame, uprompt, bought, uwatchlist):
    """Assemble the user message with all context."""
    return f"""=== RAW TOOL OUTPUT ===
{raw_report}

=== FRAME.MD (trading rules) ===
{frame}

=== UPROMPT.MD (output format specification) ===
{uprompt}

=== BOUGHT.MD (current holdings) ===
{bought}

=== UWATCHLIST.MD (watchlist context) ===
{uwatchlist}

---
Generate the final u/current.md per uprompt.md format.
IMPORTANT:
- Write A-class entry cards with both directions (突破买入 / 回踩买入)
- Include buy-stop prices, stop-loss, position sizing per frame.md risk rules
- Check holdings against current prices
- Write actionable summary bullets
- Use Chinese for all commentary, English for tickers/numbers
- Keep it terse, decisive, executable
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(ROOT / "current.md"),
                    help="Path to raw tool output (default: u/current.md)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw_report = read_file(args.report)
    frame = read_file(ROOT / "frame.md")
    uprompt = read_file(ROOT / "uprompt.md")
    bought = read_file(ROOT / "bought.md")
    uwatchlist = read_file(ROOT / "uwatchlist.md")

    system_prompt = (
        "You are an expert US stock trading analyst. "
        "Generate a daily brief in the EXACT format specified in UPROMPT.MD. "
        "Apply all rules from FRAME.MD strictly. "
        "Output valid markdown only — no explanations before or after."
    )

    user_message = build_prompt(raw_report, frame, uprompt, bought, uwatchlist)
    result = call_deepseek(system_prompt, user_message)

    if args.dry_run:
        print(result)
    else:
        out = ROOT / "current.md"
        out.write_text(result, encoding="utf-8")
        print(f"✓ Wrote {out}  ({len(result)} chars)")


if __name__ == "__main__":
    main()
