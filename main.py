import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime

# 1. 검색할 키워드 목록
KEYWORDS = ["도도포인트", "나우웨이팅", "플레이스앤"]
# 2. 깃허브에 숨겨둔 슬랙 웹훅 주소 불러오기
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

def search_naver_blog(keyword):
    # 네이버 블로그 검색 URL
    url = f"https://search.naver.com/search.naver?where=blog&query={keyword}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    posts = []
    # 네이버 블로그 글 제목과 링크 추출 (상위 5개만)
    for item in soup.select('.api_txt_lines.total_tit')[:5]:
        title = item.text
        link = item.get('href')
        posts.append({"title": title, "link": link})
    return posts

def send_slack_message(message):
    if not SLACK_WEBHOOK_URL:
        print("슬랙 웹훅 URL이 설정되지 않았습니다.")
        return
    payload = {"text": message}
    requests.post(SLACK_WEBHOOK_URL, json=payload)

def main():
    today = datetime.now().strftime("%Y년 %m월 %d일")
    message = f"📣 *{today} 네이버 블로그 스크랩 리포트*\n\n"
    
    for keyword in KEYWORDS:
        message += f"*[ {keyword} ] 검색 결과*\n"
        posts = search_naver_blog(keyword)
        
        if not posts:
            message += "새로운 글이 없습니다.\n"
        else:
            for post in posts:
                message += f"• <{post['link']}|{post['title']}>\n"
        message += "\n"
        
    # 슬랙으로 메시지 전송
    send_slack_message(message)
    print("슬랙 메시지 전송 완료!")

if __name__ == "__main__":
    main()
