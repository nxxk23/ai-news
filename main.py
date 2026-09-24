import concurrent.futures
import json
import os
import tempfile
from datetime import datetime

import feedparser
import requests
from dotenv import load_dotenv
from groq import Groq
from newspaper import Article
from PIL import Image, ImageDraw, ImageFont

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


def get_market_quotes(reports):
    symbols = ["NVDA", "MSFT", "META", "GOOGL", "AMZN", "QQQ", "VOO", "VT"]
    for report in reports:
        for symbol in str(report.get("tickers", "")).replace(",", " ").split():
            symbol = symbol.strip().upper().replace("$", "")
            if symbol and symbol != "-" and symbol not in symbols:
                symbols.append(symbol)
    quotes = []
    try:
        joined = ",".join(symbols[:8])
        url = f"https://query2.finance.yahoo.com/v7/finance/spark?symbols={joined}&range=5d&interval=1d"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        results = response.json()["spark"]["result"]
        by_symbol = {item["symbol"]: item["response"][0] for item in results}
        for symbol in symbols[:8]:
            closes = [value for value in by_symbol.get(symbol, {}).get("indicators", {}).get("quote", [{}])[0].get("close", []) if value is not None]
            if len(closes) < 2:
                quotes.append((symbol, None, None))
            else:
                quotes.append((symbol, (closes[-1] - closes[-2]) / closes[-2] * 100, closes[-1]))
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException):
        quotes = [(symbol, None, None) for symbol in symbols[:8]]
    return quotes


def build_market_heatmap_image(reports):
    quotes = get_market_quotes(reports)
    width, height = 1400, 760
    image = Image.new("RGB", (width, height), "#090b10")
    draw = ImageDraw.Draw(image)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        title_font = ImageFont.truetype(bold_path, 30)
        symbol_font = ImageFont.truetype(bold_path, 29)
        value_font = ImageFont.truetype(font_path, 21)
        small_font = ImageFont.truetype(font_path, 16)
    except OSError:
        title_font = symbol_font = value_font = small_font = ImageFont.load_default()

    draw.text((32, 24), "Market Overview", fill="#f4f7fb", font=title_font)
    draw.text((32, 68), datetime.now().strftime("%d %b %Y · AI/Tech + ETF"), fill="#8f9bab", font=small_font)
    chart_x, chart_y, chart_w, chart_h = 32, 116, 300, 250
    draw.rounded_rectangle((chart_x, chart_y, chart_x + chart_w, chart_y + chart_h), radius=12, fill="#111721", outline="#263344", width=2)
    draw.text((chart_x + 18, chart_y + 16), "Watchlist", fill="#d5dce5", font=value_font)
    valid = [q[1] for q in quotes if q[1] is not None]
    if valid:
        points = []
        for i, value in enumerate(valid):
            x = chart_x + 20 + int(i * (chart_w - 40) / max(1, len(valid) - 1))
            y = chart_y + chart_h - 34 - int((value - min(valid)) / max(0.01, max(valid) - min(valid)) * (chart_h - 85))
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill="#19d3b1", width=4)
        for x, y in points:
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill="#19d3b1")
    draw.text((chart_x + 18, chart_y + chart_h - 28), "daily change", fill="#8f9bab", font=small_font)

    heat_x, heat_y, heat_w, heat_h = 370, 116, 998, 590
    draw.text((heat_x, 72), "Stock Heatmap", fill="#f4f7fb", font=title_font)
    cols, rows = 4, 2
    gap = 8
    tile_w = (heat_w - gap * (cols - 1)) // cols
    tile_h = (heat_h - gap * (rows - 1)) // rows
    for index, (symbol, change, price) in enumerate(quotes):
        col, row = index % cols, index // cols
        x, y = heat_x + col * (tile_w + gap), heat_y + row * (tile_h + gap)
        if change is None:
            color = "#303742"
            change_text = "N/A"
        elif change >= 0:
            intensity = min(120, int(change * 22))
            color = (22, 92 + intensity // 2, 76)
            change_text = f"+{change:.2f}%"
        else:
            intensity = min(120, int(abs(change) * 22))
            color = (112 + intensity // 2, 38, 51)
            change_text = f"{change:.2f}%"
        draw.rounded_rectangle((x, y, x + tile_w, y + tile_h), radius=10, fill=color)
        draw.text((x + 22, y + 22), symbol, fill="#ffffff", font=symbol_font)
        draw.text((x + 22, y + 70), change_text, fill="#ffffff", font=value_font)
        if price is not None:
            draw.text((x + 22, y + tile_h - 32), f"${price:,.2f}", fill="#d7e0e8", font=small_font)

    path = os.path.join(tempfile.gettempdir(), "market-heatmap.png")
    image.save(path, format="PNG", optimize=True)
    return path


def send_to_discord(reports):
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("ต้องตั้ง GitHub secret DISCORD_INVEST เป็น webhook ของ channel ลงทุนก่อน")
    embeds = []
    for report in reports:
        action = report.get("action", "WATCH")
        action_icon = {"BUY": "🟢", "DCA": "🔵", "WATCH": "🟡", "AVOID": "🔴"}.get(action, "⚪")
        risk = str(report.get("risk", "-"))
        risk_icon = "🔴" if any(word in risk.lower() for word in ("high", "สูง")) else "🟡" if any(word in risk.lower() for word in ("medium", "ปานกลาง")) else "🟢"
        embeds.append({
            "title": f"{action_icon} {action}  ·  {report.get('headline', report['title'])}",
            "url": report["link"],
            "description": report.get("impact", "-"),
            "color": {"BUY": 3066993, "DCA": 3447003, "WATCH": 15105570, "AVOID": 15158332}.get(action, 9807270),
            "fields": [
                {"name": "ตัวเลือก", "value": f"`{report.get('tickers', '-')}`", "inline": True},
                {"name": "ความเสี่ยง", "value": f"{risk_icon} {risk}", "inline": True},
            ],
        })
    today = datetime.now().strftime("%d/%m/%Y")
    heatmap_path = build_market_heatmap_image(reports)
    embeds.insert(0, {"title": "📊 Market Heatmap", "image": {"url": "attachment://market-heatmap.png"}, "color": 921102})
    payload = {"content": f"**📈 หุ้น AI/Tech + ETF สำหรับ DCA**  ·  {today}", "embeds": embeds, "allowed_mentions": {"parse": []}}
    with open(heatmap_path, "rb") as image_file:
        response = requests.post(DISCORD_WEBHOOK_URL, data={"payload_json": json.dumps(payload)}, files={"file": ("market-heatmap.png", image_file, "image/png")}, timeout=30)
    response.raise_for_status()


if __name__ == "__main__":
    send_to_discord(generate_investment_brief(get_investment_news()))
