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
    "도도포인트", "나우웨이팅", "소상공인지원", "사장님", 
    "배달비", "물가", "폐업", "지원금", "최저임금"
]

# 2. 추천 뉴스용 특수 키워드 (경제, 사회, 음식 카테고리 대체)
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
                
            # 🚨 질문자님 아이디어 반영! AI 과부하를 막기 위해 최신 핵심 기사 딱 5개만 가져옵니다.
            return posts[:5]
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

데이터:
{text_data}
"""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        headers = {'Content-Type': 'application/json'}
        
        response = requests.post(url, headers=headers, json=payload)
        result = response.json()
        if response.status_code == 200:
            return result['candidates'][0]['content']['parts'][0]['text'].strip()
        else:
            log(f"❌ AI 요약 거절: {result}")
            return f"요약 생성 중 오류가 발생했습니다."
    except Exception as e:
        return f"요약 생성 중 시스템 에러가 발생했습니다."

# AI 사장님 추천 뉴스 큐레이션 함수
def generate_ai_recommendations(recommend_data):
    if not GEMINI_API_KEY:
        return ""
        
    text_data = ""
    post_count = 0
    
    for keyword, posts in recommend_data.items():
        if posts:
            for p in posts:
                text_data += f"- 제목: {p['title']}\n- 링크: {p['link']}\n- 내용: {p['snippet']}\n\n"
                post_count += 1
                
    if post_count == 0:
        return "오늘은 추천할 만한 경제/사회/외식업 기사가 없습니다."
        
    prompt = f"""다음은 오늘자 자영업자, 소상공인과 관련된 경제, 사회, 외식업 트렌드 기사들입니다.
이 중에서 식당 사장님들이나 소상공인들이 장사하는 데 있어 반드시 읽어봐야 할 '가장 유익하고 중요한 기사 딱 3개'를 큐레이션 해주세요.

[작성 규칙]
1. 서론, 결론 없이 딱 추천 기사 3개만 포맷에 맞춰 작성하세요.
2. 기사 제목에 링크를 걸기 위해 슬랙 마크다운 포맷(<링크|제목>)을 반드시 지켜주세요.

[출력 포맷 예시]
• <http://기사링크.com|기사 원문 제목을 여기에 작성하세요>
  > 💡 추천 이유: (이 기사를 사장님이 왜 읽어야 하는지, 가게 운영에 어떤 도움이 되는지 1~2줄로 설명. ~요, ~다 말투 사용)

기사 데이터:
{text_data}
"""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        headers = {'Content-Type': 'application/json'}
        
        response = requests.post(url, headers=headers, json=payload)
        result = response.json()
        if response.status_code == 200:
            return result['candidates'][0]['content']['parts'][0]['text'].strip()
        else:
            log(f"❌ AI 큐레이션 거절: {result}")
            return f"추천 뉴스 생성 중 오류가 발생했습니다."
    except Exception as e:
        return f"추천 뉴스 생성 중 시스템 에러가 발생했습니다."

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
    
    if kst_now.weekday() == 0: # 월요일
        target_dates = [(kst_now - timedelta(days=i)).strftime("%Y%m%d") for i in range(1, 4)]
        date_label = "지난 주말(금,토,일)"
    else:
        target_dates = [(kst_now - timedelta(days=1)).strftime("%Y%m%d")]
        date_label = "어제 하루"
    
    log(f"🔍 1. 일반 키워드(9개) 및 추천용 키워드(3개) 기사를 수집 중입니다...")
    news_data = {}
    recommend_data = {}
    
    for keyword in KEYWORDS:
        news_data[keyword] = search_naver_api(keyword, "news", target_dates)
        
    for keyword in RECOMMEND_KEYWORDS:
        recommend_data[keyword] = search_naver_api(keyword, "news", target_dates)
        
    log("🧠 2. AI 요약 및 AI 추천 큐레이션을 생성합니다...")
    ai_summary = generate_ai_summary(news_data)
    ai_recommendations = generate_ai_recommendations(recommend_data)
    
    main_text = f"📣 *{today} 외식업/소상공인 트렌드 및 자사 뉴스 스크랩*\n\n💡 *오늘의 핵심 인사이트 (AI 요약)*\n> {ai_summary.replace(chr(10), chr(10)+'> ')}\n\n📌 *오늘의 사장님 추천 뉴스 (AI 큐레이션)*\n{ai_recommendations}"
    
    log("📤 3. 슬랙 채널에 메인 리포트 전송을 시도합니다...")
    main_ts = send_slack_message(main_text)
    
    if main_ts:
        log("✅ 메인 리포트 전송 성공! 스레드(댓글) 전송을 시작합니다...")
        send_slack_message(format_section("📰 세부 키워드별 뉴스 기사", news_data, date_label), thread_ts=main_ts)
        log("🎉 모든 작업이 성공적으로 끝났습니다!")

if __name__ == "__main__":
    main()
