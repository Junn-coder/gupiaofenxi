#!/usr/bin/env python3
"""
send_watchlist.py — run daily scan pipeline, email watchlistd.md format.
Same output as cprompt.md + steps.md manual flow.
"""

import os
import sys
import subprocess
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, cwd=HERE, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", 1


def cap_ok(cap_str):
    try:
        return 30 <= float(cap_str) <= 500
    except (ValueError, TypeError):
        return False


def step_gate():
    out, _, _ = run("python index.py")
    lines = []
    for line in out.split("\n"):
        s = line.strip()
        if any(k in s for k in ["上证综指", "创业板指", "沪深300"]):
            lines.append(s)
        if "limit-ups" in s.lower() or "warming" in s.lower() or "neutral" in s.lower() or "freeze" in s.lower():
            lines.append(s)
        if "[Verdict]" in s:
            lines.append(s)
    return "\n".join(lines)


def step_scan():
    out, _, _ = run("python scan_cn.py")
    top3, backups, top3_codes = [], [], set()
    current_sector = ""
    section = None

    for line in out.split("\n"):
        if "[Final shortlist" in line:
            section = "shortlist"
            continue
        if "[Full leader breakdown" in line:
            section = "leader"
            continue
        if section == "shortlist" and line.strip().startswith(("1  ", "2  ", "3  ")):
            parts = line.split()
            if len(parts) >= 9:
                top3.append(dict(
                    code=parts[1], name=parts[2], sector=parts[3],
                    boards=parts[4], first=parts[5], cap_str=parts[8],
                    flags=" ".join(parts[9:]) if len(parts) > 9 else "",
                ))
                top3_codes.add(parts[1])
        if section == "shortlist" and not line.strip():
            section = None
        if section == "leader":
            s = line.strip()
            if s.startswith("* "):
                current_sector = s[2:]
                continue
            if "code" in s and "name" in s:
                continue
            if s and s[0].isdigit() and not s.startswith("202"):
                parts = s.split()
                if len(parts) >= 7:
                    code = parts[0]
                    if code not in top3_codes and code.isdigit() and len(code) == 6:
                        backups.append(dict(
                            code=code, name=parts[1], sector=current_sector,
                            boards=parts[2], first=parts[3], cap_str=parts[6],
                            flags=" ".join(parts[7:]) if len(parts) > 7 else "",
                        ))
        if section == "leader" and not s:
            current_sector = ""

    backups.sort(key=lambda c: (0 if cap_ok(c["cap_str"]) else 1,
                                 float(c["cap_str"]) if cap_ok(c["cap_str"]) else 9999))
    return top3, backups


def step_quote(code):
    out, _, _ = run(f"python cn_stock.py {code}")
    info = {}
    for line in out.split("\n"):
        if "最新:" in line:
            info["price"] = line.split()[1]
        elif "开:" in line:
            for p in line.split():
                if "开:" in p: info["open"] = p.split(":")[1]
                if "高:" in p: info["high"] = p.split(":")[1]
                if "低:" in p: info["low"] = p.split(":")[1]
                if "昨收:" in p: info["prev"] = p.split(":")[1]
    return info


def is_gap_seal(o, h, prev):
    try:
        return float(o) >= float(prev) * 1.09 and abs(float(o) - float(h)) < 0.01
    except (ValueError, TypeError):
        return False


def build_md(gate_text, top3, backups):
    today = datetime.datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][today.weekday()]

    table = "| # | code   | name   | sector | 市值      | 连板 | flag   |\n"
    table += "| - | ------ | ------ | ------ | --------- | ---- | ------ |\n"
    for i, c in enumerate(top3):
        cap = c["cap_str"]
        ok = "v" if cap_ok(cap) else "x"
        q = step_quote(c["code"])
        gs = is_gap_seal(q.get("open", "?"), q.get("high", "?"), q.get("prev", "?"))
        bd = c["boards"]
        bd_flag = ""
        if gs:
            bd_flag = "，一字板无法买入"
        elif not cap_ok(cap):
            bd_flag = ""
        elif bd.isdigit() and int(bd) >= 5:
            bd_flag = "，高位"
        flag = bd_flag if bd_flag else c.get("flags", "")
        table += f"| {i+1} | {c['code']} | {c['name']} | {c['sector']} | {cap}亿 {ok} | {bd}板 | {flag.strip()} |\n"

    backup_table = ""
    if backups:
        backup_table = "\n替补：\n\n"
        backup_table += "| # | code   | name   | 市值      | 连板 | 首封  | flag             |\n"
        backup_table += "| - | ------ | ------ | --------- | ---- | ----- | ---------------- |\n"
        for i, c in enumerate(backups[:5]):
            cap = c["cap_str"]
            ok = "v" if cap_ok(cap) else "x"
            q = step_quote(c["code"])
            gs = is_gap_seal(q.get("open", "?"), q.get("high", "?"), q.get("prev", "?"))
            if gs:
                flag = "一字板无法买入"
            elif not cap_ok(cap):
                flag = "cap-NG"
            else:
                flag = "cap-OK，未一字板"
            backup_table += f"| {i+1} | {c['code']} | {c['name']} | {cap}亿 {ok} | {c['boards']}板 | {c['first']} | {flag} |\n"

    buyable = None
    for c in top3 + backups:
        q = step_quote(c["code"])
        gs = is_gap_seal(q.get("open", "?"), q.get("high", "?"), q.get("prev", "?"))
        high_bd = c["boards"].isdigit() and int(c["boards"]) >= 5
        if cap_ok(c["cap_str"]) and not gs and not high_bd:
            buyable = (c, q.get("price", "?"))
            break

    buy_section = ""
    reject_list = []
    for c in top3:
        q = step_quote(c["code"])
        gs = is_gap_seal(q.get("open", "?"), q.get("high", "?"), q.get("prev", "?"))
        reason = ""
        if gs:
            reason = "一字板无法买入"
        elif not cap_ok(c["cap_str"]):
            reason = f"cap-NG {c['cap_str']}亿"
        elif c["boards"].isdigit() and int(c["boards"]) >= 5:
            reason = f"{c['boards']}连板高位风险"
        if reason:
            reject_list.append(f"{c['code']} {c['name']}（{reason}）")

    if buyable:
        c, price = buyable
        entry = float(price)
        shares = int(25000 / entry / 100) * 100
        stop = round(entry * 0.95, 2)
        tp1 = round(entry * 1.08, 2)
        tp2 = round(entry * 1.15, 2)
        limit_p = round(entry * 1.10, 2)
        buy_section = (
            f"> 1）{c['code']} {c['name']} — {c['sector']}\n"
            f">\n"
            f"> 考虑买入的价格范围和量是：{entry}（T+1 开盘），{shares} 股 ~{shares*entry:,.0f}；"
            f"不能买入的价格是：{limit_p} 及以上（涨停一字板）\n"
            f">\n"
            f"> 止损价格是：{stop}（ATR 1.0x，max(5%, cap 10%)）\n"
            f">\n"
            f"> 考虑止盈的价格是：TP1 {tp1}（+8%）出一半，TP2 {tp2}（+15%）清仓\n"
            f">\n"
            f"> 可以加仓的价格是：不加仓\n"
        )
    reject_line = f"> 2）不建议{'、'.join(reject_list)}。" if reject_list else ""

    amber_note = ""
    if "AMBER" in gate_text:
        amber_note = "\n> AMBER 退潮：最多 2 槽。按候选顺序择优 1-2 只，不追一字板。\n"

    return f"""# watchlistd — Short-term swing watchlist (paired with framed.md)

## {date_str} ({weekday})

闸门：
{gate_text}

{table}
{backup_table}
建议：

{buy_section}
{reject_line}
{amber_note}
"""


def send_email(md_body):
    smtp_user = os.getenv("SMTP_USER")
    smtp_pwd = os.getenv("SMTP_PASSWORD")
    to_email = os.getenv("TO_EMAIL")
    if not all([smtp_user, smtp_pwd, to_email]):
        print("Missing SMTP env vars, skipping email.")
        return

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    html = f"""<html><head><meta charset="UTF-8"></head><body>
<pre style="font-family:Consolas,monospace;white-space:pre-wrap;">{md_body}</pre>
<p style="color:gray;font-size:12px;">Auto-generated by GitHub Actions (daily scan). Not investment advice.</p>
</body></html>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"A 股每日扫描 — {date_str}"
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_pwd)
        server.sendmail(smtp_user, to_email, msg.as_string())
    print("Email sent.")


def main():
    print("=== Gate ===")
    gate = step_gate()
    print(gate[:200])

    print("=== Scan ===")
    top3, backups = step_scan()
    print(f"  top3: {len(top3)}, backups: {len(backups)}")

    md = build_md(gate, top3, backups)
    print(md[:500])

    print("=== Send ===")
    send_email(md)
    print("Done.")


if __name__ == "__main__":
    main()
