import urllib.request
import json
import os
import re
from datetime import datetime, timedelta
import email.utils
import requests

# 1. 기본 세팅
KEYWORDS = ["도도포인트", "나우웨이팅"]

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

def log(msg):
    print(f"👉 {msg}", flush=True)

def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', raw_html).replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&apos;', "'")

def search_naver_api(keyword, search_type):
    exact_keyword = f'"{keyword}"'
    encText = urllib.parse.quote(exact_keyword)
    
    url = f"https://openapi.naver.com/v1/search/{search_type}.json?query={encText}&display=100&sort=date"
    
    request = urllib.request.Request(url)
    request.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
    request.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
    
    try:
        response = urllib.request.urlopen(request)
        rescode = response.getcode()
        if rescode == 200:
            response_body = response.read()
            data = json.loads(response_body.decode('utf-8'))
            
            posts = []
            kst_now = datetime.utcnow() + timedelta(hours=9)
            yesterday_kst = kst_now - timedelta(days=1)
            yesterday_str = yesterday_kst.strftime("%Y%m%d")
            
            for item in data['items']:
                post_date_formatted = ""
                
                if search_type == "blog":
                    raw_date = item.get("postdate", "")
                    if raw_date != yesterday_str:
                        continue 
                    if len(raw_date) == 8:
                        post_date_formatted = f"{raw_date[:4]}.{raw_date[4:6]}.{raw_date[6:]}"
                        
                elif search_type == "news":
                    pub_date_tuple = email.utils.parsedate_tz(item.get('pubDate', ''))
                    if pub_date_tuple:
                        pub_date = datetime.fromtimestamp(email.utils.mktime_tz(pub_date_tuple))
                        if pub_date.strftime("%Y%m%d") != yesterday_str:
                            continue
                        post_date_formatted = pub_date.strftime("%Y.%m.%d")
                        
                elif search_type == "cafearticle":
                    post_date_formatted = "날짜 미제공"

                title = clean_html(item['title'])
                link = item['link']
                snippet = clean_html(item['description'])
                
                posts.append({
                    "title": title, 
                    "link": link, 
                    "snippet": snippet,
                    "date": post_date_formatted
                })
            
            if search_type == "cafearticle":
                posts = posts[:5]
                
            return posts
    except Exception as e:
        log(f"❌ 네이버 API 호출 에러 ({keyword}, {search_type}): {e}")
        return []
    return []

def generate_ai_summary(cafe_data, blog_data, news_data):
    if not GEMINI_API_KEY:
        return "⚠️ 제미나이 API 키가 설정되지 않았습니다."
        
    text_data = ""
    post_count = 0
    
    for category, data in [("카페", cafe_data), ("블로그", blog_data), ("기사", news_data)]:
        text_data += f"\n--- {category} 데이터 ---\n"
        for keyword, posts in data.items():
            if posts:
                text_data += f"[{keyword}]\n"
                for p in posts:
                    text_data += f"- 제목: {p['title']}\n- 내용: {p['snippet']}\n"
                    post_count += 1
                
    if post_count == 0:
        return "어제 하루 동안 새로 올라온 관련 콘텐츠가 없습니다."
        
    prompt = f"""다음은 어제 하루 동안 네이버 카페, 블로그, 뉴스에 올라온 우리 회사 서비스(도도포인트, 나우웨이팅) 관련 모니터링 데이터입니다.
이 데이터를 바탕으로 실무 담당자들이 즉시 활용할 수 있는 비즈니스 아이디어와 인사이트를 도출해주세요.
반드시 아래 두
