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


def parse_stat_value(text: str) -> int:
    """통계 값에서 숫자 추출"""
    if not text:
        return None
    text = text.strip()
    # "New", "RE" 같은 특수값은 None 처리
    if text.upper() in ["NEW", "RE", "-"]:
        return None
    # 숫자만 추출
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def scrape_uk_chart(url: str, table: str):
    """UK Official Charts 스크래핑 - 실제 HTML 구조 기반"""
    print(f"\n{'='*70}")
    print(f"🎵 UK 차트 스크래핑 시작")
    print(f"📍 URL: {url}")
    print(f"💾 TABLE: {table}")
    print(f"{'='*70}\n")

    # 페이지 요청
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    
    html_content = resp.text
    soup = BeautifulSoup(html_content, "html.parser")

    # 차트 날짜 (기본값: 오늘)
    chart_date = datetime.utcnow().strftime("%Y-%m-%d")

    results = []
    
    # 실제 HTML에서 패턴 찾기:
    # 1) 제목 링크: /songs/xxx
    # 2) 아티스트 링크: /artist/xxx
    # 3) 통계: "LW: 1," "Peak: 2," "Weeks: 3"
    
    # 전체 텍스트를 가져와서 패턴 매칭
    page_text = soup.get_text()
    
    # 각 곡마다 나타나는 패턴: [곡제목] [아티스트] LW: X, Peak: Y, Weeks: Z
    # 또는: [곡제목] [아티스트] - LW: X, - Peak: Y, - Weeks: Z
    
    # 모든 /songs/ 링크 찾기 (곡 제목)
    # Singles는 /songs/, Albums는 /albums/ 사용
    if "singles" in url.lower():
        content_links = soup.find_all("a", href=re.compile(r"/songs/"))
        artist_pattern = r"/artist/"
    else:
        content_links = soup.find_all("a", href=re.compile(r"/albums/"))
        artist_pattern = r"/artist/"
    
    print(f"📊 발견된 항목 링크: {len(content_links)}개\n")
    
    for idx, song_link in enumerate(content_links, start=1):
        title = song_link.get_text(strip=True)
        if not title or title.startswith("Image:"):
            continue
            
        rank = idx
        artist = "Unknown"
        lw = peak = weeks = None
        
        # 곡 링크 다음에 있는 아티스트 링크 찾기
        next_sibling = song_link.find_next_sibling("a")
        if not next_sibling:
            # 형제가 없으면 부모의 다음 링크 찾기
            parent = song_link.parent
            if parent:
                next_link = parent.find_next("a")
                if next_link and artist_pattern in next_link.get("href", ""):
                    artist = next_link.get_text(strip=True)
        elif artist_pattern in next_sibling.get("href", ""):
            artist = next_sibling.get_text(strip=True)
        
        # 통계 정보 추출: 현재 링크부터 넓은 범위에서 찾기
        search_start = html_content.find(title)
        if search_start != -1:
            # 제목 위치부터 500자 범위에서 통계 찾기
            search_text = html_content[search_start:search_start + 500]
            
            # 실제 HTML 패턴: "LW: 1," 또는 "- LW: 1," 또는 "LW:1"
            # LW 추출 - 여러 패턴 시도
            lw_patterns = [
                r"LW[:\s]+(\d+)",  # LW: 1 또는 LW:1
                r"Last\s+week[:\s]+(\d+)",  # Last week: 1
                r"-\s*LW[:\s]+(\d+)",  # - LW: 1
            ]
            for pattern in lw_patterns:
                lw_match = re.search(pattern, search_text, re.I)
                if lw_match:
                    lw = int(lw_match.group(1))
                    break
            
            # New나 RE 처리
            if re.search(r"LW[:\s]+(New|RE)", search_text, re.I):
                lw = None
            
            # Peak 추출
            peak_patterns = [
                r"Peak[:\s]+(\d+)",
                r"-\s*Peak[:\s]+(\d+)",
            ]
            for pattern in peak_patterns:
                peak_match = re.search(pattern, search_text, re.I)
                if peak_match:
                    peak = int(peak_match.group(1))
                    break
            
            # Weeks 추출
            weeks_patterns = [
                r"Weeks[:\s]+(\d+)",
                r"-\s*Weeks[:\s]+(\d+)",
            ]
            for pattern in weeks_patterns:
                weeks_match = re.search(pattern, search_text, re.I)
                if weeks_match:
                    weeks = int(weeks_match.group(1))
                    break
        
        # 데이터 저장
        entry = {
            "chart_date": chart_date,
            "rank": rank,
            "title": title,
            "artist": artist,
            "last_week_rank": lw,
            "peak_rank": peak,
            "weeks_on_chart": weeks,
        }
        results.append(entry)
        
        # 처음 10개 출력
        if rank <= 10:
            print(f"#{rank:3d} | {title[:35]:<35} | {artist[:25]:<25}")
            print(f"       LW: {str(lw) if lw else 'New':>4} | Peak: {peak or '-':>3} | Weeks: {weeks or '-':>3}")
            print()
    
    # 결과 확인
    print(f"\n{'='*70}")
    print(f"✅ 총 {len(results)}개 항목 수집 완료")
    
    if not results:
        print("⚠️  수집된 데이터가 없습니다.")
        print(f"{'='*70}\n")
        return
    
    # 통계 데이터 수집률 확인
    lw_count = sum(1 for r in results if r["last_week_rank"] is not None)
    peak_count = sum(1 for r in results if r["peak_rank"] is not None)
    weeks_count = sum(1 for r in results if r["weeks_on_chart"] is not None)
    
    print(f"📈 데이터 수집률:")
    print(f"   - Last Week: {lw_count}/{len(results)} ({lw_count/len(results)*100:.1f}%)")
    print(f"   - Peak: {peak_count}/{len(results)} ({peak_count/len(results)*100:.1f}%)")
    print(f"   - Weeks: {weeks_count}/{len(results)} ({weeks_count/len(results)*100:.1f}%)")
    print(f"{'='*70}\n")
    
    # Supabase 업서트
    print(f"💾 {table} 테이블에 저장 중...")
    try:
        supabase.table(table).upsert(results).execute()
        print(f"✅ {table} 저장 완료!\n")
    except Exception as e:
        print(f"❌ 저장 실패: {e}")
        print(f"샘플 데이터: {results[0] if results else 'None'}")
        raise


def main():
    """메인 실행 함수"""
    try:
        scrape_uk_chart(SINGLES_URL, "uk_singles_entries")
        scrape_uk_chart(ALBUMS_URL, "uk_albums_entries")
        
        print(f"\n{'='*70}")
        print("🎉 모든 UK 차트 업데이트 완료!")
        print(f"{'='*70}\n")
    except Exception as e:
        print(f"\n❌오류 발생: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
