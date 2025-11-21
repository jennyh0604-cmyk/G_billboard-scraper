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


def parse_stat(text):
    """ 'LW: 2' → 2 """
    num = re.findall(r"\d+", text)
    return int(num[0]) if num else None


def scrape_uk_chart(url, table):
    print(f"\n=== UK 차트 스크래핑 시작 ===\n[URL] {url}\n")

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    chart_date = datetime.utcnow().strftime("%Y-%m-%d")
    results = []

    tracks = soup.select("div.track")   # 핵심 선택자!

    if not tracks:
        print("[WARN] track 요소를 찾지 못했습니다. 사이트 구조 변경 가능.")
        return

    for tr in tracks:
        # rank
        rank_tag = tr.select_one(".position")
        rank = int(rank_tag.text.strip()) if rank_tag else None

        # title
        title_tag = tr.select_one(".title")
        title = title_tag.text.strip() if title_tag else "Unknown"

        # artist
        artist_tag = tr.select_one(".artist")
        artist = artist_tag.text.strip() if artist_tag else "Unknown"

        # LW / Peak / Weeks
        lw = peak = weeks = None
        stats = tr.select("ul.stats li")

        for li in stats:
            txt = li.get_text(strip=True)
            if txt.startswith("LW"):
                lw = parse_stat(txt)
            elif txt.startswith("Peak"):
                peak = parse_stat(txt)
            elif txt.startswith("Weeks"):
                weeks = parse_stat(txt)

        results.append({
            "chart_date": chart_date,
            "rank": rank,
            "title": title,
            "artist": artist,
            "last_week_rank": lw,
            "peak_rank": peak,
            "weeks_on_chart": weeks
        })

    # Supabase 업서트
    supabase.table(table).upsert(results).execute()
    print(f"{table} 저장 완료 ({len(results)}개 항목)\n")


def main():
    scrape_uk_chart(SINGLES_URL, "uk_singles_entries")
    scrape_uk_chart(ALBUMS_URL, "uk_albums_entries")
    print("🎉 모든 UK 차트 업데이트 완료!")


if __name__ == "__main__":
    main()
