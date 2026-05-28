import urllib.request
import json
import os
import re
from datetime import datetime
import google.generativeai as genai
import requests

# 1. 기본 세팅 (키워드 축소)
KEYWORDS = ["도도포인트", "나우웨이팅"]

# 깃허브 시크릿에서 정보 가져오기
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

# 제미나이 AI 설정 (안정적인 gemini-pro 모델로 변경하여 에러 해결)
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-pro')

# HTML 태그 제거용 함수
def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    # 특수기호 깔끔하게 정리
    return re.sub(cleanr, '', raw_html).replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&apos;', "'")

def search_naver_api(keyword, search_type):
    encText = urllib.parse.quote(keyword)
    # display=5 (5개씩 가져오기)
    url = f"https://openapi.naver.com/v1/search/{search_type}.json?query={encText}&display=5&sort=date"
    
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
                title = clean_html(item['title'])
                link = item['link']
                # 본문 미리보기 (snippet)
                snippet = clean_html(item['description'])
                posts.append({"title": title, "link": link, "snippet": snippet})
            return posts
    except Exception as e:
        print(f"네이버 API 호출 에러 ({keyword}, {search_type}): {e}")
        return []
    return []

def generate_ai_summary(cafe_data, news_data, blog_data):
    if not GEMINI_API_KEY:
        return "⚠️ 제미나이 API 키가 등록되지 않았습니다."
        
    text_data = ""
    post_count = 0
    
    # 3가지 데이터 취합
    for category, data in [("카페", cafe_data), ("기사", news_data), ("블로그", blog_data)]:
        text_data += f"\n--- {category} 데이터 ---\n"
        for keyword, posts in data.items():
            if posts:
                text_data += f"[{keyword}]\n"
                for p in posts:
                    text_data += f"- 제목: {p['title']}\n- 내용: {p['snippet']}\n"
                    post_count += 1
                
    if post_count == 0:
        return "어제 하루 동안 새로 올라온 글이 없습니다."
        
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

# 슬랙 메시지 전송 함수 (스레드 기능 추가)
def send_slack_message(text, thread_ts=None):
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        print("슬랙 봇 토큰 또는 채널 ID가 없습니다.")
        return None
        
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "channel": SLACK_CHANNEL_ID,
        "text": text
    }
    # thread_ts가 있으면 댓글(스레드)로 작성됨
    if thread_ts:
        payload["thread_ts"] = thread_ts
        
    res = requests.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload)
    data = res.json()
    if data.get("ok"):
        return data.get("ts") # 방금 보낸 메시지의 고유 시간값 반환 (댓글 달 때 필요함)
    else:
        print(f"슬랙 전송 실패: {data}")
        return None

def format_section(title, data):
    message = f"*{title}*\n"
    for keyword in KEYWORDS:
        message += f"==============\n*[ {keyword} ] 최근 검색 결과*\n"
        if not data[keyword]:
            message += "새로운 글이 없습니다.\n\n"
        else:
            for post in data[keyword]:
                # 제목 아래에 본문 미리보기를 100자까지 잘라서 기울임꼴(_) 인용구(>)로 넣음
                message += f"• <{post['link']}|{post['title']}>\n  > _{post['snippet'][:100]}..._\n"
            message += "\n"
    return message

def main():
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("네이버 API 키가 없습니다. 설정해주세요.")
        return

    today = datetime.now().strftime("%Y년 %m월 %d일")
    cafe_data = {}
    news_data = {}
    blog_data = {}
    
    # 1. 카페, 기사, 블로그 순서로 데이터 수집
    for keyword in KEYWORDS:
        cafe_data[keyword] = search_naver_api(keyword, "cafearticle")
        news_data[keyword] = search_naver_api(keyword, "news")
        blog_data[keyword] = search_naver_api(keyword, "blog")
        
    # 2. AI 요약 생성
    ai_summary = generate_ai_summary(cafe_data, news_data, blog_data)
    
    # 3. 메인 메시지 전송 (제목 + AI 요약만)
    main_text = f"📣 *{today} 네이버 모니터링 리포트*\n\n💡 *오늘의 핵심 인사이트 (AI 요약)*\n> {ai_summary.replace(chr(10), chr(10)+'> ')}"
    
    # main_ts는 방금 쓴 메인 글의 위치(시간값)를 의미합니다.
    main_ts = send_slack_message(main_text)
    
    # 4. 메인 글이 성공적으로 써졌다면, 그 아래에 스레드(댓글)로 상세 내용 전송
    if main_ts:
        send_slack_message(format_section("☕ 카페", cafe_data), thread_ts=main_ts)
        send_slack_message(format_section("📰 기사 (뉴스)", news_data), thread_ts=main_ts)
        send_slack_message(format_section("📝 블로그", blog_data), thread_ts=main_ts)
        print("슬랙 스레드 메시지 전송 완료!")

if __name__ == "__main__":
    main()
