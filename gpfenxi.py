# daily_analysis.py
import os
import time
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import pandas as pd
import requests
import akshare as ak

# ------------------------------------------------------------
# 1. 高成长赛道白名单（股票代码 + 名称）
#    以下名单涵盖 AI/半导体、新能源、军工电子、涨价资源品
# ------------------------------------------------------------
WHITELIST = [
    # AI算力与半导体
    {"code": "002916", "name": "深南电路", "sector": "PCB"},
    {"code": "603986", "name": "兆易创新", "sector": "存储芯片"},
    {"code": "688012", "name": "中微公司", "sector": "半导体设备"},
    {"code": "688041", "name": "海光信息", "sector": "算力芯片"},
    # 新能源与高端制造
    {"code": "300750", "name": "宁德时代", "sector": "电池"},
    {"code": "300124", "name": "汇川技术", "sector": "工控"},
    {"code": "603129", "name": "春风动力", "sector": "出海"},
    # 军工电子（振华科技、中航光电）
    {"code": "000733", "name": "振华科技", "sector": "军工电子"},
    {"code": "002179", "name": "中航光电", "sector": "军工电子"},
    # 涨价资源品
    {"code": "601899", "name": "紫金矿业", "sector": "铜金"},
    {"code": "600111", "name": "北方稀土", "sector": "稀土"},
]

# ------------------------------------------------------------
# 2. 获取单只股票的一季度财务数据（营收同比增长、净利同比增长）
# ------------------------------------------------------------
def get_q1_growth(stock_code):
    """
    返回 (revenue_growth, profit_growth)
    若获取失败或数据不足，返回 (None, None)
    """
    try:
        # 获取利润表（按报告期）
        profit_df = ak.stock_profit_sheet_by_report_em(symbol=stock_code)
        if profit_df is None or profit_df.empty:
            return None, None
        # 提取最近两个报告期的净利润（用于同比）
        profit_df = profit_df.sort_values("报告期", ascending=False)
        if len(profit_df) < 2:
            return None, None
        # 2026年一季报（报告期格式如 "2026-03-31"）
        q1_current = profit_df[profit_df["报告期"].str.startswith("2026-03-31")]
        q1_prev = profit_df[profit_df["报告期"].str.startswith("2025-03-31")]
        if q1_current.empty or q1_prev.empty:
            return None, None
        current_profit = q1_current.iloc[0]["净利润"]
        prev_profit = q1_prev.iloc[0]["净利润"]
        profit_growth = (current_profit - prev_profit) / abs(prev_profit) * 100 if prev_profit != 0 else None

        # 营收同比增长（使用营业总收入）
        revenue_current = q1_current.iloc[0]["营业总收入"]
        revenue_prev = q1_prev.iloc[0]["营业总收入"]
        revenue_growth = (revenue_current - revenue_prev) / abs(revenue_prev) * 100 if revenue_prev != 0 else None

        return revenue_growth, profit_growth
    except Exception as e:
        print(f"获取 {stock_code} 财务数据出错: {e}")
        return None, None

# ------------------------------------------------------------
# 3. 筛选高成长股（净利润同比>100%，营收同比>30%）
# ------------------------------------------------------------
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

# ------------------------------------------------------------
# 4. 调用 DeepSeek API 分析单只股票
# ------------------------------------------------------------
def analyze_stock_with_deepseek(stock_info, api_key):
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
        print(f"DeepSeek分析 {stock_info['name']} 失败: {e}")
        return "分析失败，请稍后重试。"

# ------------------------------------------------------------
# 5. 分析兴业银行（保持不变）
# ------------------------------------------------------------
def analyze_yyg(api_key):
    # 获取兴业银行最新行情
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

# ------------------------------------------------------------
# 6. 发送HTML邮件（分两栏 + 表格）
# ------------------------------------------------------------
def send_email(candidates, yyg_analysis, smtp_user, smtp_password, to_email):
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 构建高成长候选股票表格
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
            # 调用DeepSeek获取详细分析（为避免API过载，这里只展示摘要，但你可以选择全量）
            analysis_text = analyze_stock_with_deepseek(c, os.getenv("DEEPSEEK_API_KEY"))
            # 简单提取评级和预期（实际可从analysis_text中正则提取，这里简化）
            rating = "待分析"
            target_range = "待分析"
            # 你可以将analysis_text完整放入表格，但会导致表格过长，故放在折叠区域
            candidates_html += f"""
                <tr>
                    <td>{c['code']}</td><td>{c['name']}</td><td>{c['sector']}</td>
                    <td>{c['revenue_growth']}</td><td>{c['profit_growth']}</td>
                    <td>{rating}</td><td>{target_range}</td>
                </tr>
                <tr style="background-color: #fafafa;"><td colspan="7"><details><summary>📝 详细分析</summary><pre>{analysis_text}</pre></details></td></tr>
            """
            time.sleep(1)  # 避免API请求过快
        candidates_html += "</table>"
    else:
        candidates_html += "<p>今日白名单中未筛选出符合条件（净利同比>100% 且 营收同比>30%）的高成长股。</p>"

    # 兴业银行分析部分
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
        <p style="color: gray;">⚠️ 本报告由GitHub Actions自动生成，数据来源于AKShare，分析由DeepSeek API提供，不构成投资建议。</p>
    </body>
    </html>
    """

    # 发送邮件
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

# ------------------------------------------------------------
# 7. 主函数
# ------------------------------------------------------------
def main():
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pwd = os.getenv("SMTP_PASSWORD")
    to_email = os.getenv("TO_EMAIL")

    if not all([deepseek_key, smtp_user, smtp_pwd, to_email]):
        raise ValueError("请确保GitHub Secrets中配置了DEEPSEEK_API_KEY, SMTP_USER, SMTP_PASSWORD, TO_EMAIL")

    # 筛选高成长股
    candidates = screen_growth_stocks()
    # 分析兴业银行
    yyg_analysis = analyze_yyg(deepseek_key)
    # 发送邮件
    send_email(candidates, yyg_analysis, smtp_user, smtp_pwd, to_email)

if __name__ == "__main__":
    main()