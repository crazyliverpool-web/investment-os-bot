import os
import requests
import yfinance as yf
import feedparser
import schedule
import time
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID   = os.environ.get('CHAT_ID')

if not BOT_TOKEN or not CHAT_ID:
    raise RuntimeError('BOT_TOKEN และ CHAT_ID ต้องตั้งใน Environment Variables')

WATCHLIST = [
    'AIMCG.BK','ASK.BK','BAFS.BK','BCH.BK','BDMS.BK',
    'CHG.BK','GVREIT.BK','HMPRO.BK','ILM.BK','KTBSTMR.BK',
    'NKT.BK','PROSPECT.BK','QHBREIT.BK','RJH.BK','RPH.BK',
    'SNNP.BK','SPRIME.BK','VIH.BK','WPH.BK',
]

NEWS_FEEDS = {
    'Bangkok Post Business': 'https://www.bangkokpost.com/rss/data/business.xml',
    'Bangkok Post Markets':  'https://www.bangkokpost.com/rss/data/investing.xml',
}

# keyword สำคัญที่ต้องแจ้งเตือนพิเศษ
IMPORTANT_KEYWORDS = [
    'dividend', 'ปันผล', 'earnings', 'profit', 'งบการเงิน', 'ผลประกอบการ',
    'quarterly', 'annual report', 'รายงานประจำปี', 'capital increase', 'เพิ่มทุน',
    'warrant', 'วอแรนต์', 'buyback', 'ซื้อหุ้นคืน', 'merger', 'acquisition',
    'q1', 'q2', 'q3', 'q4', 'ไตรมาส', 'net profit', 'revenue',
]

TH_TZ = timezone(timedelta(hours=7))

# เก็บ dividend ที่เคยเห็นแล้ว (ป้องกันแจ้งซ้ำ)
seen_dividends = {}


def is_market_open():
    now = datetime.now(TH_TZ)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return (10*60 <= t <= 12*60+30) or (14*60+30 <= t <= 17*60)

def send_message(text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    for attempt in range(3):
        try:
            r = requests.post(url, json={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f'send_message attempt {attempt+1} failed: {e}')
            if attempt < 2:
                time.sleep(5)
    print('send_message failed after 3 attempts')

def send_error(context, error):
    now = datetime.now(TH_TZ).strftime('%d/%m/%Y %H:%M')
    try:
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        requests.post(url, json={
            'chat_id': CHAT_ID,
            'text': f'🚨 <b>Investment OS — Bot Error</b>\n📅 {now}\n\n<b>จุด:</b> {context}\n<b>Error:</b> {str(error)[:300]}',
            'parse_mode': 'HTML'
        }, timeout=10)
    except:
        print(f'ERROR ALERT FAILED: {context} — {error}')

def is_important_news(title):
    title_lower = title.lower()
    return any(kw in title_lower for kw in IMPORTANT_KEYWORDS)

# ── ราคาหุ้น ────────────────────────────────────────────
def get_stock_info(ticker):
    try:
        info = yf.Ticker(ticker).info
        current_price = info.get('currentPrice') or info.get('regularMarketPrice')
        prev_close    = info.get('previousClose') or info.get('regularMarketPreviousClose')
        name          = info.get('longName') or info.get('shortName') or ticker
        if current_price and prev_close:
            change     = current_price - prev_close
            change_pct = (change / prev_close) * 100
            return {
                'ticker': ticker, 'name': name,
                'price': current_price, 'change': change,
                'change_pct': change_pct,
                'arrow': '🟢' if change >= 0 else '🔴',
                'sign':  '+' if change >= 0 else '',
                'pe':        info.get('trailingPE'),
                'div_yield': info.get('dividendYield'),
            }
    except Exception as e:
        print(f'Error {ticker}: {e}')
    return None

def format_stock_price(s):
    pe_text = f"{s['pe']:.1f}x" if s['pe'] else 'N/A'
    if s['div_yield']:
        div_text = f"{s['div_yield']*100:.2f}%" if s['div_yield'] < 1 else f"{s['div_yield']:.2f}%"
    else:
        div_text = 'N/A'
    return (
        f"{s['arrow']} <b>{s['ticker']}</b> — {s['name']}\n"
        f"   💰 {s['price']:.2f} THB  "
        f"{s['sign']}{s['change']:.2f} ({s['sign']}{s['change_pct']:.2f}%)\n"
        f"   P/E: {pe_text}  |  Div: {div_text}"
    )

# ── ข่าวรายหุ้น (พร้อม flag ข่าวสำคัญ) ─────────────────
def get_stock_news(ticker):
    try:
        news = yf.Ticker(ticker).news or []
        normal, important = [], []
        for n in news[:5]:
            title = n.get('title', '')
            link  = n.get('link', '')
            if not title:
                continue
            if is_important_news(title):
                important.append(f'🚨 <b>{title}</b>\n  {link}')
            else:
                if len(normal) < 2:
                    normal.append(f'• {title}\n  {link}')
        return important, normal
    except:
        return [], []

# ── Earnings Calendar ────────────────────────────────────
def check_earnings_calendar():
    alerts = []
    today  = datetime.now(TH_TZ).date()
    for ticker in WATCHLIST:
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is None:
                continue
            # yfinance คืน dict หรือ DataFrame
            if hasattr(cal, 'get'):
                earn_date = cal.get('Earnings Date')
            elif hasattr(cal, 'loc'):
                earn_date = cal.loc['Earnings Date'].values if 'Earnings Date' in cal.index else None
            else:
                continue
            if earn_date is None:
                continue
            # แปลงเป็น list
            if not hasattr(earn_date, '__iter__') or isinstance(earn_date, str):
                earn_date = [earn_date]
            for d in earn_date:
                try:
                    d_date = d.date() if hasattr(d, 'date') else d
                    days_left = (d_date - today).days
                    if 0 <= days_left <= 7:
                        alerts.append(
                            f'📅 <b>{ticker}</b> — ประกาศผลประกอบการใน {days_left} วัน ({d_date})'
                        )
                except:
                    pass
        except:
            pass
    return alerts

# ── Dividend Tracker ─────────────────────────────────────
def check_new_dividends():
    alerts = []
    for ticker in WATCHLIST:
        try:
            divs = yf.Ticker(ticker).dividends
            if divs is None or len(divs) == 0:
                continue
            latest_date  = str(divs.index[-1].date())
            latest_amount = float(divs.iloc[-1])
            key = f'{ticker}_{latest_date}'
            if key not in seen_dividends:
                seen_dividends[key] = True
                # แจ้งเฉพาะปันผลที่ประกาศใน 30 วันล่าสุด
                div_date = divs.index[-1].date()
                today    = datetime.now(TH_TZ).date()
                if (today - div_date).days <= 30:
                    alerts.append(
                        f'💰 <b>{ticker}</b> ปันผล {latest_amount:.4f} THB/หุ้น (XD: {latest_date})'
                    )
        except:
            pass
    return alerts

# ── ข่าวตลาดทั่วไป (RSS) ─────────────────────────────────
def get_market_news():
    results = []
    for source, url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:1]:
                title = entry.get('title', '')
                link  = entry.get('link', '')
                if title:
                    results.append(f'• {title}\n  {link}')
        except Exception as e:
            print(f'RSS error {source}: {e}')
    return results

# ── ส่งแจ้งเตือนเร่งด่วน (ปันผล/earnings) ───────────────
def check_and_send_alerts():
    earnings_alerts = check_earnings_calendar()
    dividend_alerts = check_new_dividends()

    if earnings_alerts or dividend_alerts:
        lines = ['🔔 <b>Investment OS — แจ้งเตือนสำคัญ</b>\n' + '─'*28]
        if earnings_alerts:
            lines.append('\n<b>📊 ใกล้ประกาศผลประกอบการ:</b>')
            lines.extend(earnings_alerts)
        if dividend_alerts:
            lines.append('\n<b>💰 ปันผลใหม่:</b>')
            lines.extend(dividend_alerts)
        send_message('\n'.join(lines))

# ── รายงานหลัก ───────────────────────────────────────────
def send_report():
    try:
        _send_report()
    except Exception as e:
        send_error('send_report', e)
        print(f'send_report crashed: {e}')

def _send_report():
    now         = datetime.now(TH_TZ).strftime('%d/%m/%Y %H:%M')
    market_open = is_market_open()
    print(f'[{now}] ตลาด{"เปิด" if market_open else "ปิด"} — กำลังส่ง...')

    important_news_all = []

    if market_open:
        price_lines      = []
        stock_news_lines = []

        for ticker in WATCHLIST:
            s = get_stock_info(ticker)
            price_lines.append(format_stock_price(s) if s else f'⚠️ {ticker}: ดึงข้อมูลไม่ได้')
            important, normal = get_stock_news(ticker)
            important_news_all.extend([f'<b>{ticker}</b>: ' + n for n in important])
            if important or normal:
                lines = important + normal
                stock_news_lines.append(f'\n📌 <b>{ticker}</b>\n' + '\n'.join(lines))
            time.sleep(0.5)

        msg1 = (f'📈 <b>Investment OS — Market Update</b>\n📅 {now}\n{"─"*28}\n\n'
                + '\n\n'.join(price_lines))
        send_message(msg1)
        time.sleep(1)

        if stock_news_lines:
            msg2 = '📰 <b>ข่าวหุ้นใน Watchlist</b>\n' + '─'*28 + ''.join(stock_news_lines)
            send_message(msg2)
            time.sleep(1)

    else:
        stock_news_lines = []
        for ticker in WATCHLIST:
            important, normal = get_stock_news(ticker)
            important_news_all.extend([f'<b>{ticker}</b>: ' + n for n in important])
            lines = important + normal
            if lines:
                stock_news_lines.append(f'\n📌 <b>{ticker}</b>\n' + '\n'.join(lines))
            time.sleep(0.3)

        if stock_news_lines:
            msg = ('📰 <b>Investment OS — News Update</b>\n'
                   f'📅 {now}  |  🔴 ตลาดปิด\n{"─"*28}'
                   + ''.join(stock_news_lines))
            send_message(msg)
            time.sleep(1)

    # ── ข่าวสำคัญ (แยก highlight) ──────────────────────
    if important_news_all:
        msg_imp = ('🚨 <b>ข่าวสำคัญ — ต้องติดตาม!</b>\n' + '─'*28 + '\n'
                   + '\n\n'.join(important_news_all))
        send_message(msg_imp)
        time.sleep(1)

    # ── ข่าวตลาดทั่วไป ─────────────────────────────────
    market_news = get_market_news()
    if market_news:
        msg_news = ('🌐 <b>ข่าวตลาดและเศรษฐกิจ</b>\n' + '─'*28 + '\n'
                    + '\n\n'.join(market_news)
                    + '\n\n💡 <i>Powered by Investment OS</i>')
        send_message(msg_news)

    # ── เช็คปันผล/earnings ทุกรอบ ──────────────────────
    check_and_send_alerts()

    print(f'[{now}] ✅ เสร็จแล้ว')

# ── Schedule UTC ─────────────────────────────────────────
schedule.every().day.at('03:30').do(send_report)  # 10:30 TH
schedule.every().day.at('05:30').do(send_report)  # 12:30 TH
schedule.every().day.at('10:00').do(send_report)  # 17:00 TH
schedule.every().day.at('13:00').do(send_report)  # 20:00 TH

print('🚀 Investment OS Bot เริ่มทำงานแล้ว')
print('📅 ตลาดเปิด  → ราคา + ข่าว + แจ้งเตือนสำคัญ')
print('📅 ตลาดปิด  → ข่าว + แจ้งเตือนสำคัญ')
print('🚨 ปันผล/Earnings → แจ้งเตือนทันที')

while True:
    schedule.run_pending()
    time.sleep(30)
