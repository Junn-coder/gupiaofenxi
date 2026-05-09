import os
import time
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import pandas as pd
import requests
import yfinance as yf
import baostock as bs

# 调试日志收集器
debug_logs = []

def log_debug(msg):
    print(msg)
    debug_logs.append(msg)

WHITELIST = [
    {"code": "603629", "name": "利通电子", "sector": "AI算力租赁"},
    {"code": "688610", "name": "埃科光电", "sector": "机器视觉"},
    {"code": "002266", "name": "浙富控股", "sector": "资源化/清洁能源"},
    {"code": "301162", "name": "国能日新", "sector": "新能源数字化"},
    {"code": "003010", "name": "若羽臣", "sector": "电商运营转型"},
]

def get_q1_growth(stock_code):
    """
    使用 baostock 获取季度利润同比增长率
    返回 (revenue_growth, profit_growth, debug_info)
    """
    debug_info = []
    try:
        lg = bs.login()
        if lg.error_code != '0':
            debug_info.append(f"baostock登录失败: {lg.error_msg}")
            log_debug(f"  ❌ {stock_code}: baostock登录失败")
            return None, None, "\n".join(debug_info)

        if stock_code.startswith('6'):
            bs_code = f"sh.{stock_code}"
        else:
            bs_code = f"sz.{stock_code}"

        profit_data = []
        for year in [2025, 2026]:
            rs_profit = bs.query_profit_data(code=bs_code, year=year, quarter=1)
            if rs_profit.error_code == '0':
                while rs_profit.next():
                    row = rs_profit.get_row_data()
                    # 根据 baostock 文档，字段顺序为: code, year, quarter, roe, netProfit, eps, revenue, profitTotal, operateProfit, yoyNetProfit, yoyRevenue
                    # 我们只需要 netProfit (索引4) 和 revenue (索引6)
                    if len(row) >= 7:
                        profit_data.append({
                            'year': row[1],
                            'net_profit': float(row[4]) if row[4] else 0.0,
                            'revenue': float(row[6]) if row[6] else 0.0
                        })
                    else:
                        debug_info.append(f"返回数据列数不足: {len(row)}")
            else:
                debug_info.append(f"获取{year}Q1利润表失败: {rs_profit.error_msg}")
        bs.logout()

        if len(profit_data) < 2:
            debug_info.append(f"不足两个季度的利润数据，实际获取到{len(profit_data)}条")
            return None, None, "\n".join(debug_info)

        df = pd.DataFrame(profit_data)
        df = df.sort_values('year')
        q2025 = df[df['year'] == '2025'].iloc[0]
        q2026 = df[df['year'] == '2026'].iloc[0]

        if q2025['net_profit'] == 0 or q2025['revenue'] == 0:
            debug_info.append("同期净利或营收为0，无法计算增长率")
            return None, None, "\n".join(debug_info)

        profit_growth = (q2026['net_profit'] - q2025['net_profit']) / abs(q2025['net_profit']) * 100
        revenue_growth = (q2026['revenue'] - q2025['revenue']) / abs(q2025['revenue']) * 100

        debug_info.append(f"baostock: 2025Q1净利={q2025['net_profit']:.2f}, 2026Q1净利={q2026['net_profit']:.2f} -> 增长{profit_growth:.2f}%")
        debug_info.append(f"营收增长{revenue_growth:.2f}%")
        return revenue_growth, profit_growth, "\n".join(debug_info)
    except Exception as e:
        err_msg = f"baostock异常: {str(e)}"
        debug_info.append(err_msg)
        log_debug(f"  ❌ {stock_code}: {err_msg}")
        return None, None, "\n".join(debug_info)

def screen_growth_stocks():
    candidates = []
    for item in WHITELIST:
        code = item["code"]
        name = item["name"]
        log_debug(f"正在分析 {name} ({code}) ...")
        revenue_growth, profit_growth, debug_info = get_q1_growth(code)
        if revenue_growth is None or profit_growth is None:
            log_debug(f"  -> 数据缺失，跳过 (调试: {debug_info})")
            continue
        log_debug(f"  -> 营收增长 {revenue_growth:.2f}%，净利增长 {profit_growth:.2f}%")
        if profit_growth > 30 and revenue_growth > 20:
            candidates.append({
                "code": code,
                "name": name,
                "sector": item["sector"],
                "revenue_growth": round(revenue_growth, 2),
                "profit_growth": round(profit_growth, 2),
                "debug": debug_info
            })
            log_debug(f"  ✅ 符合条件，加入候选")
        else:
            log_debug(f"  ❌ 不符合条件 (净利>{profit_growth:.1f} 需>30 或 营收>{revenue_growth:.1f} 需>20)")
    return candidates

def analyze_stock_with_myai(stock_info, api_key):
    prompt = f"""
请分析以下A股股票的投资价值，重点关注3-6个月是否有30%-50%上涨潜力：
- 股票名称：{stock_info['name']}（{stock_info['code']}）
- 所属赛道：{stock_info['sector']}
- 一季度净利润同比：{stock_info['profit_growth']}%
- 一季度营收同比：{stock_info['revenue_growth']}%

输出格式：
1. 核心成长逻辑（2-3点）
2. 主要风险（2点）
3. 综合评级：A（强烈看好）/B（一般）/C（回避）
4. 3-6个月预期涨幅区间：xx%
"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    try:
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log_debug(f"myai分析 {stock_info['name']} 失败: {e}")
        return "分析失败，请稍后重试。"

def analyze_yyg(api_key):
    try:
        ticker = yf.Ticker("601166.SS")
        hist = ticker.history(period="2d")
        if not hist.empty:
            price = hist['Close'].iloc[-1]
            if len(hist) > 1:
                prev_close = hist['Close'].iloc[-2]
                change = (price - prev_close) / prev_close * 100
            else:
                change = 0.0
        else:
            price, change = "N/A", "N/A"
    except Exception as e:
        log_debug(f"获取兴业银行行情失败: {e}")
        price, change = "N/A", "N/A"
    prompt = f"""
兴业银行（601166）最新数据：
- 收盘价：{price}
- 涨跌幅：{change}%
请结合当前低利率环境、银行板块整体估值及公司不良率等指标，给出简短分析和操作建议。
"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    try:
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log_debug(f"兴业银行分析失败: {e}")
        return "分析失败。"

def send_email(candidates, yyg_analysis, smtp_user, smtp_password, to_email):
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    candidates_html = "<h2>📈 今日高成长股筛选结果（白名单）</h2>"
    if candidates:
        candidates_html += """
        <table border="1" cellpadding="6" style="border-collapse: collapse; width: 100%; font-family: Arial;">
            <tr style="background-color: #f2f2f2;">
                <th>股票代码</th><th>股票名称</th><th>赛道</th>
                <th>营收同比(%)</th><th>净利同比(%)</th><th>AI综合评级</th><th>预期涨幅</th>
            </tr>
        """
        for c in candidates:
            analysis_text = analyze_stock_with_myai(c, os.getenv("_API_KEY"))
            rating = "待分析"
            target_range = "待分析"
            candidates_html += f"""
                <tr>
                    <td>{c['code']}</td><td>{c['name']}</td><td>{c['sector']}</td>
                    <td>{c['revenue_growth']}</td><td>{c['profit_growth']}</td>
                    <td>{rating}</td><td>{target_range}</td>
                </tr>
                <tr style="background-color: #fafafa;"><td colspan="7"><details><summary>📝 详细分析</summary><pre>{analysis_text}</pre></details></td></tr>
            """
            time.sleep(1)
        candidates_html += "</table>"
    else:
        candidates_html += "<p>今日白名单中未筛选出符合条件（净利同比>30% 且 营收同比>20%）的高成长股。</p>"

    yyg_html = f"""
    <h2>🏦 监控股票：兴业银行 (601166)</h2>
    <pre>{yyg_analysis}</pre>
    """

    debug_html = "<h2>🔧 调试日志</h2><details><summary>点击展开</summary><pre>" + "\n".join(debug_logs) + "</pre></details>"

    full_html = f"""
    <html>
    <head><meta charset="UTF-8"></head>
    <body>
        <h1>每日股市投资简报 - {date_str}</h1>
        {candidates_html}
        <hr>
        {yyg_html}
        <hr>
        {debug_html}
        <hr>
        <p style="color: gray;">⚠️ 本报告由GitHub Actions自动生成，数据来源于baostock/yfinance，分析由AI提供，不构成投资建议。</p>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"高成长股筛选 + 兴业银行分析 - {date_str}"
    msg["From"] = smtp_user
    msg["To"] = to_email
    part = MIMEText(full_html, "html")
    msg.attach(part)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, to_email, msg.as_string())
    print("邮件发送成功")

def main():
    my_key = os.getenv("_API_KEY")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pwd = os.getenv("SMTP_PASSWORD")
    to_email = os.getenv("TO_EMAIL")

    if not all([my_key, smtp_user, smtp_pwd, to_email]):
        raise ValueError("请确保GitHub Secrets中配置了_API_KEY, SMTP_USER, SMTP_PASSWORD, TO_EMAIL")

    log_debug("========== 开始执行筛选 ==========")
    candidates = screen_growth_stocks()
    log_debug(f"筛选完成，共找到 {len(candidates)} 只符合条件的股票")
    log_debug("========== 开始分析兴业银行 ==========")
    yyg_analysis = analyze_yyg(my_key)
    log_debug("========== 发送邮件 ==========")
    send_email(candidates, yyg_analysis, smtp_user, smtp_pwd, to_email)
    log_debug("========== 全部完成 ==========")

if __name__ == "__main__":
    main()