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

def log(msg):
    print(f"👉 {msg}", flush=True)

# [수정 1] AI 에러 해결: 가장 안정적인 gemini-pro 모델로 롤백
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-pro')

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
                
                # [수정 2 & 3] 날짜 필터링 및 발행일 포맷팅
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
                    # 카페는 네이버 API에서 날짜 데이터를 주지 않아 필터링 불가! (미제공 표기)
                    post_date_formatted = "날짜 미제공"

                title = clean_html(item['title'])
                link = item['link']
                snippet = clean_html(item['description'])
                
                # 데이터 딕셔너리에 'date' 항목 추가
                posts.append({
                    "title": title, 
                    "link": link, 
                    "snippet": snippet,
                    "date": post_date_formatted
                })
            
            # 카페는 어제 글만 걸러낼 수 없으므로, 도배를 막기 위해 최신순 5개만 자릅니다.
            if search_type == "cafearticle":
                posts = posts[:5]
                
            return posts
    except Exception as e:
        log(f"❌ 네이버 API 호출 에러 ({keyword}, {search_type}): {e}")
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
        
    prompt = f"""다음은 최근 네이버 카페, 뉴스 기사, 블로그에 올라온 우리 회사 서비스(도도포인트, 나우웨이팅) 관련 게시글 데이터입니다.
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
        log("❌ 에러: 슬랙 봇 토큰이나 채널 ID가 없습니다!")
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
    else:
        log(f"❌ 슬랙 전송 거절됨! 상세 이유: {data}")
        return None

def format_section(title, data):
    message = f"*{title}*\n"
    for keyword in KEYWORDS:
        message += f"==============\n*[ {keyword} ] 검색 결과*\n"
        if not data[keyword]:
            message += "새로운 글이 없습니다.\n\n"
        else:
            for post in data[keyword]:
                # [수정 3] 제목 옆에 괄호 치고 발행일(date) 추가
                message += f"• <{post['link']}|{post['title']}> ({post['date']})\n  > _{post['snippet'][:100]}..._\n"
            message += "\n"
    return message

def main():
    log("🚀 스크랩 봇 작동을 시작합니다!")
    
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        log("❌ 네이버 API 키가 없습니다.")
        return

    kst_now = datetime.utcnow() + timedelta(hours=9)
    today = kst_now.strftime("%Y년 %m월 %d일")
    
    log("🔍 1. 네이버에서 데이터를 수집 중입니다...")
    cafe_data = {}
    news_data = {}
    blog_data = {}
    
    for keyword in KEYWORDS:
        cafe_data[keyword] = search_naver_api(keyword, "cafearticle")
        news_data[keyword] = search_naver_api(keyword, "news")
        blog_data[keyword] = search_naver_api(keyword, "blog")
        
    log("🧠 2. 데이터 수집 완료! AI 요약을 생성합니다...")
    ai_summary = generate_ai_summary(cafe_data, news_data, blog_data)
    
    main_text = f"📣 *{today} 미디어 콘텐츠 모니터링 스크랩*\n\n💡 *오늘의 핵심 인사이트 (AI 요약)*\n> {ai_summary.replace(chr(10), chr(10)+'> ')}"
    
    log("📤 3. 슬랙 채널에 메인 리포트 전송을 시도합니다...")
    main_ts = send_slack_message(main_text)
    
    if main_ts:
        log("✅ 메인 리포트 전송 성공! 스레드(댓글) 전송을 시작합니다...")
        send_slack_message(format_section("☕ 카페", cafe_data), thread_ts=main_ts)
        send_slack_message(format_section("📰 기사 (뉴스)", news_data), thread_ts=main_ts)
        send_slack_message(format_section("📝 블로그", blog_data), thread_ts=main_ts)
        log("🎉 모든 작업이 성공적으로 끝났습니다!")

if __name__ == "__main__":
    main()
