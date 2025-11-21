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
    'LW: 2' / 'Last week: 2' / 'Weeks on chart: 6' 같은 문자열에서
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

    # 일단 오늘 날짜를 차트 날짜로 사용
    chart_date = datetime.utcnow().strftime("%Y-%m-%d")
    results = []

    # 기존 코드처럼 track 요소 기준으로 파싱
    tracks = soup.select("div.track")

    if not tracks:
        print("[WARN] div.track 요소를 찾지 못했습니다. 사이트 구조가 바뀐 것 같아요.")
        return

    for idx, tr in enumerate(tracks, start=1):
        # ------------------------
        # Rank
        # ------------------------
        rank_tag = tr.select_one(".position")
        rank = int(rank_tag.get_text(strip=True)) if rank_tag else None

        # ------------------------
        # Title / Artist 기본 파싱
        # ------------------------
        title = "Unknown"
        artist = "Unknown"

        title_tag = tr.select_one(".title")
        artist_tag = tr.select_one(".artist")

        if title_tag:
            title = title_tag.get_text(strip=True)
        if artist_tag:
            artist = artist_tag.get_text(strip=True)

        # ------------------------
        # 보강: title-artist 블록에서 다시 시도
        # (일부 항목에서 제목에 가수 이름 일부가 들어가는 문제를 줄이기 위함)
        # ------------------------
        if (title == "Unknown" or " " not in title) or (artist == "Unknown"):
            ta_block = tr.select_one(".title-artist")
            if ta_block:
                links = ta_block.find_all("a")
                if len(links) >= 1:
                    # 첫 번째 링크를 제목으로 사용
                    title = links[0].get_text(strip=True)
                if len(links) >= 2:
                    # 나머지 링크들을 아티스트로 이어붙임 (여러 명일 수 있으니까)
                    artist_names = [a.get_text(strip=True) for a in links[1:]]
                    artist = " / ".join(artist_names)

        # ------------------------
        # LW / Peak / Weeks
        # ------------------------
        lw = peak = weeks = None
        stats = tr.select("ul.stats li")

        for li in stats:
            txt = li.get_text(strip=True)
            lower = txt.lower()

            # Last week / LW
            if "lw" in lower or "last" in lower:
                lw = parse_stat(txt)
            # Peak position
            elif "peak" in lower:
                peak = parse_stat(txt)
            # Weeks on chart
            elif "week" in lower:
                weeks = parse_stat(txt)

        # ------------------------
        # 결과 누적
        # ------------------------
        results.append({
            "chart_date": chart_date,
            "rank": rank,
            "title": title,
            "artist": artist,
            "last_week_rank": lw,
            "peak_rank": peak,
            "weeks_on_chart": weeks,
        })

        # 처음 몇 개는 콘솔에 찍어서 확인해볼 수 있게 (원하면 주석 처리해도 됨)
        if idx <= 3:
            print(f"[DEBUG] rank={rank}, title={title}, artist={artist}, "
                  f"LW={lw}, Peak={peak}, Weeks={weeks}")

    # ---------------------------------------------------
    # Supabase 업서트
    # ---------------------------------------------------
    print(f"\n{table} → {len(results)}개 항목 업서트 중…")
    supabase.table(table).upsert(results).execute()
    print(f"{table} 저장 완료! ✅\n")


# ---------------------------------------------------
# main
# ---------------------------------------------------
def main():
    scrape_uk_chart(SINGLES_URL, "uk_singles_entries")
    scrape_uk_chart(ALBUMS_URL, "uk_albums_entries")
    print("🎉 모든 UK 차트 업데이트 완료!")


if __name__ == "__main__":
    main()
