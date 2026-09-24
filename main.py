import concurrent.futures
import json
import os
from datetime import datetime

import feedparser
import requests
from dotenv import load_dotenv
from groq import Groq
from newspaper import Article

load_dotenv("credential.env")
GROQ_API_KEY = os.getenv("GROQ")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_INVEST")
client = Groq(api_key=GROQ_API_KEY)


def get_investment_news():
    sources = [
        {"url": "https://news.google.com/rss/search?q=AI+stocks+OR+technology+stocks+when:2d&hl=en-US&gl=US&ceid=US:en", "name": "Google News: AI/Tech stocks"},
        {"url": "https://news.google.com/rss/search?q=semiconductor+OR+NVIDIA+OR+AMD+OR+TSMC+when:2d&hl=en-US&gl=US&ceid=US:en", "name": "Google News: semiconductors"},
        {"url": "https://news.google.com/rss/search?q=Microsoft+OR+Amazon+OR+Alphabet+OR+Meta+AI+when:2d&hl=en-US&gl=US&ceid=US:en", "name": "Google News: Big Tech"},
        {"url": "https://news.google.com/rss/search?q=ETF+DCA+investing+when:7d&hl=en-US&gl=US&ceid=US:en", "name": "Google News: ETF/DCA"},
        {"url": "https://news.google.com/rss/search?q=VOO+OR+VTI+OR+QQQ+OR+VT+ETF+when:7d&hl=en-US&gl=US&ceid=US:en", "name": "Google News: broad-market ETFs"},
        {"url": "https://news.google.com/rss/search?q=%E0%B8%A5%E0%B8%87%E0%B8%97%E0%B8%B8%E0%B8%99%E0%B9%81%E0%B8%A1%E0%B8%99+%E0%B8%AB%E0%B8%B8%E0%B9%89%E0%B8%99+OR+ETF+when:7d&hl=th&gl=TH&ceid=TH:th", "name": "Google News: ลงทุนแมน"},
        {"url": "https://news.google.com/rss/search?q=%E0%B8%AB%E0%B8%B8%E0%B9%89%E0%B8%99+AI+OR+ETF+OR+DCA+when:7d&hl=th&gl=TH&ceid=TH:th", "name": "Google News: หุ้น/ETF ไทย"},
        {"url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "name": "Wall Street Journal: Markets"},
        {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "name": "CNBC: Markets"},
        {"url": "https://feeds.marketwatch.com/marketwatch/topstories/", "name": "MarketWatch: Top stories"},
        {"url": "https://seekingalpha.com/market-news/feed.xml", "name": "Seeking Alpha: Market news"},
        {"url": "https://www.sec.gov/rss/news/press.xml", "name": "SEC: Press releases"},
    ]
    facebook_feed = os.getenv("FACEBOOK_FEED_URL")
    if facebook_feed:
        sources.append({"url": facebook_feed, "name": "Facebook investment group"})
    articles = []
    for source in sources:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:8]:
                articles.append({"title": entry.get("title", ""), "link": entry.get("link", ""), "source_name": source["name"]})
        except Exception as exc:
            print(f"ข้ามแหล่งข่าว {source['name']}: {exc}")
    return articles


def fetch_article(data):
    index, item = data
    try:
        article = Article(item["link"])
        article.download()
        article.parse()
        text = article.text[:1200]
        if len(text) >= 120:
            return str(index), item, f"ID: {index}\nTitle: {item['title']}\nSource: {item['source_name']}\nContent: {text}\n"
    except Exception:
        pass
    return None


def generate_investment_brief(news):
    context, valid = [], {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for result in executor.map(fetch_article, enumerate(news)):
            if result:
                index, item, text = result
                valid[index] = item
                context.append(text)
    prompt = f"""
คุณเป็นนักวิเคราะห์การเงินสำหรับสรุปข่าวให้ผู้ลงทุนทั่วไป เลือกไม่เกิน 3 ข่าวที่มีผลต่อหุ้นเทคโนโลยี/AI หรือ ETF สำหรับ DCA
ข้อมูลข่าว:
{chr(10).join(context)}
ตอบ JSON เท่านั้น: {{"items":[{{"id":"...","headline":"...","impact":"...","action":"BUY|DCA|WATCH|AVOID","tickers":"...","risk":"..."}}]}}
กติกา: ภาษาไทยสั้นมาก แต่ละข่าวไม่เกิน 3 บรรทัด; ใส่ ticker เฉพาะเมื่อ ticker นั้นปรากฏในข่าวโดยตรง; ใส่ VOO/VTI/VT/QQQ ได้เฉพาะเมื่อข่าวพูดถึง ETF/ดัชนีนั้นจริง; ห้ามเดา ticker จากชื่อบริษัทหรือเหตุการณ์; ถ้าไม่มี ticker ที่ยืนยันได้ให้ใช้ "-"; action เป็นมุมมองเพื่อการศึกษา ไม่รับประกันผลตอบแทน; ถ้าหลักฐานไม่พอใช้ WATCH; ห้ามให้คำสั่งซื้อขายเฉพาะบุคคล
"""
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[{"role": "system", "content": "You are a concise financial-news analyst. Return valid JSON only."}, {"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    parsed = json.loads(completion.choices[0].message.content)
    reports = []
    for item in parsed.get("items", [])[:3]:
        news_id = str(item.get("id", ""))
        if news_id in valid:
            reports.append({**item, **valid[news_id]})
    return reports


def build_market_heatmap(reports):
    symbols = []
    for report in reports:
        for symbol in str(report.get("tickers", "")).replace(",", " ").split():
            symbol = symbol.strip().upper().replace("$", "")
            if symbol and symbol != "-" and symbol not in symbols:
                symbols.append(symbol)
    rows = []
    for symbol in symbols[:8]:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
            response = requests.get(url, timeout=10)
            result = response.json()["chart"]["result"][0]
            closes = [value for value in result["indicators"]["quote"][0]["close"] if value is not None]
            if len(closes) < 2:
                continue
            change = (closes[-1] - closes[-2]) / closes[-2] * 100
            tile = "🟩" if change >= 1 else "🟢" if change >= 0 else "🟨" if change > -1 else "🟥"
            rows.append(f"{tile} `{symbol:<6} {change:+.2f}%`")
        except (KeyError, IndexError, TypeError, ValueError, requests.RequestException):
            continue
    return "\n".join(rows) if rows else "ยังไม่มีราคาตลาดล่าสุดสำหรับ ticker ในข่าวรอบนี้"


def send_to_discord(reports):
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("ต้องตั้ง GitHub secret DISCORD_INVEST เป็น webhook ของ channel ลงทุนก่อน")
    embeds = []
    for report in reports:
        action = report.get("action", "WATCH")
        embeds.append({
            "title": f"{action}  |  {report.get('headline', report['title'])}",
            "url": report["link"],
            "description": report.get("impact", "-"),
            "color": {"BUY": 3066993, "DCA": 3447003, "WATCH": 15105570, "AVOID": 15158332}.get(action, 9807270),
            "fields": [
                {"name": "ตัวเลือก", "value": f"`{report.get('tickers', '-')}`", "inline": True},
                {"name": "ความเสี่ยง", "value": report.get("risk", "-"), "inline": True},
                {"name": "แหล่งข่าว", "value": report["source_name"], "inline": False},
            ],
        })
    today = datetime.now().strftime("%d/%m/%Y")
    heatmap = build_market_heatmap(reports)
    payload = {"content": f"**📈 หุ้น AI/Tech + ETF สำหรับ DCA**  ·  {today}\n\n**📊 Market heatmap (เปลี่ยนแปลงเทียบวันก่อน)**\n{heatmap}", "embeds": embeds, "allowed_mentions": {"parse": []}}
    response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
    response.raise_for_status()


if __name__ == "__main__":
    send_to_discord(generate_investment_brief(get_investment_news()))
