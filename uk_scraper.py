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

    # 일단 오늘 날짜를 차트 날짜로 사용
    chart_date = datetime.utcnow().strftime("%Y-%m-%d")
    results = []

    # 화면에 보이는 "Number 1", "Number 2" ... 텍스트 기준으로 곡 찾기
    number_tags = soup.find_all(string=re.compile(r"Number\s+\d+"))

    if not number_tags:
        print("[WARN] 'Number n' 텍스트를 찾지 못했습니다. HTML 구조가 바뀐 것 같아요.")
        return

    for idx, num_tag in enumerate(number_tags, start=1):
        # ----- 순위(rank) -----
        m = re.search(r"\d+", str(num_tag))
        rank = int(m.group()) if m else None

        # ----- 제목 / 아티스트 -----
        # 'Number n' 이후에 나오는 a 태그들 중
        # 텍스트가 'Image:' 로 시작하는 것은 커버 이미지라서 제외
        title = "Unknown"
        artist = "Unknown"

        candidate_links = num_tag.find_all_next("a", limit=8)
        non_image_links = []
        for a in candidate_links:
            txt = a.get_text(strip=True)
            if not txt:
                continue
            if txt.startswith("Image:"):
                continue
            non_image_links.append(a)

        if len(non_image_links) >= 1:
            title = non_image_links[0].get_text(strip=True)
        if len(non_image_links) >= 2:
            artist = non_image_links[1].get_text(strip=True)

        # ----- LW / Peak / Weeks -----
        lw = peak = weeks = None

        # 통계 텍스트는 보통 제목/아티스트 바로 뒤에 나오는 리스트에 있음
        # 마지막 non_image 링크 뒤에서부터 문자열들을 훑으면서 찾는다.
        start_anchor = non_image_links[-1] if non_image_links else num_tag

        for s in start_anchor.find_all_next(string=True):
            txt = s.strip()
            if not txt:
                continue

            # 다음 곡의 "Number n"을 만나면 현재 곡 블록 종료
            if re.search(r"Number\s+\d+", txt):
                break

            lower = txt.lower()
            if "lw" in lower or "last" in lower:
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

        # 처음 몇 개는 로그로 확인
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
