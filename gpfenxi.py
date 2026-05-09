import requests
import json
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import yfinance as yf
import os
from typing import Dict, Any

def fetch_market_data(ticker: str) -> Dict[str, Any]:
    """获取 A 股或港股目标股票的实时数据"""
    # 用 yfinance 获取美股/港股/A股数据（A股需加 .SS 或 .SZ 后缀）
    # 示例：兴业银行对应 A 股 "601166.SS"
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="5d")
        current_price = info.get('regularMarketPrice', 0)
        prev_close = info.get('previousClose', 0)
        change_pct = ((current_price - prev_close) / prev_close) * 100 if prev_close else 0
        return {
            "price": round(current_price, 2),
            "change_pct": round(change_pct, 2),
            "prev_close": prev_close
        }
    except Exception as e:
        print(f"获取股票数据失败: {e}")
        return {"price": 0, "change_pct": 0, "prev_close": 0}

def call_deepseek_api(prompt: str, api_key: str) -> str:
    """调用 DeepSeek API 进行分析"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    try:
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"调用 DeepSeek API 失败: {e}")
        return "暂无分析结果。"

def send_email(
    subject: str,
    body_html: str,
    to_email: str,
    smtp_server: str = "smtp.gmail.com",
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_password: str = ""
):
    """发送邮件"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    html_part = MIMEText(body_html, "html")
    msg.attach(html_part)
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, msg.as_string())
        print("邮件发送成功")
    except Exception as e:
        print(f"邮件发送失败: {e}")

def main():
    _api_key = os.getenv("_API_KEY")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    to_email = os.getenv("TO_EMAIL")
    ticker = os.getenv("TICKER_SYMBOL", "601166.SS")  # 兴业银行

    if not _api_key:
        raise ValueError("_api_key 未设置")
    if not smtp_user or not smtp_password:
        raise ValueError("SMTP 邮箱配置未设置")
    if not to_email:
        raise ValueError("TO_EMAIL 未设置")

    # 获取股票数据
    stock_data = fetch_market_data(ticker)
    prompt = f"""
请分析以下股票数据：
- 当前价格: {stock_data['price']}
- 涨跌幅: {stock_data['change_pct']}%
- 昨日收盘: {stock_data['prev_close']}
请给出简要的投资建议和风险提示。
"""

    # 调用 AI 分析
    analysis = call_deepseek_api(prompt, _api_key)

    # 构建 HTML 邮件
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_content = f"""
    <html>
    <body>
        <h2>股市分析报告 - {date_str}</h2>
        <p><strong>股票代码：</strong>{ticker}</p>
        <p><strong>当前价格：</strong>{stock_data['price']}</p>
        <p><strong>涨跌幅：</strong>{stock_data['change_pct']}%</p>
        <p><strong>昨日收盘：</strong>{stock_data['prev_close']}</p>
        <h3>AI 分析结果：</h3>
        <p>{analysis}</p>
        <hr>
        <small>本邮件由 GitHub Actions 自动生成，仅供参考，不构成投资建议。</small>
    </body>
    </html>
    """

    # 发送邮件
    send_email(
        subject=f"每日股市分析 - {date_str}",
        body_html=html_content,
        to_email=to_email,
        smtp_user=smtp_user,
        smtp_password=smtp_password
    )

if __name__ == "__main__":
    main()
