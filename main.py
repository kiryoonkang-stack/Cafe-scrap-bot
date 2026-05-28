import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime
import google.generativeai as genai

# 1. 기본 세팅
KEYWORDS = ["도도포인트", "나우웨이팅", "플레이스앤"]
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 제미나이 AI 설정
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash') # 가볍고 빠른 최신 모델

def search_naver_cafe(keyword):
    # where=article (카페글), nso=so:dd,p:1d (최신순 정렬, 최근 1일 이내)
    url = f"https://search.naver.com/search.naver?where=article&query={keyword}&nso=so:dd,p:1d"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    posts = []
    titles = soup.select('.api_txt_lines.total_tit')
    snippets = soup.select('.api_txt_lines.dsc_txt') # 본문 내용 미리보기
    
    # 상위 5개까지만 수집 (제목, 링크, 본문 일부)
    for i in range(min(5, len(titles))):
        title = titles[i].text
        link = titles[i].get('href')
        snippet = snippets[i].text if i < len(snippets) else ""
        posts.append({"title": title, "link": link, "snippet": snippet})
        
    return posts

def generate_ai_summary(all_posts_data):
    if not GEMINI_API_KEY:
        return "⚠️ 제미나이 API 키가 등록되지 않아 요약을 생성할 수 없습니다."
        
    # AI에게 읽힐 데이터 텍스트로 합치기
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
        
    # AI에게 내릴 프롬프트(명령어)
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
        return f"요약 생성 중 오류가 발생했습니다: {e}"

def send_slack_message(message):
    if not SLACK_WEBHOOK_URL:
        print("슬랙 웹훅 URL이 없습니다.")
        return
    payload = {"text": message}
    requests.post(SLACK_WEBHOOK_URL, json=payload)

def main():
    today = datetime.now().strftime("%Y년 %m월 %d일")
    all_posts_data = {}
    
    # 1. 모든 키워드에 대해 전일 카페 글 수집
    for keyword in KEYWORDS:
        all_posts_data[keyword] = search_naver_cafe(keyword)
        
    # 2. 제미나이 AI를 활용해 요약 인사이트 생성
    ai_summary = generate_ai_summary(all_posts_data)
    
    # 3. 슬랙 리포트 조립 (맨 위에 AI 요약 배치)
    message = f"📣 *{today} 네이버 카페 모니터링 리포트*\n\n"
    message += f"💡 *오늘의 핵심 인사이트 (AI 요약)*\n> {ai_summary.replace(chr(10), chr(10)+'> ')}\n\n"
    
    for keyword, posts in all_posts_data.items():
        message += f"==============\n*[ {keyword} ] 최근 1일 검색 결과*\n"
        if not posts:
            message += "새로운 글이 없습니다.\n\n"
        else:
            for post in posts:
                message += f"• <{post['link']}|{post['title']}>\n"
            message += "\n"
            
    # 4. 슬랙으로 전송
    send_slack_message(message)
    print("슬랙 메시지 전송 완료!")

if __name__ == "__main__":
    main()
