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
반드시 아래 두 가지 항목으로 나누어 비즈니스 보고서 형식(~음, ~함)으로 명확하게 요약해주세요.

[고객 반응 및 주요 이슈]
- (긍정/부정 반응, 불만 사항, 눈에 띄는 활용 사례 등 핵심 내용 2~3줄)

[비즈니스 인사이트 및 액션 제안]
- (위 내용을 바탕으로 마케팅, 기획, 영업 담당자가 참고할 만한 아이디어나 시사점 2~3줄)

데이터:
{text_data}
"""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        headers = {'Content-Type': 'application/json'}
        
        response = requests.post(url, headers=headers, json=payload)
        result = response.json()
        
        if response.status_code == 200:
            return result['candidates'][0]['content']['parts'][0]['text'].strip()
        else:
            log(f"❌ AI 요약 실패 (구글 서버 거절): {result}")
            return f"요약 생성 중 오류가 발생했습니다. (구글 API 에러)"
            
    except Exception as e:
        log(f"❌ AI 요약 코드 에러: {e}")
        return f"요약 생성 중 시스템 에러가 발생했습니다."

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
    ai_summary = generate_ai_summary(cafe_data, blog_data, news_data)
    
    main_text = f"📣 *{today} 미디어 콘텐츠 모니터링 스크랩*\n\n💡 *오늘의 핵심 인사이트 (AI 요약)*\n> {ai_summary.replace(chr(10), chr(10)+'> ')}"
    
    log("📤 3. 슬랙 채널에 메인 리포트 전송을 시도합니다...")
    main_ts = send_slack_message(main_text)
    
    if main_ts:
        log("✅ 메인 리포트 전송 성공! 스레드(댓글) 전송을 시작합니다...")
        send_slack_message(format_section("☕ 카페", cafe_data), thread_ts=main_ts)
        send_slack_message(format_section("📝 블로그", blog_data), thread_ts=main_ts)
        send_slack_message(format_section("📰 기사 (뉴스)", news_data), thread_ts=main_ts)
        log("🎉 모든 작업이 성공적으로 끝났습니다!")

if __name__ == "__main__":
    main()
