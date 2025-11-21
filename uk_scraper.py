import os
import re
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup, Tag

# =========================
# 0. Supabase 설정 (REST API)
# =========================

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("환경변수 SUPABASE_URL / SUPABASE_SERVICE_KEY 를 설정하세요.")

BASE_REST_URL = SUPABASE_URL.rstrip("/") + "/rest/v1"

BASE_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}

# =========================
# 1. 공통 유틸 및 파싱 로직 (Selector 업데이트)
# =========================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# UK Official Charts의 기본 URL
BASE_CHART_URL = "https://www.officialcharts.com/"


def safe_int(value: Optional[str]) -> Optional[int]:
    """숫자처럼 보이면 int, 아니면 None."""
    if not value:
        return None
    try:
        # 'NEW' 또는 'RE ENTRY'와 같은 문자열은 None으로 처리
        return int(value.strip().replace(",", ""))
    except ValueError:
        return None


def fetch_soup(url: str) -> BeautifulSoup:
    """URL에서 HTML을 가져와 BeautifulSoup 객체를 반환합니다."""
    print(f"Fetching: {url}")
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def fetch_official_chart(chart_path: str) -> List[Dict]:
    """UK Official Chart 페이지에서 데이터를 스크래핑합니다."""
    url = BASE_CHART_URL + chart_path
    soup = fetch_soup(url)
    entries = []
    
    # 차트 발표일 추출 (예: 'The Official Singles Chart Update Top 100 on 21/11/2025')
    date_el = soup.find("div", class_="info").find("p")
    chart_date_str = None
    if date_el and date_el.text:
        match = re.search(r'on\s+(\d{2}/\d{2}/\d{4})', date_el.text)
        if match:
            # 일/월/년 형식을 YYYY-MM-DD로 변환
            chart_date_str = datetime.strptime(match.group(1), '%d/%m/%Y').strftime('%Y-%m-%d')
    
    if not chart_date_str:
        print("⚠️ 차트 날짜를 추출할 수 없습니다. 스크래핑을 중단합니다.")
        return []

    # 차트 항목 컨테이너 (이전에 사용된 .chart-item 대신 .chart-item-row 사용)
    chart_items = soup.select('.chart-item-row') 
    
    if not chart_items:
        # 대체 컨테이너 시도 (새로운 디자인에 대한 대비)
        chart_items = soup.select('div.chart-results-list ul li.chart-item')
        if not chart_items:
             print("⚠️ 차트 항목을 찾을 수 없습니다. 셀렉터가 변경되었을 수 있습니다.")
             return []


    for idx, item in enumerate(chart_items):
        try:
            # 순위 (Position)
            rank_el = item.select_one('.position .position__number')
            rank = safe_int(rank_el.text) if rank_el else None

            # 아티스트, 타이틀
            title_el = item.select_one('.title-artist .title')
            artist_el = item.select_one('.title-artist .artist')
            title = title_el.text.strip() if title_el else "Unknown Title"
            artist = artist_el.text.strip() if artist_el else "Unknown Artist"
            
            # --- ✨ LW, Peak, WKS 데이터 추출 로직 추가/수정 ✨ ---
            # UK 차트는 데이터가 별도의 칼럼에 명확히 구분되어 있음:
            
            # LW (Last Week) - .last-week
            lw_el = item.select_one('.last-week')
            lw = safe_int(lw_el.text) if lw_el else None
            
            # Peak (Peak Position) - .peak-pos
            peak_el = item.select_one('.peak-pos')
            peak = safe_int(peak_el.text) if peak_el else None
            
            # WKS (Weeks On Chart) - .woc
            wks_el = item.select_one('.woc')
            weeks = safe_int(wks_el.text) if wks_el else None
            # --- ✨ 추출 로직 종료 ✨ ---

            # UK 차트는 커버 이미지를 직접 추출하지 않음 (프론트엔드에서 커버 이미지 필드를 사용하지 않음)
            
            if rank is not None:
                entries.append(
                    {
                        "chart_date": chart_date_str,
                        "rank": rank,
                        "title": title,
                        "artist": artist,
                        "last_week_rank": lw,
                        "peak_rank": peak,
                        "weeks_on_chart": weeks,
                        # UK 차트는 cover_image_url이 필요 없으므로 None 처리
                        "cover_image_url": None, 
                    }
                )
        except Exception as e:
            print(f"⚠️ UK Chart 파싱 오류 (idx={idx}, Rank={rank}): {e}")
            continue

    print(f"UK Chart 스크래핑 완료. {len(entries)}개 항목 (날짜: {chart_date_str}).")
    return entries


# =========================
# 2. Supabase REST API 연동
# =========================

def replace_entries_for_date(table_name: str, entries: List[Dict]):
    """Supabase에서 해당 테이블의 데이터를 삭제하고 새로 insert합니다."""
    if not entries:
        print(f"[Supabase] {table_name}: 삽입할 항목이 없습니다. 건너뜁니다.")
        return

    # 1. 기존 데이터 delete (가장 최근 날짜의 데이터만 삭제)
    chart_date = entries[0]['chart_date']
    print(f"[Supabase] {table_name}: 기존 데이터 ({chart_date}) 삭제 시도...")
    
    # 'eq' 필터가 쿼리 파라미터로 추가됨: ?chart_date=2025-11-21
    delete_url = f"{BASE_REST_URL}/{table_name}?chart_date=eq.{chart_date}"
    r_del = requests.delete(delete_url, headers=BASE_HEADERS, timeout=20)
    if not r_del.ok:
        # 삭제 실패는 경고로 처리하고 계속 진행
        print(f"[Supabase] {table_name} 삭제 실패: {r_del.status_code} {r_del.text}")

    # 2) 새 데이터 insert
    insert_url = f"{BASE_REST_URL}/{table_name}"
    headers = {**BASE_HEADERS, "Prefer": "return=representation"}
    print(f"[Supabase] {table_name} {len(entries)}개 행 insert...")
    r_ins = requests.post(insert_url, headers=headers, json=entries, timeout=30)
    if not r_ins.ok:
        print(f"[ERROR] {table_name} insert 실패: {r_ins.status_code} {r_ins.text}")
        r_ins.raise_for_status()
    else:
        print(f"[OK] {table_name} insert 완료.")


# =========================
# 3. 실행 흐름
# =========================

def update_uk_singles_chart():
    print("\n=== UK Official Singles Chart 스크래핑 시작 ===")
    entries = fetch_official_chart("singles-chart/")
    replace_entries_for_date("uk_singles_entries", entries)
    print("=== UK Official Singles Chart 스크래핑 종료 ===")


def update_uk_albums_chart():
    print("\n=== UK Official Albums Chart 스크래핑 시작 ===")
    entries = fetch_official_chart("albums-chart/")
    replace_entries_for_date("uk_albums_entries", entries)
    print("=== UK Official Albums Chart 스크래핑 종료 ===")


def main():
    update_uk_singles_chart()
    update_uk_albums_chart()


if __name__ == "__main__":
    main()
