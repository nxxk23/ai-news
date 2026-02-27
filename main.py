import os
import feedparser
import requests
import time
import json
from groq import Groq
from dotenv import load_dotenv
from newspaper import Article

load_dotenv("credential.env")
GROQ_API_KEY = os.getenv("GROQ")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD")
client = Groq(api_key=GROQ_API_KEY)

def get_extensive_news():
    sources = [
        {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "name": "TechCrunch"},
        {"url": "https://hnrss.org/newest?q=AI", "name": "Hacker News"},
        {"url": "https://www.reddit.com/r/artificial/top.rss?t=day", "name": "Reddit"},
        {"url": "http://export.arxiv.org/rss/cs.AI", "name": "ArXiv"},
        {"url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "name": "Ars Technica"},
        {"url": "https://venturebeat.com/category/ai/feed/", "name": "VentureBeat"}
    ]
    
    all_articles = []
    
    for s in sources:
        try:
            feed = feedparser.parse(s['url'])
            for entry in feed.entries[:7]: 
                all_articles.append({
                    "title": entry.title, 
                    "link": entry.link, 
                    "source_name": s['name']
                })
        except Exception as e:
            print(f"⚠️ ข้ามการดึงข่าวจาก {s['name']} เนื่องจาก: {e}")
            continue
            
    return all_articles
def generate_and_group_reports(news_list):
    categories_format = {
        "TECH": {"cat_title": "🚀 AI Tech อุบัติใหม่", "color": 3447003},
        "TOOLS": {"cat_title": "🛠️ AI Tools & Comparison", "color": 15105570},
        "TREND": {"cat_title": "📈 AI Trend & Future", "color": 3066993}
    }
    
    articles_context = ""
    valid_articles = {}
    
    print("📥 กำลังดึงเนื้อหาข่าวเบื้องต้นเพื่อคัดเลือก 3 ข่าวเด่น...")
    for idx, item in enumerate(news_list):
        try:
            article_data = Article(item['link'])
            article_data.download()
            article_data.parse()
            text = article_data.text[:800] 
            if len(text) > 100:
                articles_context += f"ID: {idx}\nTitle: {item['title']}\nSource: {item['source_name']}\nContent: {text}\n\n"
                valid_articles[str(idx)] = item
        except Exception:
            continue

    prompt = f"""
    คุณคือบรรณาธิการข่าว Tech AI หน้าที่ของคุณคือเลือกข่าวที่ดีที่สุด 'เพียง 3 ข่าว' จากรายการด้านล่าง 
    โดยต้องจัดลง 3 หมวดหมู่ (หมวดละ 1 ข่าว ห้ามซ้ำกัน) ดังนี้:
    1. TECH: เทคโนโลยีใหม่ หรืออัปเดตจากบริษัทใหญ่ๆ (Big Tech)
    2. TOOLS: เครื่องมือ หรือแอพ AI ใหม่ๆ ที่ออกแบบมาน่าสนใจ มีข้อดีกว่าตัวเดิมในตลาด
    3. TREND: แนวโน้ม ข่าวอัปเดต หรือเหตุการณ์สำคัญที่เกิดขึ้นในวงการ AI ตอนนี้

    รายการข่าว:
    {articles_context}

    กติกาการสรุปข่าว:
    - สรุป Insight (ดียังไง/ต่างยังไง/ทำไมในอนาคตต้องมี) เป็นข้อๆ
    - ต้องมี 'อีโมจิ' นำหน้าทุกข้อ
    - ใช้ภาษาวัยรุ่น Tech (เช่น ตัวแรง, Game Changer, จัดเต็ม)
    - ห้ามใส่ Link ในเนื้อหาสรุป

    ตอบกลับเป็นรูปแบบ JSON เท่านั้น ตามโครงสร้างเป๊ะๆ แบบนี้:
    {{
        "TECH": {{"id": "...", "summary": "..."}},
        "TOOLS": {{"id": "...", "summary": "..."}},
        "TREND": {{"id": "...", "summary": "..."}}
    }}
    """
    
    print("🤖 กำลังให้ AI คัดเลือกและสรุป 3 ข่าวใหญ่ประจำวัน...")
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a helpful AI news curator. Always output strictly in JSON format."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        response_format={"type": "json_object"} 
    )
    
    raw_res = completion.choices[0].message.content
    reports = []
    
    try:
        parsed_res = json.loads(raw_res)
        for cat in ["TECH", "TOOLS", "TREND"]:
            if cat in parsed_res:
                news_id = str(parsed_res[cat].get("id", ""))
                summary = parsed_res[cat].get("summary", "")
                
                if news_id in valid_articles:
                    item = valid_articles[news_id]
                    reports.append({
                        "category": cat,
                        "cat_title": categories_format[cat]["cat_title"],
                        "color": categories_format[cat]["color"],
                        "title": item["title"],
                        "link": item["link"],
                        "source_name": item["source_name"],
                        "summary": summary
                    })
    except Exception as e:
        print(f"❌ Error parsing JSON from Groq: {e}")
        
    return reports

def send_to_discord(reports):
    if not reports:
        print("⚠️ ไม่มีข่าวที่จะส่ง")
        return

    print("🚚 กำลังรวบรวมและส่ง Embeds ทั้งหมดในข้อความเดียวเข้า Discord...")

    from datetime import datetime
    thai_months = ["มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน",
                   "กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"]
    now = datetime.now()
    today = f"{now.day} {thai_months[now.month - 1]} {now.year + 543}"
    
    # สร้าง Payload หลักที่มีทั้งข้อความเกริ่นนำ และเตรียมลิสต์สำหรับใส่ Embeds
    payload = {
        "content": f"**🔥 AI Top 3 Highlights: สรุปข่าว AI ประจำวันที่ {today}!**",
        "embeds": []
    }

    # วนลูปเพื่อนำแต่ละหมวดหมู่มาต่อในลิสต์ embeds
    for report in reports:
        safe_content = report["summary"][:4000]
        
        payload["embeds"].append({
            "author": {"name": report["cat_title"]},
            "title": report["title"],
            "url": report["link"],
            "description": safe_content,
            "color": report["color"],
            "footer": {"text": f"📰 อ้างอิงแหล่งที่มา: {report['source_name']}"}
        })

    # ส่ง Request เพียงครั้งเดียว
    res = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if res.status_code == 204:
        print("✅ ส่งข่าวทั้ง 3 หมวดหมู่สำเร็จในข้อความเดียว!")
    else:
        print(f"❌ มีปัญหาในการส่ง: {res.text}")

if __name__ == "__main__":
    articles = get_extensive_news()
    top_reports = generate_and_group_reports(articles)
    send_to_discord(top_reports)