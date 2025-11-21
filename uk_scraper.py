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


def scrape_uk_chart(url: str, table: str):
    """UK Official Charts 스크래핑"""
    print(f"\n{'='*60}")
    print(f"UK 차트 스크래핑 시작")
    print(f"URL: {url}")
    print(f"TABLE: {table}")
    print(f"{'='*60}\n")

    # 페이지 요청
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 차트 날짜 (기본값: 오늘)
    chart_date = datetime.utcnow().strftime("%Y-%m-%d")

    results = []
    current_rank = 0

    # 실제 페이지 구조: 각 곡이 링크로 되어 있고, 그 뒤에 통계 정보가 나옴
    # 패턴: [곡 링크] [가수 링크] - LW: X, Peak: Y, Weeks: Z
    
    # 모든 링크 찾기
    all_links = soup.find_all("a", href=True)
    
    i = 0
    while i < len(all_links):
        link = all_links[i]
        href = link.get("href", "")
        text = link.get_text(strip=True)
        
        # 커버 이미지 스킵
        if text.startswith("Image:") or not text:
            i += 1
            continue
        
        # 곡 링크 찾기 (/songs/ 포함)
        if "/songs/" in href:
            current_rank += 1
            
            title = text
            artist = "Unknown"
            lw = peak = weeks = None
            
            # 다음 링크가 아티스트일 가능성 높음
            if i + 1 < len(all_links):
                next_link = all_links[i + 1]
                next_href = next_link.get("href", "")
                next_text = next_link.get_text(strip=True)
                
                # 아티스트 링크 확인
                if "/artist/" in next_href and next_text:
                    artist = next_text
                    i += 1  # 아티스트 링크 건너뛰기
            
            # 현재 링크 주변 텍스트에서 통계 정보 추출
            # 부모 또는 형제 요소에서 "LW:", "Peak:", "Weeks:" 찾기
            parent = link.find_parent(["div", "section", "li", "p"])
            if parent:
                stats_text = parent.get_text()
            else:
                # 다음 몇 개의 요소에서 찾기
                stats_text = ""
                for j in range(i, min(i + 10, len(all_links))):
                    if "/songs/" in all_links[j].get("href", ""):
                        break  # 다음 곡 시작
                    stats_text += " " + all_links[j].get_text()
            
            # 정규식으로 통계 추출
            lw_match = re.search(r"LW[:\s]*(\d+|New|RE)", stats_text, re.I)
            if lw_match:
                lw_val = lw_match.group(1)
                if lw_val.isdigit():
                    lw = int(lw_val)
                # "New"나 "RE"는 None으로 처리
            
            peak_match = re.search(r"Peak[:\s]*(\d+)", stats_text, re.I)
            if peak_match:
                peak = int(peak_match.group(1))
            
            weeks_match = re.search(r"Weeks[:\s]*(\d+)", stats_text, re.I)
            if weeks_match:
                weeks = int(weeks_match.group(1))
            
            # 결과 저장
            results.append({
                "chart_date": chart_date,
                "rank": current_rank,
                "title": title,
                "artist": artist,
                "last_week_rank": lw,
                "peak_rank": peak,
                "weeks_on_chart": weeks,
            })
            
            # 디버그: 처음 5개만 출력
            if current_rank <= 5:
                print(f"#{current_rank:2d} | {title[:40]:<40} | {artist[:30]:<30}")
                print(f"      LW: {lw or 'N/A':<4} | Peak: {peak or 'N/A':<4} | Weeks: {weeks or 'N/A'}")
                print()
        
        i += 1
    
    # 결과 확인
    print(f"\n총 {len(results)}개 항목 수집 완료")
    
    if not results:
        print("[경고] 수집된 데이터가 없습니다. HTML 구조가 변경되었을 수 있습니다.")
        return
    
    # Supabase 업서트
    print(f"\n{table} 테이블에 데이터 저장 중...")
    try:
        supabase.table(table).upsert(results).execute()
        print(f"✅ {table} 저장 완료!\n")
    except Exception as e:
        print(f"❌ 저장 실패: {e}")
        # 오류 발생 시 첫 번째 항목 출력
        if results:
            print(f"첫 번째 데이터 샘플: {results[0]}")


def main():
    """메인 실행 함수"""
    try:
        scrape_uk_chart(SINGLES_URL, "uk_singles_entries")
        scrape_uk_chart(ALBUMS_URL, "uk_albums_entries")
        print(f"\n{'='*60}")
        print("🎉 모든 UK 차트 업데이트 완료!")
        print(f"{'='*60}\n")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        raise


if __name__ == "__main__":
    main()
