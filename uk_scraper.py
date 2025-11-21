import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from supabase import create_client

# Supabase 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("환경변수 SUPABASE_URL / SUPABASE_SERVICE_KEY 를 설정하세요.")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

SINGLES_URL = "https://www.officialcharts.com/charts/singles-chart/"
ALBUMS_URL = "https://www.officialcharts.com/charts/albums-chart/"


def extract_stats_from_text(text):
    """텍스트에서 LW, Peak, Weeks 추출"""
    lw = peak = weeks = None
    
    # LW 추출
    lw_match = re.search(r'LW:\s*(\d+)', text)
    if lw_match:
        lw = int(lw_match.group(1))
    elif re.search(r'LW:\s*(New|RE)', text, re.I):
        lw = None  # New나 RE는 None 처리
    
    # Peak 추출
    peak_match = re.search(r'Peak:\s*(\d+)', text)
    if peak_match:
        peak = int(peak_match.group(1))
    
    # Weeks 추출
    weeks_match = re.search(r'Weeks:\s*(\d+)', text)
    if weeks_match:
        weeks = int(weeks_match.group(1))
    
    return lw, peak, weeks



def scrape_uk_chart(url, table):
    """UK Official Charts 스크래핑 - 완전히 새로운 방식"""
    print(f"\n{'='*80}")
    print(f"📊 UK 차트 스크래핑")
    print(f"🔗 URL: {url}")
    print(f"💾 테이블: {table}")
    print(f"{'='*80}\n")
    
    # 페이지 요청
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.text, "html.parser")
    chart_date = datetime.utcnow().strftime("%Y-%m-%d")
    
    # Singles / Albums 구분
    is_singles = "singles" in url.lower()
    content_url_pattern = "/songs/" if is_singles else "/albums/"
    
    print(f"📌 차트 유형: {'Singles' if is_singles else 'Albums'}")
    print(f"📅 차트 날짜: {chart_date}\n")
    
    # 전체 텍스트 가져오기
    page_text = soup.get_text()
    
    # 모든 링크 찾기
    all_links = soup.find_all("a", href=True)
    
    results = []
    seen_titles = set()
    
    for link in all_links:
        href = link.get("href", "")
        text = link.get_text(strip=True)
        
        # 해당 차트의 컨텐츠 링크만 처리
        if content_url_pattern not in href:
            continue
        
        # 이미지 링크 제외
        if text.startswith("Image:") or not text:
            continue
        
        # 중복 체크
        if text in seen_titles:
            continue
        seen_titles.add(text)
        
        title = text
        rank = len(results) + 1
        artist = "Unknown"
        
        # 아티스트 찾기: 현재 링크 다음에 나오는 /artist/ 링크
        next_elem = link.find_next("a", href=re.compile(r"/artist/"))
        if next_elem:
            artist_text = next_elem.get_text(strip=True)
            if artist_text and not artist_text.startswith("Image:"):
                artist = artist_text
        
        # 통계 정보 추출: 제목 텍스트 위치 기준으로 검색
        lw = peak = weeks = None
        title_pos = page_text.find(title)
        
        if title_pos != -1:
            # 제목 위치부터 300자 범위에서 통계 찾기
            search_text = page_text[title_pos:title_pos + 300]
            lw, peak, weeks = extract_stats_from_text(search_text)
        
        # 결과 저장
        results.append({
            "chart_date": chart_date,
            "rank": rank,
            "title": title,
            "artist": artist,
            "last_week_rank": lw,
            "peak_rank": peak,
            "weeks_on_chart": weeks,
        })
        
        # 처음 10개 출력
        if rank <= 10:
            print(f"#{rank:2d} │ {title[:40]:<40} │ {artist[:25]:<25}")
            lw_str = str(lw) if lw else "New"
            print(f"     LW: {lw_str:>4} │ Peak: {peak or '-':>3} │ Weeks: {weeks or '-'}")
            print()
    
    # 통계 출력
    print(f"\n{'='*80}")
    print(f"✅ 총 {len(results)}개 항목 수집 완료")
    
    if results:
        lw_count = sum(1 for r in results if r["last_week_rank"] is not None)
        peak_count = sum(1 for r in results if r["peak_rank"] is not None)
        weeks_count = sum(1 for r in results if r["weeks_on_chart"] is not None)
        
        print(f"\n📊 통계 데이터 수집률:")
        print(f"   • Last Week: {lw_count}/{len(results)} ({lw_count/len(results)*100:.1f}%)")
        print(f"   • Peak: {peak_count}/{len(results)} ({peak_count/len(results)*100:.1f}%)")
        print(f"   • Weeks: {weeks_count}/{len(results)} ({weeks_count/len(results)*100:.1f}%)")
    print(f"{'='*80}\n")
    
    if not results:
        print("⚠️  수집된 데이터가 없습니다.\n")
        return
    
       # Supabase 저장
    print(f"💾 {table} 테이블에 저장 중...")

    try:
        # 1) 같은 chart_date 데이터 먼저 삭제
        supabase.table(table).delete().eq("chart_date", chart_date).execute()
        print(f"   - {chart_date} 날짜 기존 레코드 삭제 완료")

        # 2) 새 결과 삽입
        supabase.table(table).insert(results).execute()
        print(f"✅ {table} 저장 완료! (총 {len(results)}개)\n")

    except Exception as e:
        print(f"❌ 저장 실패: {e}\n")
        raise



def main():
    """메인 실행"""
    print("\n" + "="*80)
    print("🎵 UK Official Charts 스크래핑 시작")
    print("="*80)
    
    try:
        scrape_uk_chart(SINGLES_URL, "uk_singles_entries")
        scrape_uk_chart(ALBUMS_URL, "uk_albums_entries")
        
        print("\n" + "="*80)
        print("🎉 모든 차트 업데이트 완료!")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()


