import urllib.request
import json
import os
import re
from datetime import datetime, timedelta
import email.utils
import google.generativeai as genai
import requests

# 1. 기본 세팅
KEYWORDS = ["도도포인트", "나우웨이팅"]

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

# 제미나이 AI 최신 모델 설정
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', raw_html).replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&apos;', "'")

def search_naver_api(keyword, search_type):
    # 1. 정확히 일치하는 단어만 검색하도록 큰따옴표("") 추가
    exact_keyword = f'"{keyword}"'
    encText = urllib.parse.quote(exact_keyword)
    
    # [수정됨] 어제 글을 하나도 놓치지 않기 위해 최대치인 100개를 한 번에 불러옵니다.
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
            
            # 한국 시간(KST) 기준 '어제' 날짜 계산
            kst_now = datetime.utcnow() + timedelta(hours=9)
            yesterday_kst = kst_now - timedelta(days=1)
            yesterday_str = yesterday_kst.strftime("%Y%m%d")
            
            for item in data['items']:
                # 날짜 필터링 로직 (어제 쓴 글만 통과)
                if search_type == "blog":
                    if item.get("postdate") != yesterday_str:
                        continue 
                elif search_type == "news":
                    pub_date_tuple = email.utils.parsedate_tz(item['pubDate'])
                    if pub_date_tuple:
                        pub_date = datetime.fromtimestamp(email.utils.mktime_tz(pub_date_tuple))
                        if pub_date.strftime("%Y%m%d") != yesterday_str:
                            continue

                title = clean_html(item['title'])
                link = item['link']
                snippet = clean_html(item['description'])
                posts.append({"title": title, "link": link, "snippet": snippet})
                
                # [수정됨] 5개 제한 로직 삭제! 이제 어제 발행된 글이라면 개수 제한 없이 모두 posts에 담깁니다.
                    
            return posts
    except Exception as e:
        print(f"네이버 API 호출 에러 ({keyword}, {search_type}): {e}")
        return []
    return []

def generate_ai_summary(cafe_data, news_data, blog_data):
    if not GEMINI_API_KEY:
        return "⚠️ 제미나이 API 키가 설정되지 않았습니다."
        
    text_data = ""
    post_count = 0
    
    for category, data in [("카페", cafe_data), ("기사", news_data), ("블로그", blog_data)]:
        text_data += f"\n--- {category} 데이터 ---\n"
        for keyword, posts in data.items():
            if posts:
                text_data += f"[{keyword}]\n"
                for p in posts:
                    text_data += f"- 제목: {p['title']}\n- 내용: {p['snippet']}\n"
                    post_count += 1
                
    if post_count == 0:
        return "어제 하루 동안 새로 올라온 관련 콘텐츠가 없습니다."
        
    prompt = f"""다음은 어제 하루 동안 네이버 카페, 뉴스 기사, 블로그에 올라온 우리 회사 서비스(도도포인트, 나우웨이팅) 관련 게시글 데이터입니다.
이 내용을 바탕으로 점주들이나 고객들의 반응, 불만 사항, 혹은 특이한 시장 동향(인사이트)을 파악해서 딱 2~3줄로 핵심만 요약해주세요.
말투는 비즈니스 보고서 형식(~음, ~함)으로 해주세요.

데이터:
{text_data}
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"요약 생성 중 오류 발생: {e}"

def send_slack_message(text, thread_ts=None):
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        return None
        
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "channel": SLACK_CHANNEL_ID,
        "text": text
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
        
    res = requests.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload)
    data = res.json()
    if data.get("ok"):
        return data.get("ts")
    return None

def format_section(title, data):
    message = f"*{title}*\n"
    for keyword in KEYWORDS:
        message += f"==============\n*[ {keyword} ] 어제자 검색 결과*\n"
