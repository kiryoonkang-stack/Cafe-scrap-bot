import urllib.request
import json
import os
import re
from datetime import datetime, timedelta
import email.utils
import requests

# 1. 9개 키워드로 확장
KEYWORDS = [
    "도도포인트", "나우웨이팅", "소상공인지원", "사장님", 
    "배달비", "물가", "폐업", "지원금", "최저임금"
]

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
                
            return posts
    except Exception as e:
        log(f"❌ 네이버 API 호출 에러 ({keyword}): {e}")
        return []
    return []

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
        
    # 🚨 거시적 트렌드(물가, 폐업 등)를 분석하도록 AI 프롬프트 재조정
    prompt = f"""다음은 우리 회사 서비스(도도포인트, 나우웨이팅) 및 외식업/소상공인 주요 이슈에 대한 네이버 기사 스크랩 데이터입니다.
이 데이터를 바탕으로 실무 담당자에게 즉시 도움이 될 핵심 인사이트를 도출해주세요.

[작성 규칙]
1. 불필요한 인사말이나 서론은 절대 쓰지 마세요.
2. 딱 1개의 문단으로, 5~7문장 내외로 압축해서 작성하세요.
3. 자사 브랜드(도도포인트, 나우웨이팅)가 언급된 기사가 있다면, 어떤 내용으로 보도되었는지 가장 먼저 구체적으로 짚어주세요.
4. 시장 트렌드(배달비, 물가, 최저임금, 폐업 등)와 정부 동향(소상공인지원, 지원금) 중 사장님(고객)들에게 가장 큰 영향을 미칠 이슈를 분석하고, 이것이 우리 비즈니스에 주는 시사점을 1~2문장으로 제안하세요.
5. 비즈니스 보고서 형식(~음, ~함)으로 작성하세요.

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
            log(f"❌ AI 요약 실패: {result}")
            return f"요약 생성 중 오류가 발생했습니다."
            
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

def format_section(title, data, date_label):
    message = f"*{title}*\n"
    for keyword in KEYWORDS:
        message += f"==============\n*[ {keyword} ] {date_label} 기사*\n"
        if not data[keyword]:
            message += "관련 기사가 없습니다.\n\n"
        else:
            for post in data[keyword]:
                message += f"• <{post['link']}|{post['title']}> ({post['date']})\n"
            message += "\n"
    return message

def main():
    log("🚀 스크랩 봇 작동을 시작합니다!")
    
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        log("❌ 네이버 API 키가 없습니다.")
        return

    kst_now = datetime.utcnow() + timedelta(hours=9)
    today = kst_now.strftime("%Y년 %m월 %d일")
    
    if kst_now.weekday() == 0:
        target_dates = [(kst_now - timedelta(days=i)).strftime("%Y%m%d") for i in range(1, 4)]
        date_label = "지난 주말(금,토,일)"
    else:
        target_dates = [(kst_now - timedelta(days=1)).strftime("%Y%m%d")]
        date_label = "어제 하루"
    
    log(f"🔍 1. 네이버에서 {date_label} '뉴스 기사' 데이터를 수집 중입니다...")
    news_data = {}
    
    for keyword in KEYWORDS:
        news_data[keyword] = search_naver_api(keyword, "news", target_dates)
        
    log("🧠 2. 데이터 수집 완료! AI 요약을 생성합니다...")
    ai_summary = generate_ai_summary(news_data)
    
    main_text = f"📣 *{today} 외식업/소상공인 트렌드 및 자사 뉴스 스크랩*\n\n💡 *오늘의 핵심 인사이트 (AI 요약)*\n> {ai_summary.replace(chr(10), chr(10)+'> ')}"
    
    log("📤 3. 슬랙 채널에 메인 리포트 전송을 시도합니다...")
    main_ts = send_slack_message(main_text)
    
    if main_ts:
        log("✅ 메인 리포트 전송 성공! 스레드(댓글) 전송을 시작합니다...")
        # 카페, 블로그 다 빼고 기사만 스레드로 전송
        send_slack_message(format_section("📰 주요 뉴스 기사", news_data, date_label), thread_ts=main_ts)
        log("🎉 모든 작업이 성공적으로 끝났습니다!")

if __name__ == "__main__":
    main()
