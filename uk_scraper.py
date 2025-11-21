import os
import re
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup, Tag

# =========================
# 0. Supabase 설정 (변경 없음)
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


def safe_int(value: Optional[str]) -> Optional[int]:
    """숫자처럼 보이면 int, 아니면 None."""
    if not value:
        return None
    # 쉼표 제거 및 공백 제거
    value = value.replace(",", "").strip()
    if value.lower() in ("new", "re", "n/a"):
        return None
    
    # 숫자만 있는지 확인
    if not value.isdigit():
        # 혹시 '1.'이나 '2.' 같은 형식이 있으면 처리 (예: '1.')
        if value.endswith(".") and value[:-1].isdigit():
            return int(value[:-1])
        return None
    
    return int(value)


def extract_chart_date_from_text(raw_text: str) -> Optional[str]:
    """
    차트 날짜를 추출
    예시: '14 November 2025 - 20 November 2025'
    """
    m = re.search(r"(\d{1,2} \w+ \d{4})\s*-\s*(\d{1,2} \w+ \d{4})", raw_text)
    if not m:
        return None

    start_str = m.group(1)
    try:
        d = datetime.strptime(start_str, "%d %B %Y").date() 
        return d.isoformat()
    except ValueError:
        try:
            d = datetime.strptime(start_str, "%d %b %Y").date() 
            return d.isoformat()
        except ValueError:
            return None


def extract_metric_from_chart_item(container: Tag, metric_type: str) -> Optional[int]:
    """
    차트 항목(container)에서 'LW', 'Peak', 'Wks' 값을 추출.
    
    Official Charts의 새로운 구조:
    각 메트릭은 'metric-chart-stat' 클래스를 가진 div 안에 있으며,
    라벨(LW, Peak, Wks)은 'metric-chart-stat-title' 안에,
    값은 'metric-chart-stat-value' 안에 있습니다.
    """
    
    # 모든 메트릭 항목을 선택합니다
    metric_stats = container.select(".metric-chart-stat")
    
    for stat in metric_stats:
        # 라벨(title)을 찾고 metric_type과 비교
        title_el = stat.select_one(".metric-chart-stat-title")
        if title_el and title_el.get_text(strip=True).upper() == metric_type.upper():
            # 값(value)을 찾습니다
            value_el = stat.select_one(".metric-chart-stat-value")
            if value_el:
                raw_value = value_el.get_text(strip=True)
                return safe_int(raw_value)
    
    return None


def parse_officialcharts_soup(soup: BeautifulSoup) -> List[Dict]:
    """
    Official Charts 페이지 soup 객체를 받아 CSS Selector 기반으로 파싱.
    CSS Selector를 최신 구조에 맞게 업데이트했습니다.
    """
    # 1. 차트 날짜 추출 (기존의 텍스트 기반 방식 사용)
    full_text = soup.get_text("\n", strip=True)
    chart_date = extract_chart_date_from_text(full_text)
    if not chart_date:
        print("⚠️ chart_date를 찾지 못했습니다. 현재 날짜를 사용합니다.")
        chart_date = datetime.now().date().isoformat()

    entries: List[Dict] = []
    
    # 2. 차트 항목 컨테이너 선택 (업데이트된 Selector 사용: .chart-listing-item)
    # .chart-item 대신 .chart-listing-item을 사용합니다.
    chart_items = soup.select(".chart-listing-item")
    
    if not chart_items:
        print("⚠️ Official Charts: 차트 항목 (.chart-listing-item)을 찾지 못했습니다. Selector를 다시 확인하세요.")
        return entries
    
    print(f"[DEBUG] Official Charts: {len(chart_items)}개 항목 발견.")

    for idx, item in enumerate(chart_items):
        try:
            # 순위 (rank)
            # 순위는 .chart-listing-item-rank-text 안에 있습니다.
            rank_el = item.select_one(".chart-listing-item-rank-text")
            
            rank = safe_int(rank_el.get_text(strip=True)) if rank_el else idx + 1
            if rank is None:
                rank = idx + 1 

            # 제목 (title) 
            # 제목은 .chart-listing-item-title 안에 있습니다.
            title_el = item.select_one(".chart-listing-item-title")
            title = title_el.get_text(strip=True) if title_el else "Unknown Title"

            # 아티스트 (artist) 
            # 아티스트는 .chart-listing-item-artist 안에 있습니다.
            artist_el = item.select_one(".chart-listing-item-artist")
            artist = artist_el.get_text(strip=True) if artist_el else "Unknown Artist"

            # 메트릭 추출
            # 메트릭 정보는 메인 컨테이너에서 추출합니다.
            lw = extract_metric_from_chart_item(item, "LW")
            peak = extract_metric_from_chart_item(item, "PEAK")
            weeks = extract_metric_from_chart_item(item, "WKS")
            
            entries.append(
                {
                    "rank": rank,
                    "title": title,
                    "artist": artist,
                    "last_week_rank": lw,
                    "peak_rank": peak,
                    "weeks_on_chart": weeks,
                    "chart_date": chart_date,
                }
            )
        except Exception as e:
            # print(f"⚠️ UK Chart 파싱 오류 (idx={idx}, title='{title}'): {e}") # title 변수가 정의되지 않았을 수 있으므로 주석 처리
            print(f"⚠️ UK Chart 파싱 오류 (idx={idx}): {e}")
            continue

    print(f"[DEBUG] parsed entries 개수: {len(entries)}")
    return entries


def fetch_official_chart(chart_path: str) -> List[Dict]:
    """
    chart_path 예시:
      - 'singles-chart/'
      - 'albums-chart/'
    """
    url = f"https://www.officialcharts.com/charts/{chart_path}"
    print(f"=== [UK] 요청 URL: {url} ===")

    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    
    # CSS Selector 기반의 새로운 파싱 함수 호출
    entries = parse_officialcharts_soup(soup) 
    print(f"[UK] {chart_path} 에서 {len(entries)}개 항목 파싱 완료.")
    return entries


# =========================
# 2. Supabase REST 저장 (변경 없음)
# =========================

def replace_entries_for_date(table_name: str, entries: List[Dict]) -> None:
    """같은 chart_date 데이터 싹 지우고 새로 넣기."""
    if not entries:
        print(f"[WARN] {table_name}: 저장할 데이터가 없습니다.")
        return

    chart_date = entries[0]["chart_date"]
    if not chart_date:
        print(f"[WARN] {table_name}: chart_date 없음, 저장 스킵.")
        return

    # 1) 기존 해당 날짜 데이터 삭제
    delete_url = f"{BASE_REST_URL}/{table_name}?chart_date=eq.{chart_date}"
    print(f"[Supabase] {table_name} {chart_date} 데이터 삭제: {delete_url}")
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
# 3. 실행 흐름 (변경 없음)
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


if __name__ == "__main__":
    try:
        update_uk_singles_chart()
        update_uk_albums_chart()
        print("\n모든 UK 차트 업데이트 완료 ✅")
    except Exception:
        import traceback

        print("[FATAL] UK 차트 스크래핑 중 오류 발생:")
        traceback.print_exc()
        raise
