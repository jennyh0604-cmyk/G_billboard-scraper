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


def parse_stat(text: str):
    """
    'LW: 2', 'Peak: 1', 'Weeks: 6' 같은 문자열에서
    숫자만 뽑아서 int로 반환. 숫자가 없으면 None.
    """
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else None




def scrape_uk_chart(url, table):
    """UK Official Charts 스크래핑 (Number n 기반)"""
    print(f"\n{'='*80}")
    print(f"📊 UK 차트 스크래핑")
    print(f"🔗 URL: {url}")
    print(f"💾 테이블: {table}")
    print(f"{'='*80}\n")

    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    chart_date = datetime.utcnow().strftime("%Y-%m-%d")
    results = []

    # 화면에 보이는 "Number 1", "Number 2" ... 텍스트 기준으로 곡 찾기
    number_tags = soup.find_all(string=re.compile(r"^Number\s+\d+"))

    if not number_tags:
        print("[WARN] 'Number n' 텍스트를 찾지 못했습니다. HTML 구조가 바뀐 것 같아요.")
        return

    for idx, num_tag in enumerate(number_tags, start=1):
        # ----- 순위(rank) -----
        m = re.search(r"\d+", str(num_tag))
        rank = int(m.group()) if m else None

        # ----- 제목 / 아티스트 -----
        # Number n 뒤에는 보통
        # 1) Image 링크 2개
        # 2) 제목 링크 1개
        # 3) 아티스트 링크 1개
        title_link = num_tag.find_next("a")
        # Image: ... 링크는 건너뛴다
        while title_link and title_link.get_text(strip=True).startswith("Image:"):
            title_link = title_link.find_next("a")

        if not title_link:
            continue

        artist_link = title_link.find_next("a")
        if not artist_link:
            continue

        title = title_link.get_text(strip=True)
        artist = artist_link.get_text(strip=True)

        # ----- LW / Peak / Weeks -----
        lw = peak = weeks = None

        # 아티스트 링크 이후로 나오는 텍스트들을 훑으면서
        # 다음 "Number n" 이 나오기 전까지에서 통계만 추출
        for s in artist_link.find_all_next(string=True):
            txt = s.strip()
            if not txt:
                continue

            # 다음 곡 블록으로 넘어가면 종료
            if txt.startswith("Number "):
                break

            lower = txt.lower()
            if "lw" in lower:
                lw = parse_stat(txt)
            elif "peak" in lower:
                peak = parse_stat(txt)
            elif "week" in lower:
                weeks = parse_stat(txt)

            if lw is not None and peak is not None and weeks is not None:
                break

        results.append({
            "chart_date": chart_date,
            "rank": rank,
            "title": title,
            "artist": artist,
            "last_week_rank": lw,
            "peak_rank": peak,
            "weeks_on_chart": weeks,
        })

        if idx <= 5:
            print(f"[DEBUG] #{rank} {title} / {artist} | LW={lw}, Peak={peak}, Weeks={weeks}")

    print(f"\n{'='*80}")
    print(f"✅ 총 {len(results)}개 항목 수집 완료")
    print(f"{'='*80}\n")

    if not results:
        print("⚠️  수집된 데이터가 없습니다.\n")
        return

    # Supabase 저장 (같은 chart_date 데이터 먼저 삭제 후 삽입)
    print(f"💾 {table} 테이블에 저장 중...")
    try:
        supabase.table(table).delete().eq("chart_date", chart_date).execute()
        print(f"   - {chart_date} 날짜 기존 레코드 삭제 완료")
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



