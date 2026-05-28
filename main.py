import urllib.request
import json
import os
import re
from datetime import datetime, timedelta
import google.generativeai as genai

# 1. 기본 세팅
KEYWORDS = ["도도포인트", "나우웨이팅", "플레이스앤"]
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

# 제미나이 AI 설정
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

# HTML 태그 제거용 함수 (<b>도도포인트</b> -> 도도포인트)
def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', raw_html).replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>')

def search_naver_api(keyword, search_type="cafearticle"):
    # search_type: "cafearticle"(카페) 또는 "blog"(블로그)
    encText = urllib.parse.quote(keyword)
    # sort=date (최신순 정렬), display=10 (10개 가져오기)
    url = f"https://openapi.naver.com/v1/search/{search_type}.json?query={encText}&display=10&sort=date"
    
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
            # 어제 날짜 구하기 (YYYYMMDD 형식 비교용)
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            
            for item in data['items']:
                # 블로그 API는 'postdate'(YYYYMMDD), 카페 API는 생성이슈로 날짜가 안 올수 있으므로 최근 5개만 무조건 가져오는 식으로 일단 진행
                title = clean_html(item['title'])
                link = item['link']
                snippet = clean_html(item['description'])
                posts.append({"title": title, "link": link, "snippet": snippet})
            
            return posts[:5] # 최신 5개만 자르기
    except Exception as e:
        print(f"네이버 API 호출 에러 ({keyword}): {e}")
        return []
    
    return []

def generate_ai_summary(all_posts_data):
    if not GEMINI_API_KEY:
        return "⚠️ 제미나이 API 키가 등록되지 않았습니다."
        
    text_data = ""
    post_count = 0
    for keyword, posts in all_posts_data.items():
        if posts:
            text_data += f"\n[{keyword}]\n"
            for p in posts:
                text_data += f"- 제목: {p['title']}\n- 내용: {p['snippet']}\n"
                post_count += 1
                
    if post_count == 0:
        return "어제 하루 동안 새로 올라온 카페 글이 없습니다."
        
    prompt = f"""다음은 어제 하루 동안 네이버 카페에 올라온 우리 회사 서비스(도도포인트, 나우웨이팅, 플레이스앤) 관련 게시글 데이터입니다.
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

def send_slack_message(message):
    if not SLACK_WEBHOOK_URL:
        return
    payload = {"text": message}
    import requests
    requests.post(SLACK_WEBHOOK_URL, json=payload)

def main():
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("네이버 API 키가 없습니다. 설정해주세요.")
        return

    today = datetime.now().strftime("%Y년 %m월 %d일")
    all_posts_data = {}
    
    for keyword in KEYWORDS:
        # 카페 글 검색 API 호출
        all_posts_data[keyword] = search_naver_api(keyword, "cafearticle")
        
    ai_summary = generate_ai_summary(all_posts_data)
    
    message = f"📣 *{today} 네이버 카페 모니터링 리포트*\n\n"
    message += f"💡 *오늘의 핵심 인사이트 (AI 요약)*\n> {ai_summary.replace(chr(10), chr(10)+'> ')}\n\n"
    
    for keyword, posts in all_posts_data.items():
        message += f"==============\n*[ {keyword} ] 최근 카페 검색 결과*\n"
        if not posts:
            message += "새로운 글이 없습니다.\n\n"
        else:
            for post in posts:
                message += f"• <{post['link']}|{post['title']}>\n"
            message += "\n"
            
    send_slack_message(message)
    print("슬랙 메시지 전송 완료!")

if __name__ == "__main__":
    main()
