import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from supabase import create_client

# ---------------------------------------------------
# Supabase 설정
# ---------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("환경변수 SUPABASE_URL / SUPABASE_SERVICE_KEY 를 설정하세요.")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

SINGLES_URL = "https://www.officialcharts.com/charts/singles-chart/"
ALBUMS_URL = "https://www.officialcharts.com/charts/albums-chart/"


# ---------------------------------------------------
# 공통 유틸
# ---------------------------------------------------
def parse_stat(text: str):
    """
    'LW: 2' / 'Last week: 2' / 'Weeks: 6' 같은 문자열에서
    숫자만 뽑아서 int로 반환. 숫자가 없으면 None.
    """
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else None


# ---------------------------------------------------
# 메인 스크래핑 함수
# ---------------------------------------------------
def scrape_uk_chart(url: str, table: str):
    print(f"\n=== UK 차트 스크래핑 시작 ===")
    print(f"[URL] {url}")
    print(f"[TABLE] {table}\n")

    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 차트 날짜 추출 시도
    chart_date = datetime.utcnow().strftime("%Y-%m-%d")
    date_elem = soup.find(string=re.compile(r"\d{1,2}\s+\w+\s+\d{4}"))
    if date_elem:
        try:
            # 예: "22 November 2024" 형식 파싱
            date_str = re.search(r"\d{1,2}\s+\w+\s+\d{4}", date_elem.string).group()
            chart_date = datetime.strptime(date_str, "%d %B %Y").strftime("%Y-%m-%d")
            print(f"[INFO] 차트 날짜: {chart_date}")
        except:
            pass

    results = []

    # Official Charts의 실제 구조: 각 차트 항목이 특정 div/article 안에 있음
    # 'title' 클래스를 가진 요소들을 찾거나, 전체 구조를 파악
    
    # 방법 1: table 또는 section 기반 파싱
    chart_items = soup.select("table.chart-positions tr") or \
                  soup.select("div.chart-item") or \
                  soup.select("article.chart-item")
    
    if chart_items:
        print(f"[INFO] {len(chart_items)}개 차트 항목 발견 (구조화된 방식)")
        for item in chart_items:
            rank_elem = item.select_one(".position, .rank, [class*='position']")
            title_elem = item.select_one(".track, .title, a[href*='/search/']")
            artist_elem = item.select_one(".artist, a[href*='/artist/']")
            
            lw_elem = item.find(string=re.compile(r"Last\s+week|LW", re.I))
            peak_elem = item.find(string=re.compile(r"Peak", re.I))
            weeks_elem = item.find(string=re.compile(r"Weeks?\s+on\s+chart", re.I))
            
            rank = parse_stat(rank_elem.get_text()) if rank_elem else None
            title = title_elem.get_text(strip=True) if title_elem else "Unknown"
            artist = artist_elem.get_text(strip=True) if artist_elem else "Unknown"
            
            lw = parse_stat(lw_elem.find_next(string=re.compile(r"\d+"))) if lw_elem else None
            peak = parse_stat(peak_elem.find_next(string=re.compile(r"\d+"))) if peak_elem else None
            weeks = parse_stat(weeks_elem.find_next(string=re.compile(r"\d+"))) if weeks_elem else None
            
            results.append({
                "chart_date": chart_date,
                "rank": rank,
                "title": title,
                "artist": artist,
                "last_week_rank": lw,
                "peak_rank": peak,
                "weeks_on_chart": weeks,
            })
    
    # 방법 2: 기존 방식 개선 (fallback)
    else:
        print("[INFO] 폴백 방식으로 스크래핑 시작")
        number_tags = soup.find_all(string=re.compile(r"Number\s+\d+"))
        
        for num_tag in number_tags:
            m = re.search(r"\d+", str(num_tag))
            rank = int(m.group()) if m else None
            
            # 부모 컨테이너 찾기 (더 정확한 범위 지정)
            container = num_tag.find_parent(['div', 'section', 'article', 'tr', 'li'])
            if not container:
                container = num_tag.parent
            
            # 컨테이너 내에서만 링크 검색
            title = "Unknown"
            artist = "Unknown"
            lw = peak = weeks = None
            
            # 제목과 아티스트 추출 개선
            links = container.find_all("a", href=True)
            track_links = []
            artist_links = []
            
            for a in links:
                href = a.get("href", "")
                txt = a.get_text(strip=True)
                
                if not txt or txt.startswith("Image:"):
                    continue
                
                # URL 패턴으로 구분
                if "/search/" in href or "/tracks/" in href:
                    track_links.append(txt)
                elif "/artist/" in href:
                    artist_links.append(txt)
                else:
                    # href가 명확하지 않은 경우, 순서대로 추가
                    if not track_links:
                        track_links.append(txt)
                    elif not artist_links:
                        artist_links.append(txt)
            
            if track_links:
                title = track_links[0]
            if artist_links:
                artist = artist_links[0]
            
            # 통계 정보 추출 (컨테이너 내에서만)
            stats_text = container.get_text()
            
            # Last Week
            lw_match = re.search(r"(?:Last\s+week|LW)[:\s]*(\d+)", stats_text, re.I)
            if lw_match:
                lw = int(lw_match.group(1))
            
            # Peak
            peak_match = re.search(r"Peak[:\s]*(\d+)", stats_text, re.I)
            if peak_match:
                peak = int(peak_match.group(1))
            
            # Weeks on chart
            weeks_match = re.search(r"Weeks?[:\s]*(\d+)", stats_text, re.I)
            if weeks_match:
                weeks = int(weeks_match.group(1))
            
            results.append({
                "chart_date": chart_date,
                "rank": rank,
                "title": title,
                "artist": artist,
                "last_week_rank": lw,
                "peak_rank": peak,
                "weeks_on_chart": weeks,
            })

    # 로그 출력
    print(f"\n[수집 결과 샘플]")
    for item in results[:5]:
        print(f"#{item['rank']} - {item['title']} by {item['artist']}")
        print(f"  LW: {item['last_week_rank']}, Peak: {item['peak_rank']}, Weeks: {item['weeks_on_chart']}")

    # ---------------------------------------------------
    # Supabase 업서트
    # ---------------------------------------------------
    if results:
        print(f"\n{table} → {len(results)}개 항목 업서트 중…")
        supabase.table(table).upsert(results).execute()
        print(f"{table} 저장 완료! ✅\n")
    else:
        print(f"[WARN] {table}에 저장할 데이터가 없습니다.")


# ---------------------------------------------------
# main
# ---------------------------------------------------
def main():
    scrape_uk_chart(SINGLES_URL, "uk_singles_entries")
    scrape_uk_chart(ALBUMS_URL, "uk_albums_entries")
    print("🎉 모든 UK 차트 업데이트 완료!")


if __name__ == "__main__":
    main()
