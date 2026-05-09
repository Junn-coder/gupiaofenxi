import os
import time
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import pandas as pd
import requests
import akshare as ak

WHITELIST = [
    {"code": "002916", "name": "深南电路", "sector": "PCB"},
    {"code": "603986", "name": "兆易创新", "sector": "存储芯片"},
    {"code": "688012", "name": "中微公司", "sector": "半导体设备"},
    {"code": "688041", "name": "海光信息", "sector": "算力芯片"},
    {"code": "300750", "name": "宁德时代", "sector": "电池"},
    {"code": "300124", "name": "汇川技术", "sector": "工控"},
    {"code": "603129", "name": "春风动力", "sector": "出海"},
    {"code": "000733", "name": "振华科技", "sector": "军工电子"},
    {"code": "002179", "name": "中航光电", "sector": "军工电子"},
    {"code": "601899", "name": "紫金矿业", "sector": "铜金"},
    {"code": "600111", "name": "北方稀土", "sector": "稀土"},
]

def get_q1_growth(stock_code):
    try:
        profit_df = ak.stock_profit_sheet_by_report_em(symbol=stock_code)
        if profit_df is None or profit_df.empty:
            return None, None
        profit_df = profit_df.sort_values("报告期", ascending=False)
        if len(profit_df) < 2:
            return None, None
        q1_current = profit_df[profit_df["报告期"].str.startswith("2026-03-31")]
        q1_prev = profit_df[profit_df["报告期"].str.startswith("2025-03-31")]
        if q1_current.empty or q1_prev.empty:
            return None, None
        current_profit = q1_current.iloc[0]["净利润"]
        prev_profit = q1_prev.iloc[0]["净利润"]
        profit_growth = (current_profit - prev_profit) / abs(prev_profit) * 100 if prev_profit != 0 else None
        revenue_current = q1_current.iloc[0]["营业总收入"]
        revenue_prev = q1_prev.iloc[0]["营业总收入"]
        revenue_growth = (revenue_current - revenue_prev) / abs(revenue_prev) * 100 if revenue_prev != 0 else None
        return revenue_growth, profit_growth
    except Exception as e:
        print(f"获取 {stock_code} 财务数据出错: {e}")
        return None, None

def screen_growth_stocks():
    candidates = []
    for item in WHITELIST:
        code = item["code"]
        name = item["name"]
        print(f"正在分析 {name} ({code}) ...")
        revenue_growth, profit_growth = get_q1_growth(code)
        if revenue_growth is None or profit_growth is None:
            print(f"  -> 数据缺失，跳过")
            continue
        print(f"  -> 营收增长 {revenue_growth:.2f}%，净利增长 {profit_growth:.2f}%")
        if profit_growth > 100 and revenue_growth > 30:
            candidates.append({
                "code": code,
                "name": name,
                "sector": item["sector"],
                "revenue_growth": round(revenue_growth, 2),
                "profit_growth": round(profit_growth, 2),
            })
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
        print(f"myai分析 {stock_info['name']} 失败: {e}")
        return "分析失败，请稍后重试。"

def analyze_yyg(api_key):
    try:
        real = ak.stock_zh_a_hist(symbol="601166", period="daily", adjust="qfq")
        last = real.iloc[-1]
        price = last["收盘"]
        change = last["涨跌幅"]
    except:
        price = "N/A"
        change = "N/A"
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
        print(f"兴业银行分析失败: {e}")
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
            </table>
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
        candidates_html += "<p>今日白名单中未筛选出符合条件（净利同比>100% 且 营收同比>30%）的高成长股。</p>"

    yyg_html = f"""
    <h2>🏦 监控股票：兴业银行 (601166)</h2>
    <pre>{yyg_analysis}</pre>
    """

    full_html = f"""
    <html>
    <head><meta charset="UTF-8"></head>
    <body>
        <h1>每日股市投资简报 - {date_str}</h1>
        {candidates_html}
        <hr>
        {yyg_html}
        <hr>
        <p style="color: gray;">⚠️ 本报告由GitHub Actions自动生成，数据来源于AKShare，分析由AI提供，不构成投资建议。</p>
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

    candidates = screen_growth_stocks()
    yyg_analysis = analyze_yyg(my_key)
    send_email(candidates, yyg_analysis, smtp_user, smtp_pwd, to_email)

if __name__ == "__main__":
    main()