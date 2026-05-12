import requests
import yfinance as yf
import feedparser
import schedule
import time
from datetime import datetime, timezone, timedelta

BOT_TOKEN = '8606404952:AAFicFNM78CH3pz2BVmddwbyJ5ObIf_H2DY'
CHAT_ID   = '8078322111'

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

TH_TZ = timezone(timedelta(hours=7))

def is_market_open():
    """เช็คว่าตลาด SET เปิดอยู่ไหม (วันธรรมดา 10:00-12:30 และ 14:30-17:00)"""
    now = datetime.now(TH_TZ)
    if now.weekday() >= 5:  # เสาร์-อาทิตย์
        return False
    t = now.hour * 60 + now.minute
    morning   = 10*60 <= t <= 12*60+30
    afternoon = 14*60+30 <= t <= 17*60
    return morning or afternoon

def send_message(text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    r = requests.post(url, json={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'})
    return r.json()

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

def get_stock_news(ticker):
    try:
        news = yf.Ticker(ticker).news or []
        results = []
        for n in news[:2]:
            title = n.get('title', '')
            link  = n.get('link', '')
            if title:
                results.append(f'• {title}\n  {link}')
        return results
    except:
        return []

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

def send_report():
    now        = datetime.now(TH_TZ).strftime('%d/%m/%Y %H:%M')
    market_open = is_market_open()
    print(f'[{now}] ตลาด{"เปิด" if market_open else "ปิด"} — กำลังส่งรายงาน...')

    if market_open:
        # ── ตลาดเปิด: ราคา + ข่าว ──────────────────────
        price_lines      = []
        stock_news_lines = []

        for ticker in WATCHLIST:
            s = get_stock_info(ticker)
            price_lines.append(format_stock_price(s) if s else f'⚠️ {ticker}: ดึงข้อมูลไม่ได้')
            news = get_stock_news(ticker)
            if news:
                stock_news_lines.append(f'\n📌 <b>{ticker}</b>\n' + '\n'.join(news))
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
        # ── ตลาดปิด: ข่าวอย่างเดียว ────────────────────
        stock_news_lines = []
        for ticker in WATCHLIST:
            news = get_stock_news(ticker)
            if news:
                stock_news_lines.append(f'\n📌 <b>{ticker}</b>\n' + '\n'.join(news))
            time.sleep(0.3)

        if stock_news_lines:
            msg = ('📰 <b>Investment OS — News Update</b>\n'
                   f'📅 {now}  |  🔴 ตลาดปิด\n{"─"*28}'
                   + ''.join(stock_news_lines))
            send_message(msg)
            time.sleep(1)

    # ── ข่าวตลาดทั่วไป (ส่งทุกรอบ) ─────────────────────
    market_news = get_market_news()
    if market_news:
        msg_news = ('🌐 <b>ข่าวตลาดและเศรษฐกิจ</b>\n' + '─'*28 + '\n'
                    + '\n\n'.join(market_news)
                    + '\n\n💡 <i>Powered by Investment OS</i>')
        send_message(msg_news)

    print(f'[{now}] ✅ ส่งเสร็จแล้ว')

# ── Schedule UTC (Railway ใช้ UTC) ───────────────────
schedule.every().day.at('03:30').do(send_report)  # 10:30 TH
schedule.every().day.at('05:30').do(send_report)  # 12:30 TH
schedule.every().day.at('10:00').do(send_report)  # 17:00 TH
schedule.every().day.at('13:00').do(send_report)  # 20:00 TH

print('🚀 Investment OS Bot เริ่มทำงานแล้ว')
print('📅 10:30, 12:30 → ราคา + ข่าว')
print('📅 17:00 → ราคาปิด + ข่าว')
print('📅 20:00 → ข่าวอย่างเดียว')

while True:
    schedule.run_pending()
    time.sleep(30)
