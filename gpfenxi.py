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

debug_logs = []

def log_debug(msg):
    print(msg)
    debug_logs.append(msg)

WHITELIST = [
    {"code": "603629", "name": "\u5229\u901a\u7535\u5b50", "sector": "AI\u7b97\u529b\u79df\u8d41"},
    {"code": "688610", "name": "\u57c3\u79d1\u5149\u7535", "sector": "\u673a\u5668\u89c6\u89c9"},
    {"code": "002266", "name": "\u6d59\u5bcc\u63a7\u80a1", "sector": "\u8d44\u6e90\u5316/\u6e05\u6d01\u80fd\u6e90"},
    {"code": "301162", "name": "\u56fd\u80fd\u65e5\u65b0", "sector": "\u65b0\u80fd\u6e90\u6570\u5b57\u5316"},
    {"code": "003010", "name": "\u82e5\u7fbd\u81e3", "sector": "\u7535\u5546\u8fd0\u8425\u8f6c\u578b"},
]

def get_q1_growth(stock_code):
    """Use baostock query_growth_data for YoY growth rates."""
    debug_info = []
    try:
        lg = bs.login()
        if lg.error_code != '0':
            debug_info.append('baostock login failed: ' + lg.error_msg)
            return None, None, '\n'.join(debug_info)

        bs_code = 'sh.' + stock_code if stock_code.startswith('6') else 'sz.' + stock_code
        rs = bs.query_growth_data(code=bs_code, year=2026, quarter=1)

        if rs.error_code != '0' or not rs.next():
            msg = 'No growth data for ' + stock_code
            debug_info.append(msg)
            bs.logout()
            return None, None, '\n'.join(debug_info)

        row = rs.get_row_data()
        log_debug('  ' + stock_code + ' 2026Q1: ' + str(row))

        if len(row) < 5:
            bs.logout()
            return None, None, 'Insufficient fields'

        try:
            rev_raw = float(row[3]) if row[3] else 0.0
            prof_raw = float(row[4]) if row[4] else 0.0
        except (ValueError, TypeError):
            bs.logout()
            return None, None, 'Parse error'

        bs.logout()
        rev_growth = round(rev_raw * 100, 2)
        prof_growth = round(prof_raw * 100, 2)
        debug_info.append('YoY: revenue=' + str(rev_growth) + '%, profit=' + str(prof_growth) + '%')
        return rev_growth, prof_growth, '\n'.join(debug_info)

    except Exception as e:
        err = 'Exception: ' + str(e)
        debug_info.append(err)
        return None, None, '\n'.join(debug_info)

def screen_growth_stocks():
    candidates = []
    for item in WHITELIST:
        code = item["code"]
        name = item["name"]
        log_debug('Analyzing ' + name + ' (' + code + ') ...')
        rev, prof, info = get_q1_growth(code)
        if rev is None or prof is None:
            log_debug('  -> No data, skip')
            continue
        log_debug('  -> rev=' + str(rev) + '%, prof=' + str(prof) + '%')
        if prof > 30 and rev > 20:
            candidates.append({"code": code, "name": name, "sector": item["sector"], "revenue_growth": rev, "profit_growth": prof, "debug": info})
            log_debug('  -> MATCH!')
        else:
            log_debug('  -> No match')
    return candidates

def analyze_stock_with_myai(stock_info, api_key):
    prompt = 'Analyze stock ' + stock_info["name"] + ' (' + stock_info["code"] + ')\n'
    prompt += 'Sector: ' + stock_info["sector"] + '\n'
    prompt += 'Q1 profit growth: ' + str(stock_info["profit_growth"]) + '%\n'
    prompt += 'Q1 revenue growth: ' + str(stock_info["revenue_growth"]) + '%\n'
    prompt += 'Rating and expected return.'
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}
    try:
        resp = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log_debug('myai failed: ' + str(e))
        return 'Failed'

def analyze_yyg(api_key):
    try:
        ticker = yf.Ticker("601166.SS")
        hist = ticker.history(period="2d")
        if not hist.empty:
            price = hist['Close'].iloc[-1]
            change = (price - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100 if len(hist) > 1 else 0.0
        else:
            price, change = "N/A", "N/A"
    except Exception as e:
        log_debug('yyg failed: ' + str(e))
        price, change = "N/A", "N/A"
    return 'Price: ' + str(price) + ', Change: ' + str(change) + '%'

def send_email(candidates, yyg_analysis, smtp_user, smtp_password, to_email):
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = '<html><head><meta charset="UTF-8"></head><body>'
    html += '<h1>Daily Briefing - ' + date_str + '</h1>'
    if candidates:
        html += '<h2>Candidates</h2><table border="1"><tr><th>Code</th><th>Name</th><th>Sector</th><th>Rev%</th><th>Prof%</th></tr>'
        for c in candidates:
            html += '<tr><td>' + c["code"] + '</td><td>' + c["name"] + '</td><td>' + c["sector"] + '</td><td>' + str(c["revenue_growth"]) + '</td><td>' + str(c["profit_growth"]) + '</td></tr>'
        html += '</table>'
    else:
        html += '<p>No candidates found.</p>'
    html += '<h2>601166 Analysis</h2><pre>' + yyg_analysis + '</pre>'
    html += '<p>Auto-generated, not investment advice.</p></body></html>'

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Stock Briefing - " + date_str
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, to_email, msg.as_string())
    print('Email sent')

def main():
    key = os.getenv("_API_KEY")
    smtp_u = os.getenv("SMTP_USER")
    smtp_p = os.getenv("SMTP_PASSWORD")
    to_e = os.getenv("TO_EMAIL")
    if not all([key, smtp_u, smtp_p, to_e]):
        raise ValueError("Missing env vars")
    log_debug("Start")
    candidates = screen_growth_stocks()
    log_debug("Found " + str(len(candidates)) + " candidates")
    yyg = analyze_yyg(key)
    send_email(candidates, yyg, smtp_u, smtp_p, to_e)

if __name__ == "__main__":
    main()
