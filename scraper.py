"""
Billboard Hot 100 / Billboard 200 Scraper
----------------------------------------

환경변수:
    SUPABASE_URL
    SUPABASE_SERVICE_KEY  (service_role 키)

Supabase 테이블 스키마 (schema.sql 참고):
    hot_100_entries(chart_date, rank, title, artist, last_week_rank, peak_rank, weeks_on_chart)
    billboard_200_entries(...., cover_image_url)
"""

import os
import re
import json
import datetime as dt
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup, Tag

# -------------------------------------------------
# 설정
# -------------------------------------------------
BILLBOARD_HOT_URL = "https://www.billboard.com/charts/hot-100/"
BILLBOARD_200_URL = "https://www.billboard.com/charts/billboard-200/"

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("환경변수 SUPABASE_URL / SUPABASE_SERVICE_KEY 를 설정하세요.")

# Billboard에서 402 등을 피하기 위해 최대한 브라우저 같은 UA 사용
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# -------------------------------------------------
# 공통 유틸
# -------------------------------------------------


def fetch_soup(url: str) -> BeautifulSoup:
    """요청 → BeautifulSoup 객체 반환"""
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
    resp.raise_for_status()
    # text / content 둘 다 가능하지만 text가 인코딩 처리에 유리
    return BeautifulSoup(resp.text, "html.parser")


def extract_chart_date(soup: BeautifulSoup) -> Optional[dt.date]:
    """
    페이지 상단 'Week of November 22, 2025' 같은 텍스트에서 날짜 추출.
    구조가 조금 달라질 수 있으니 여러 패턴을 시도.
    """
    candidates = []

    # 1) 'Week of'가 들어간 태그들
    for el in soup.find_all(
        lambda t: t.name in ("span", "h2", "p", "div")
        and "Week of" in t.get_text()
    ):
        candidates.append(el.get_text(strip=True))

    # 2) 혹시 'Week Of' 또는 다른 케이스
    if not candidates:
        for el in soup.find_all(
            lambda t: t.name in ("span", "h2", "p", "div")
            and "Week Of" in t.get_text()
        ):
            candidates.append(el.get_text(strip=True))

    for text in candidates:
        # 예: 'Week of November 22, 2025'
        m = re.search(r"Week of\s+(.+)", text, flags=re.IGNORECASE)
        if not m:
            continue
        date_str = m.group(1).strip()
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return dt.datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

    print("⚠️ chart_date를 찾지 못했습니다. (Week of ... 텍스트 미검출)")
    return None


def extract_metric_number(container: Tag, label: str) -> Optional[int]:
    """
    한 곡(또는 앨범) 블럭(container)에서 'LW', 'PEAK', 'WEEKS' 라벨을 기준으로 숫자를 추출.
    """
    if container is None:
        return None

    label_tag = container.find(
        lambda t: t.name in ("span", "div") and t.get_text(strip=True) == label
    )
    if not label_tag:
        return None

    value_tag = label_tag.find_next(
        lambda t: t.name in ("span", "div")
        and t.get_text(strip=True).replace("-", "").isdigit()
    )
    if not value_tag:
        return None

    text = value_tag.get_text(strip=True)
    if not text.isdigit():
        return None

    try:
        return int(text)
    except ValueError:
        return None


def supabase_upsert(table: str, rows: List[Dict]) -> None:
    """
    Supabase REST API로 upsert.
    on_conflict = chart_date,rank
    """
    if not rows:
        print(f"{table}: 업서트할 데이터가 없습니다.")
        return

    endpoint = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    params = {"on_conflict": "chart_date,rank"}

    resp = requests.post(
        endpoint,
        headers=headers,
        params=params,
        data=json.dumps(rows),
        timeout=60,
    )

    if not resp.ok:
        raise RuntimeError(f"Supabase upsert 실패 ({table}): {resp.status_code} {resp.text}")

    print(f"{table}: upsert 완료 ({len(rows)} rows).")


# -------------------------------------------------
# Hot 100 파서
# -------------------------------------------------


def parse_hot_100_items(soup: BeautifulSoup) -> List[Dict]:
    """
    Hot 100 페이지에서 각 곡 정보를 파싱.
    Billboard 구조가 바뀔 수 있어 여러 셀렉터를 시도한다.
    """
    chart_date = extract_chart_date(soup)
    if not chart_date:
        chart_date = dt.date.today()

    entries: List[Dict] = []

    # 1차: 최신 구조 추정 - ul.o-chart-results-list-row
    rows = soup.select("ul.o-chart-results-list-row")

    # 2차: 혹시 안 나오면 li 기반으로도 시도
    if not rows:
        rows = soup.select("li.o-chart-results-list__item")

    # 3차: 예전 구조 (chart-list__element 등)
    if not rows:
        rows = soup.select("li.chart-list__element")

    if not rows:
        print("⚠️ Hot 100: 차트 행을 찾지 못했습니다. 셀렉터를 수정해야 할 수 있습니다.")
        return entries

    print(f"Hot 100: 잠정 행 개수 = {len(rows)}")

    for idx, container in enumerate(rows):
        try:
            # 순위
            rank = None
            rank_el = container.find(
                "span",
                class_="c-label a-font-primary-bold-l u-font-size-32@tablet u-letter-spacing-0080@tablet"
            )
            if not rank_el:
                # fallback: 숫자만 있는 c-label
                rank_el = container.find(
                    lambda t: t.name == "span"
                    and "c-label" in t.get("class", [])
                    and re.search(r"\d+", t.get_text(strip=True))
                )
            if rank_el:
                m = re.search(r"\d+", rank_el.get_text(strip=True))
                if m:
                    rank = int(m.group())

            if rank is None:
                # 마지막 fallback: idx+1
                rank = idx + 1

            # 제목
            title_el = container.find("h3", id="title-of-a-story")
            if not title_el:
                title_el = container.find("h3")
            title = title_el.get_text(strip=True) if title_el else "Unknown Title"

            # 아티스트
            artist_el = container.find(
                lambda t: t.name == "span"
                and "c-label" in t.get("class", [])
                and ("a-no-trucate" in t.get("class", []) or "a-font-primary-s" in t.get("class", []))
            )
            if not artist_el:
                artist_el = container.find(
                    lambda t: t.name == "span" and "c-label" in t.get("class", [])
                )
            artist = artist_el.get_text(strip=True) if artist_el else "Unknown Artist"

            # 메트릭
            lw = extract_metric_number(container, "LW")
            peak = extract_metric_number(container, "PEAK")
            weeks = extract_metric_number(container, "WEEKS")

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
            print(f"⚠️ Hot 100 파싱 오류 (idx={idx}): {e}")
            continue

    return entries


def fetch_hot_100() -> List[Dict]:
    print("Hot 100 차트 스크래핑 시작...")
    soup = fetch_soup(BILLBOARD_HOT_URL)
    entries = parse_hot_100_items(soup)
    print(f"Hot 100 차트 스크래핑 완료. {len(entries)}개 항목.")
    return entries


# -------------------------------------------------
# Billboard 200 파서
# -------------------------------------------------


def parse_billboard_200_items(soup: BeautifulSoup) -> List[Dict]:
    chart_date = extract_chart_date(soup)
    if not chart_date:
        chart_date = dt.date.today()

    entries: List[Dict] = []

    rows = soup.select("ul.o-chart-results-list-row")
    if not rows:
        rows = soup.select("li.o-chart-results-list__item")
    if not rows:
        rows = soup.select("li.chart-list__element")

    if not rows:
        print("⚠️ Billboard 200: 차트 행을 찾지 못했습니다. 셀렉터를 수정해야 할 수 있습니다.")
        return entries

    print(f"Billboard 200: 잠정 행 개수 = {len(rows)}")

    for idx, container in enumerate(rows):
        try:
            # 순위
            rank = None
            rank_el = container.find(
                "span",
                class_="c-label a-font-primary-bold-l u-font-size-32@tablet u-letter-spacing-0080@tablet"
            )
            if not rank_el:
                rank_el = container.find(
                    lambda t: t.name == "span"
                    and "c-label" in t.get("class", [])
                    and re.search(r"\d+", t.get_text(strip=True))
                )
            if rank_el:
                m = re.search(r"\d+", rank_el.get_text(strip=True))
                if m:
                    rank = int(m.group())
            if rank is None:
                rank = idx + 1

            # 앨범 제목
            title_el = container.find("h3", id="title-of-a-story")
            if not title_el:
                title_el = container.find("h3")
            title = title_el.get_text(strip=True) if title_el else "Unknown Album"

            # 아티스트
            artist_el = container.find(
                lambda t: t.name == "span"
                and "c-label" in t.get("class", [])
                and ("a-no-trucate" in t.get("class", []) or "a-font-primary-s" in t.get("class", []))
            )
            if not artist_el:
                artist_el = container.find(
                    lambda t: t.name == "span" and "c-label" in t.get("class", [])
                )
            artist = artist_el.get_text(strip=True) if artist_el else "Unknown Artist"

            # 메트릭
            lw = extract_metric_number(container, "LW")
            peak = extract_metric_number(container, "PEAK")
            weeks = extract_metric_number(container, "WEEKS")

            # 커버 이미지
            cover_url = None
            img_el = container.find("img")
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
            print(f"⚠️ Billboard 200 파싱 오류 (idx={idx}): {e}")
            continue

    return entries


def fetch_billboard_200() -> List[Dict]:
    print("Billboard 200 차트 스크래핑 시작...")
    soup = fetch_soup(BILLBOARD_200_URL)
    entries = parse_billboard_200_items(soup)
    print(f"Billboard 200 차트 스크래핑 완료. {len(entries)}개 항목.")
    return entries


# -------------------------------------------------
# 메인
# -------------------------------------------------


def main():
    hot_entries = fetch_hot_100()
    if hot_entries:
        supabase_upsert("hot_100_entries", hot_entries)

    album_entries = fetch_billboard_200()
    if album_entries:
        supabase_upsert("billboard_200_entries", album_entries)


if __name__ == "__main__":
    main()
