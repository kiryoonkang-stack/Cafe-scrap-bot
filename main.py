import urllib.request
import urllib.parse
import json
import os
import re
from datetime import datetime, timedelta
import email.utils
import requests

# 1. 일반 스크랩 키워드 (9개)
KEYWORDS = [
    "도도포인트", "나우웨이팅", "소상공인", "사장님", 
    "배달비", "물가", "폐업", "지원금", "최저임금"
]

# 2. 추천 뉴스용 특수 키워드
RECOMMEND_KEYWORDS = ["자영업자 경제", "소상공인 정책", "외식업 트렌드"]

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

def search_naver_api(keyword, search_type, target_dates):
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
            for item in data['items']:
                post_date_formatted = ""
                
                if search_type == "news":
                    pub_date_tuple = email.utils.parsedate_tz(item.get('pubDate', ''))
                    if pub_date_tuple:
                        pub_date = datetime.fromtimestamp(email.utils.mktime_tz(pub_date_tuple))
                        if pub_date.strftime("%Y%m%d") not in target_dates:
                            continue
                        post_date_formatted = pub_date.strftime("%Y.%m.%d")

                title = clean_html(item['title'])
                link = item['link']
                snippet = clean_html(item['description'])
                
                posts.append({
                    "title": title, 
                    "link": link, 
                    "snippet": snippet,
                    "date": post_date_formatted
                })
                
            # 🚨 핵심 수정: AI 과부하 및 슬랙 스레드 도배를 막기 위해 최신 기사 10개만 자릅니다!
            return posts[:10]
    except Exception as e:
        log(f"❌ 네이버 API 호출 에러 ({keyword}): {e}")
        return []
    return []

# 일반 기사 인사이트 요약 함수
def generate_ai_summary(news_data):
    if not GEMINI_API_KEY:
        return "⚠️ 제미나이 API 키가 설정되지 않았습니다."
        
    text_data = ""
    post_count = 0
    
    text_data += f"\n--- 기사 데이터 ---\n"
    for keyword, posts in news_data.items():
        if posts:
            text_data += f"[{keyword}]\n"
            for p in posts:
                text_data += f"- 제목: {p['title']}\n- 내용: {p['snippet']}\n"
                post_count += 1
                
    if post_count == 0:
        return "새로 수집된 관련 기사가 없습니다."
        
    prompt = f"""다음은 우리 회사 서비스(도도포인트, 나우웨이팅) 및 외식업/소상공인 주요 이슈에 대한 네이버 기사 스크랩 데이터입니다.
이 데이터를 바탕으로 실무 담당자에게 즉시 도움이 될 핵심 인사이트를 도출해주세요.

[작성 규칙]
1. 불필요한 인사말이나 서론은 절대 쓰지 마세요.
2. 딱 1개의 문단으로, 5~7문장 내외로 압축해서 작성하세요.
3. 자사 브랜드(도도포인트, 나우웨이팅)가 언급된 기사가 있다면, 어떤 내용으로 보도되었는지 가장 먼저 구체적으로 짚어주세요.
4. 시장 트렌드(배달비, 물가, 최저임금, 폐업 등)와 정부 동향 중 사장님(고객)들에게 가장 큰 영향을 미칠 이슈를 분석하고, 이것이 우리 비즈니스에 주는 시사점을 1~2문장으로 제안하세요.
5. 비즈니스 보고서 형식(~음, ~함)으로 작성하세요.
