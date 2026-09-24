import json
import os
import tempfile
import time
from datetime import datetime

import feedparser
import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv("credential.env")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_INVEST")
DROP_ALERT_PCT = float(os.getenv("DROP_ALERT_PCT", "3"))
WATCHLISTS = {
    "AI platforms": ["NVDA", "MSFT", "GOOGL", "META", "AMZN"],
    "Semiconductors": ["NVDA", "AMD", "AVGO", "TSM", "ASML"],
    "Cloud/software": ["PLTR", "ORCL", "CRM", "SNOW", "NOW"],
    "DCA ETFs": ["QQQ", "VOO", "VTI", "VT", "SOXX"],
}
WATCHLIST_SYMBOLS = list(dict.fromkeys(symbol for group in WATCHLISTS.values() for symbol in group))


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
        {"url": "https://finance.yahoo.com/news/rssindex", "name": "Yahoo Finance"},
        {"url": "https://www.investing.com/rss/news_25.rss", "name": "Investing.com: Stocks"},
        {"url": "https://www.benzinga.com/feed", "name": "Benzinga"},
        {"url": "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best", "name": "Reuters: Business"},
        {"url": "https://news.google.com/rss/search?q=earnings+guidance+AI+OR+semiconductor+when:1d&hl=en-US&gl=US&ceid=US:en", "name": "Google News: earnings"},
    ]
    facebook_feed = os.getenv("FACEBOOK_FEED_URL")
    if facebook_feed:
        sources.append({"url": facebook_feed, "name": "Facebook investment group"})
    articles = []
    for source in sources:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:12]:
                articles.append({
                    "title": entry.get("title", "").strip(),
                    "link": entry.get("link", ""),
                    "source_name": source["name"],
                    "published": entry.get("published", ""),
                    "published_parsed": entry.get("published_parsed"),
                })
        except Exception as exc:
            print(f"ข้ามแหล่งข่าว {source['name']}: {exc}")
    unique = {}
    for item in articles:
        key = item["title"].lower()
        if item["title"] and item["link"] and key not in unique:
            unique[key] = item
    return list(unique.values())


def select_news(news, limit=5):
    # Feed order is inconsistent across providers; sort by publication time so
    # the Discord post shows the fastest/latest items first.
    def published_ts(item):
        parsed = item.get("published_parsed")
        if parsed:
            try:
                return time.mktime(parsed)
            except (TypeError, OverflowError, ValueError):
                pass
        return 0

    ranked = sorted(news, key=published_ts, reverse=True)
    return ranked[:limit]


def get_market_quotes(reports):
    symbols = WATCHLIST_SYMBOLS.copy()
    for report in reports:
        for symbol in str(report.get("tickers", "")).replace(",", " ").split():
            symbol = symbol.strip().upper().replace("$", "")
            if symbol and symbol != "-" and symbol not in symbols:
                symbols.append(symbol)
    quotes = []
    try:
        joined = ",".join(symbols)
        url = f"https://query2.finance.yahoo.com/v7/finance/spark?symbols={joined}&range=1d&interval=5m"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        results = response.json()["spark"]["result"]
        by_symbol = {item["symbol"]: item["response"][0] for item in results}
        for symbol in symbols:
            response = by_symbol.get(symbol, {})
            closes = [value for value in response.get("indicators", {}).get("quote", [{}])[0].get("close", []) if value is not None]
            previous = response.get("meta", {}).get("chartPreviousClose")
            if len(closes) < 2:
                quotes.append((symbol, None, None))
            else:
                base = previous or closes[0]
                quotes.append((symbol, (closes[-1] - base) / base * 100, closes[-1]))
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException):
        quotes = [(symbol, None, None) for symbol in symbols]
    return quotes


def build_market_heatmap_image(reports, quotes=None):
    quotes = quotes or get_market_quotes(reports)
    width, height = 1600, 1120
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

    heat_x, heat_y, heat_w, heat_h = 370, 116, 1198, 930
    draw.text((heat_x, 72), "Stock Heatmap", fill="#f4f7fb", font=title_font)
    cols, rows = 5, 4
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
    symbol_aliases = {
        "NVIDIA": "NVDA", "MICROSOFT": "MSFT", "META": "META", "FACEBOOK": "META",
        "ALPHABET": "GOOGL", "GOOGLE": "GOOGL", "AMAZON": "AMZN", "APPLE": "AAPL",
        "AMD": "AMD", "TSMC": "TSM", "BROADCOM": "AVGO", "TESLA": "TSLA",
        "QQQ": "QQQ", "VOO": "VOO", "VTI": "VTI", "VT": "VT",
    }
    groups = {}
    for item in reports:
        upper_title = item["title"].upper()
        symbols = {ticker for name, ticker in symbol_aliases.items() if name in upper_title}
        key = next(iter(symbols), "MARKET")
        groups.setdefault(key, []).append(item)
    quotes = get_market_quotes(reports)
    alerts = [(symbol, change) for symbol, change, _ in quotes if change is not None and change <= -DROP_ALERT_PCT]
    lines = []
    if alerts:
        lines.append(f"@here **🚨 หุ้นลงถึงจุดช้อน (≤ -{DROP_ALERT_PCT:.1f}%)**")
        lines.extend(f"🔻 `{symbol}` {change:+.2f}%" for symbol, change in alerts)
        lines.append("")
    lines.append("**📰 ข่าวล่าสุด**")
    for symbol, items in list(groups.items())[:5]:
        lines.append(f"\n**{symbol}**")
        for item in items[:3]:
            title = item["title"].replace("[", "(").replace("]", ")")[:150]
            lines.append(f"• [{title}]({item['link']}) · {item['source_name']}")
    lines.append("\n**👀 Watchlist (ด้านละ 5 ตัว)**")
    for name, symbols in WATCHLISTS.items():
        lines.append(f"**{name}:** " + " ".join(f"`{symbol}`" for symbol in symbols))
    today = datetime.now().strftime("%d/%m/%Y")
    heatmap_path = build_market_heatmap_image(reports, quotes)
    payload = {
        "content": f"**📈 หุ้น AI/Tech + ETF สำหรับ DCA** · {today}\n\n" + "\n".join(lines),
        "embeds": [{"title": "📊 Market Heatmap", "image": {"url": "attachment://market-heatmap.png"}, "color": 921102}],
        "allowed_mentions": {"parse": ["everyone"] if alerts else []},
    }
    with open(heatmap_path, "rb") as image_file:
        response = requests.post(DISCORD_WEBHOOK_URL, data={"payload_json": json.dumps(payload)}, files={"file": ("market-heatmap.png", image_file, "image/png")}, timeout=30)
    response.raise_for_status()


if __name__ == "__main__":
    send_to_discord(select_news(get_investment_news()))
