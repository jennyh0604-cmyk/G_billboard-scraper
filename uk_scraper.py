import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from supabase import create_client


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("환경변수 SUPABASE_URL / SUPABASE_SERVICE_KEY 를 설정하세요.")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

SINGLES_URL = "https://www.officialcharts.com/charts/singles-chart/"
ALBUMS_URL = "https://www.officialcharts.com/charts/albums-chart/"


def parse_stat(text: str):
    """ 'LW: 2', 'Peak: 1', 'Weeks: 6' → 숫자만 반환 """
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else None


def scrape_uk_chart(url: str, table: str):
    print(f"\n=== UK 차트 스크래핑 시작 ===\n[URL] {url}\n")

    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 차트 날짜
    chart_date = datetime.utcnow().strftime("%Y-%m-%d")

    results = []

    # "Number 1", "Number 2" ... 패턴으로 전체 곡 찾기
    number_tags = soup.find_all(string=re.compile(r"^Number\s+\d+"))

    if not number_tags:
        print("[경고] 'Number n' 패턴을 찾지 못했습니다. HTML 구조 변경 가능성 있음.")
        return

    for num_tag in number_tags:
        # rank 파싱
        m = re.search(r"\d+", num_tag)
        rank = int(m.group()) if m else None

        # 다음 두 <a> 태그: 첫 번째는 제목, 두 번째는 아티스트
        title_tag = num_tag.find_next("a")
        if not title_tag:
            continue
        artist_tag = title_tag.find_next("a")
        if not artist_tag:
            continue

        title = title_tag.get_text(strip=True)
        artist = artist_tag.get_text(strip=True)

        # LW / Peak / Weeks 찾기
        lw = peak = weeks = None

        # 아티스트 태그 뒤에서 다음 Number 발생 전까지 탐색
        for s in artist_tag.find_all_next(string=True):
            txt = s.strip()
            if not txt:
                continue

            # 다음 곡을 만나면 break
            if txt.startswith("Number "):
                break

            if txt.startswith("LW"):
                lw = parse_stat(txt)
            elif txt.startswith("Peak"):
                peak = parse_stat(txt)
            elif txt.startswith("Weeks"):
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

    print(f"{table} → {len(results)}개 항목 저장 중…")
    supabase.table(table).upsert(results).execute()
    print(f"{table} 저장 완료! 🎉\n")


def main():
    scrape_uk_chart(SINGLES_URL, "uk_singles_entries")
    scrape_uk_chart(ALBUMS_URL, "uk_albums_entries")
    print("🇬🇧 UK 차트 전체 업데이트 완료!")


if __name__ == "__main__":
    main()
