import os
import re
import json
import datetime as dt
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup, Tag

BILLBOARD_HOT_URL = "https://www.billboard.com/charts/hot-100/"
BILLBOARD_200_URL = "https://www.billboard.com/charts/billboard-200/"

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("환경변수 SUPABASE_URL / SUPABASE_SERVICE_KEY 를 설정하세요.")


# -------------------------------------------------
# 유틸 함수들
# -------------------------------------------------
def extract_chart_date(soup: BeautifulSoup) -> dt.date:
    """
    페이지 상단의 'Week of November 22, 2025' 같은 텍스트에서 날짜를 추출.
    """
    date_el = soup.find(
        lambda t: t.name in ("span", "h2", "p")
        and t.get_text(strip=True).startswith("Week of")
    )
    if not date_el:
        raise RuntimeError("차트 날짜(Week of ...) 텍스트를 찾을 수 없습니다.")

    text = date_el.get_text(strip=True)
    # 예: "Week of November 22, 2025"
    m = re.search(r"Week of\s+(.+)", text)
    if not m:
        raise RuntimeError(f"날짜 포맷 파싱 실패: {text}")

    date_str = m.group(1).strip()
    chart_date = dt.datetime.strptime(date_str, "%B %d, %Y").date()
    return chart_date


def extract_metric_number(item: Tag, label: str) -> Optional[int]:
    """
    한 곡(또는 앨범) 블럭에서 'LW', 'PEAK', 'WEEKS' 라벨을 기준으로 숫자를 추출.
    """
    label_tag = item.find(
        lambda tag: tag.name in ("span", "div")
        and tag.get_text(strip=True) == label
    )
    if not label_tag:
        return None

    value_tag = label_tag.find_next(
        lambda tag: tag.name in ("span", "div")
        and tag.get_text(strip=True).replace("-", "").isdigit()
    )
    if not value_tag:
        return None

    text = value_tag.get_text(strip=True)
    if not text.isdigit():
        return None

    return int(text)


def supabase_upsert(table: str, rows: List[Dict]) -> None:
    """
    Supabase REST API로 upsert.
    on_conflict = chart_date,rank
    """
    if not rows:
        print(f"{table} 업서트할 데이터가 없습니다.")
        return

    endpoint = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    params = {
        "on_conflict": "chart_date,rank"
    }

    resp = requests.post(
        endpoint,
        headers=headers,
        params=params,
        data=json.dumps(rows),
        timeout=30
    )

    if not resp.ok:
        raise RuntimeError(
            f"Supabase upsert 실패: {resp.status_code} {resp.text}"
        )

    print(f"{table} 업서트 성공: {len(rows)} rows")


# -------------------------------------------------
# Hot 100 스크래핑
# -------------------------------------------------
def fetch_hot_100() -> List[Dict]:
    print("Hot 100 차트 스크래핑 시작...")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    resp = requests.get(BILLBOARD_HOT_URL, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "html.parser")
    chart_date = extract_chart_date(soup)

    items = soup.select("li.o-chart-results-list__item")
    if not items:
        print("경고: Hot 100 항목을 찾지 못했습니다. 셀렉터를 확인하세요.")
        return []

    entries: List[Dict] = []

    for idx, item in enumerate(items):
        try:
            # 순위
            rank_el = item.select_one("span.c-label.a-font-primary-bold-l")
            if not rank_el:
                continue
            rank_text = rank_el.get_text(strip=True)
            m = re.search(r"\d+", rank_text)
            if not m:
                continue
            rank = int(m.group())

            # 제목
            title_el = item.select_one("h3#title-of-a-story")
            title = title_el.get_text(strip=True) if title_el else "Unknown Title"

            # 아티스트 (빌보드 구조가 자주 바뀌어서 널널하게 잡음)
            artist_el = item.find(
                lambda t: t.name == "span"
                and "c-label" in t.get("class", [])
                and "a-no-trucate" in t.get("class", [])
            ) or item.find(
                lambda t: t.name == "span"
                and "c-label" in t.get("class", [])
            )
            artist = artist_el.get_text(strip=True) if artist_el else "Unknown Artist"

            # 메트릭
            lw = extract_metric_number(item, "LW")
            peak = extract_metric_number(item, "PEAK")
            weeks = extract_metric_number(item, "WEEKS")

            entries.append(
                {
                    "chart_date": str(chart_date),
                    "rank": rank,
                    "title": title,
                    "artist": artist,
                    "last_week_rank": lw,
                    "peak_rank": peak,
                    "weeks_on_chart": weeks,
                }
            )
        except Exception as e:
            print(f"Hot 100 항목 파싱 중 오류 (index={idx}): {e}")
            continue

    print(f"Hot 100 차트 스크래핑 완료. {len(entries)}개 항목.")
    return entries


# -------------------------------------------------
# Billboard 200 스크래핑
# -------------------------------------------------
def fetch_billboard_200() -> List[Dict]:
    print("Billboard 200 차트 스크래핑 시작...")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    resp = requests.get(BILLBOARD_200_URL, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "html.parser")
    chart_date = extract_chart_date(soup)

    items = soup.select("li.o-chart-results-list__item")
    if not items:
        print("경고: Billboard 200 항목을 찾지 못했습니다. 셀렉터를 확인하세요.")
        return []

    entries: List[Dict] = []

    for idx, item in enumerate(items):
        try:
            # 순위
            rank_el = item.select_one("span.c-label.a-font-primary-bold-l")
            if not rank_el:
                continue
            rank_text = rank_el.get_text(strip=True)
            m = re.search(r"\d+", rank_text)
            if not m:
                continue
            rank = int(m.group())

            # 앨범 제목
            title_el = item.select_one("h3#title-of-a-story")
            title = title_el.get_text(strip=True) if title_el else "Unknown Album"

            # 아티스트
            artist_el = item.find(
                lambda t: t.name == "span"
                and "c-label" in t.get("class", [])
                and "a-no-trucate" in t.get("class", [])
            ) or item.find(
                lambda t: t.name == "span"
                and "c-label" in t.get("class", [])
            )
            artist = artist_el.get_text(strip=True) if artist_el else "Unknown Artist"

            # 메트릭
            lw = extract_metric_number(item, "LW")
            peak = extract_metric_number(item, "PEAK")
            weeks = extract_metric_number(item, "WEEKS")

            # 커버 이미지 (있으면)
            cover_url = None
            img_el = item.select_one("img")
            if img_el:
                cover_url = (
                    img_el.get("data-lazy-img")
                    or img_el.get("data-src")
                    or img_el.get("src")
                )

            entries.append(
                {
                    "chart_date": str(chart_date),
                    "rank": rank,
                    "title": title,
                    "artist": artist,
                    "last_week_rank": lw,
                    "peak_rank": peak,
                    "weeks_on_chart": weeks,
                    "cover_image_url": cover_url,
                }
            )
        except Exception as e:
            print(f"Billboard 200 항목 파싱 중 오류 (index={idx}): {e}")
            continue

    print(f"Billboard 200 차트 스크래핑 완료. {len(entries)}개 항목.")
    return entries


# -------------------------------------------------
# 메인
# -------------------------------------------------
def main():
    hot = fetch_hot_100()
    if hot:
        supabase_upsert("hot_100_entries", hot)

    albums = fetch_billboard_200()
    if albums:
        supabase_upsert("billboard_200_entries", albums)


if __name__ == "__main__":
    main()
