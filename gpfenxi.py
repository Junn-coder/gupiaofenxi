#!/usr/bin/env python3
"""
gpfenxi.py — A-share daily pipeline (runs lifchang tools, emails watchlistd format).
"""

import os
import sys
import subprocess
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

LIFCHANG = "/tmp/lifchang"
CTOOL = os.path.join(LIFCHANG, "c", "ctool")
CHOLD = os.path.join(LIFCHANG, "c", "chold.md")


def run(cmd, cwd=CTOOL, timeout=120):
    """Run a shell command, return (stdout, stderr, exit_code)."""
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", 1


def run_gate():
    """Step 1: index.py → gate verdict + detail."""
    out, err, rc = run("python index.py")
    verdict = "GATE_UNKNOWN"
    details = []
    for line in out.split("\n"):
        if "[Verdict]" in line:
            verdict = line.strip()
        # Capture index lines: "  上证综指 000001  ...  AMBER  broke the 10-day MA..."
        if line.strip() and any(k in line for k in ["上证综指", "创业板指", "沪深300"]):
            details.append(line.strip())
        # Capture sentiment
        if "limit-ups" in line or "warming" in line.lower() or "neutral" in line.lower() or "freeze" in line.lower():
            details.append(line.strip())
    return verdict, "<br>".join(details[-5:])  # last 5 relevant lines


def run_scan():
    """Step 2: scan_cn.py → top-3 shortlist + backup candidates from sector leaders."""
    out, err, rc = run("python scan_cn.py")   # full output, not --final 3
    top3 = []
    backups = []
    top3_codes = set()
    current_sector = ""
    in_table = False
    in_leader = False
    for line in out.split("\n"):
        # Final shortlist table
        if "[Final shortlist" in line:
            in_table = True
            in_leader = False
            continue
        if in_table and line.strip().startswith(("1  ", "2  ", "3  ")):
            parts = line.split()
            # col: # code name sector bd first brk turn% float(100M) flags...
            if len(parts) >= 9:
                flags = " ".join(parts[9:]) if len(parts) > 9 else ""
                top3.append({
                    "code": parts[1], "name": parts[2], "sector": parts[3],
                    "boards": int(parts[4]) if parts[4].isdigit() else parts[4],
                    "first": parts[5], "brk": parts[6],
                    "cap_str": parts[8], "flags": flags,
                })
                top3_codes.add(parts[1])
        if in_table and not line.strip():
            in_table = False

        # Full leader breakdown per sector → pick cap-OK leaders not in top3
        if "[Full leader breakdown" in line:
            in_leader = True
            in_table = False
            continue
        if in_leader and line.strip().startswith("* "):
            current_sector = line.strip()[2:]
            continue
        if in_leader and "code" in line and "name" in line:
            continue
        if in_leader and len(line.strip()) > 0 and line.strip()[0].isdigit() and not line.strip().startswith("202"):
            parts = line.split()
            if len(parts) >= 7:
                code = parts[0]
                if code not in top3_codes and code.isdigit() and len(code) == 6:
                    backups.append({
                        "code": code,
                        "name": parts[1],
                        "sector": current_sector,
                        "boards": int(parts[2]) if parts[2].isdigit() else parts[2],
                        "first": parts[3] if len(parts) > 3 else "?",
                        "brk": parts[4] if len(parts) > 4 else "?",
                        "turn": parts[5] if len(parts) > 5 else "?",
                        "cap_str": parts[6] if len(parts) > 6 else "?",
                        "flags": " ".join(parts[7:]) if len(parts) > 7 else "",
                    })
        if in_leader and not line.strip():
            current_sector = ""

    # Sort backups: cap-OK first, then smaller cap (= more short-term upside potential)
    backups.sort(key=lambda c: (
        0 if cap_ok(c.get("cap_str", "0")) else 1,
        float(c.get("cap_str", "9999")) if cap_ok(c.get("cap_str", "0")) else 9999
    ))

    print(f"  top3: {len(top3)}, backups: {len(backups)}")
    return top3, backups


def get_quote(code):
    """Step 3: cn_stock.py <code> → latest price, open, high, low, prev_close."""
    out, err, rc = run(f"python cn_stock.py {code}")
    info = {"price": None, "open": None, "high": None, "low": None, "prev_close": None}
    for line in out.split("\n"):
        line = line.strip()
        if "最新:" in line:
            info["price"] = line.split()[1]
        elif "开:" in line:
            # "开:8.74 高:9.28 低:8.74 昨收:8.44"
            for part in line.split():
                if "开:" in part: info["open"] = part.split(":")[1]
                if "高:" in part: info["high"] = part.split(":")[1]
                if "低:" in part: info["low"] = part.split(":")[1]
                if "昨收:" in part: info["prev_close"] = part.split(":")[1]
    return info


def read_chold():
    """Read existing holdings from chold.md."""
    if not os.path.exists(CHOLD):
        return []
    with open(CHOLD, "r", encoding="utf-8") as f:
        content = f.read()
    holdings = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit() and len(parts[0]) == 6:
            # active holding: "code qty cost"
            if "sold" not in line.lower():
                holdings.append({
                    "code": parts[0],
                    "qty": parts[1] if len(parts) > 1 else "?",
                    "cost": parts[2] if len(parts) > 2 else "?",
                })
    return holdings


def is_gap_seal(open_p, high_p, prev_close, board_limit=0.10):
    """Check if T+1 open is already at/above the limit (unfillable)."""
    try:
        o = float(open_p)
        h = float(high_p)
        p = float(prev_close)
        return o >= p * (1 + board_limit - 0.01) and abs(o - h) < 0.01
    except (ValueError, TypeError):
        return False


def add_buyable(c, price):
    """Return (added_bool, html_string) for a buyable candidate."""
    try:
        entry = float(price) if price and price != "?" else 0
        if entry <= 0:
            return False, ""
        shares = int(25000 / entry / 100) * 100
        amt = shares * entry
        stop = round(entry * 0.95, 2)
        tp1 = round(entry * 1.08, 2)
        tp2 = round(entry * 1.15, 2)
        html = f"""<p><strong>✅ {c['code']} {c['name']} — {c['sector']}</strong></p>
        <ul>
            <li>买入：T+1 开盘 ~¥{entry}，{shares} 股 ≈ ¥{amt:,.0f}</li>
            <li>止损：¥{stop}（ATR 1.0× max(5%, cap 10%)）</li>
            <li>止盈：TP1 ¥{tp1}（+8%）出一半，TP2 ¥{tp2}（+15%）清仓</li>
        </ul>"""
        return True, html
    except (ValueError, TypeError):
        return False, ""


def cap_ok(cap_str):
    """Check if float cap is in 30-500亿 range."""
    try:
        cap = float(cap_str)
        return 30 <= cap <= 500
    except (ValueError, TypeError):
        return False


def build_email(top3, backups, gate_verdict, gate_detail, holdings):
    """Build HTML email in watchlistd format with top3 + backup coverage."""
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # Gate row
    gate_html = f"<p><strong>闸门：{gate_verdict}</strong><br><small>{gate_detail}</small></p>"
    # Add AMBER/ebb note
    if "AMBER" in gate_verdict:
        gate_html += "<p><em>退潮 — 最多 2 槽，只做最强主线。</em></p>"

    # Candidates table (top3)
    table_rows = ""
    buyable_html = ""
    reject_html = ""
    all_candidates = top3 + backups
    buyable_found = False

    for i, c in enumerate(top3):
        cap_str = c.get("cap_str", "?")
        bd = c.get("boards", "?")
        flags_raw = c.get("flags", "")
        cap_ok_flag = "✓" if cap_ok(cap_str) else "✗"
        bd_flag = "⚠高位" if (isinstance(bd, int) and bd >= 5) else ""

        q = get_quote(c["code"])
        price = q.get("price", "?")
        open_p = q.get("open", "?")
        high_p = q.get("high", "?")
        prev = q.get("prev_close", "?")
        gs = is_gap_seal(open_p, high_p, prev)

        skip_reason = ""
        if gs:
            skip_reason = "一字板无法买入"
        elif not cap_ok(cap_str):
            skip_reason = f"cap-NG ({cap_str}亿)"
        elif isinstance(bd, int) and bd >= 5:
            skip_reason = f"{bd}连板高位风险"

        table_rows += f"""<tr>
            <td>{i+1}</td><td>{c['code']}</td><td>{c['name']}</td><td>{c['sector']}</td>
            <td>{cap_str}亿 {cap_ok_flag}</td><td>{bd}板</td>
            <td>{skip_reason or flags_raw}</td>
        </tr>"""

        if skip_reason:
            reject_html += f"<li>{c['code']} {c['name']} — {skip_reason}</li>"
        else:
            added, bh = add_buyable(c, price)
            if added:
                buyable_html += bh
                buyable_found = True
            else:
                reject_html += f"<li>{c['code']} {c['name']} — 价格获取失败</li>"

    # If no buyable from top3, try backups
    backup_html = ""
    if not buyable_found and backups:
        backup_html = "<h2>替补（板块 leader 中的 cap-OK）</h2><table border='1' cellpadding='6' style='border-collapse:collapse;'><tr style='background:#f2f2f2;'><th>#</th><th>code</th><th>name</th><th>市值</th><th>连板</th><th>首封</th><th>flag</th></tr>"
        for i, c in enumerate(backups[:5]):
            cap_str = c.get("cap_str", "?")
            bd = c.get("boards", "?")
            cap_ok_flag = "✓" if cap_ok(cap_str) else "✗"
            q = get_quote(c["code"])
            price = q.get("price", "?")
            open_p = q.get("open", "?")
            high_p = q.get("high", "?")
            prev = q.get("prev_close", "?")
            gs = is_gap_seal(open_p, high_p, prev)
            flag = "一字板" if gs else ("cap-NG" if not cap_ok(cap_str) else "cap-OK，未一字板")
            backup_html += f"<tr><td>{i+1}</td><td>{c['code']}</td><td>{c['name']}</td><td>{cap_str}亿 {cap_ok_flag}</td><td>{bd}板</td><td>{c.get('first','?')}</td><td>{flag}</td></tr>"
            if cap_ok(cap_str) and not gs and not buyable_found:
                added, bh = add_buyable(c, price)
                if added:
                    buyable_html += bh
                    buyable_found = True
        backup_html += "</table>"

    # Holdings check
    h_html = ""
    if holdings:
        h_html = "<h2>持仓检查</h2><ul>"
        for h in holdings:
            h_html += f"<li>{h['code']} — {h['qty']}股 @ ¥{h['cost']} — 需手动检查 framed.md §4</li>"
        h_html += "</ul>"
    else:
        h_html = "<p>无活跃持仓。</p>"

    return f"""
    <html><head><meta charset="UTF-8"></head><body>
        <h1>每日 A 股扫描 — {date_str}</h1>
        {gate_html}
        <h2>候选股</h2>
        <table border="1" cellpadding="6" style="border-collapse:collapse;font-family:Arial;">
            <tr style="background:#f2f2f2;">
                <th>#</th><th>code</th><th>name</th><th>sector</th><th>市值</th><th>连板</th><th>flag</th>
            </tr>
            {table_rows}
        </table>
        <h2>买入建议</h2>
        {buyable_html or "<p>无可买入候选（全部 cap-NG / 一字板 / 高位风险）。</p>"}
        {backup_html}
        <h2>排除</h2>
        <ul>{reject_html}</ul>
        <hr>
        {h_html}
        <hr>
        <p style="color:gray;font-size:12px;">Auto-generated by GitHub Actions. Rules per framed.md. Not investment advice.</p>
    </body></html>
    """


def send_email(html_body, smtp_user, smtp_password, to_email):
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"A 股每日扫描 — {date_str}"
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, to_email, msg.as_string())
    print("Email sent.")


def main():
    smtp_user = os.getenv("SMTP_USER")
    smtp_pwd = os.getenv("SMTP_PASSWORD")
    to_email = os.getenv("TO_EMAIL")
    if not all([smtp_user, smtp_pwd, to_email]):
        raise ValueError("Missing SMTP_USER / SMTP_PASSWORD / TO_EMAIL")

    print("=== Step 1: Gate ===")
    gate_verdict, gate_detail = run_gate()
    print(f"  {gate_verdict}")

    print("=== Step 2: Scan ===")
    top3, backups = run_scan()

    print("=== Step 3: Validate & Build ===")
    holdings = read_chold()
    html = build_email(top3, backups, gate_verdict, gate_detail, holdings)

    print("=== Step 4: Send ===")
    send_email(html, smtp_user, smtp_pwd, to_email)
    print("Done.")


if __name__ == "__main__":
    main()
