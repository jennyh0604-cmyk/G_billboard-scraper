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


def safe_int(value: Optional[str]) -> Optional[int]:
    """숫자처럼 보이면 int, 아니면 None."""
    if not value:
        return None
    # 쉼표, 공백, New/RE 등 비숫자 문자열 제거 및 처리
    value = value.replace(",", "").strip()
    if value.lower() in ("new", "re", "n/a", "-"):
        return None
    
    # 숫자만 있는지 확인
    if not value.isdigit():
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
        # Official Charts는 시작일 기준으로 날짜가 생성됨
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
    """
    
    # 모든 메트릭 항목을 선택합니다
    # Official Charts에서 LW, Peak, Wks를 표시하는 일반적인 클래스입니다.
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
    """
    # 1. 차트 날짜 추출
    full_text = soup.get_text("\n", strip=True)
    chart_date = extract_chart_date_from_text(full_text)
    if not chart_date:
        print("⚠️ chart_date를 찾지 못했습니다. 현재 날짜를 사용합니다.")
        chart_date = datetime.now().date().isoformat()

    entries: List[Dict] = []
    
    # 2. 차트 항목 컨테이너 선택 (사용자 제공 클래스의 가장 고유한 부분 사용)
    # chart-item-content가 하나의 곡 정보를 담는 가장 바깥쪽 컨테이너라고 가정합니다.
    chart_items = soup.select(".chart-item-content")
    
    if not chart_items:
        print("⚠️ Official Charts: 차트 항목 (.chart-item-content)을 찾지 못했습니다. Selector를 다시 확인하세요.")
        return entries
    
    print(f"[DEBUG] Official Charts: {len(chart_items)}개 항목 발견.")

    # 순위 추출을 위해, 각 항목의 부모 요소를 포함하는 모든 요소(주로 li)를 찾습니다.
    # Official Charts의 순위는 .chart-item-content 외부에 있는 경우가 많습니다.
    all_parent_items = soup.select(".chart-listing-item")
    
    for idx, item in enumerate(chart_items):
        rank = idx + 1 # 기본값 설정 (Fallback)
        title = "Unknown Title"
        artist = "Unknown Artist"
        
        try:
            # 순위 (rank) 추출
            
            # 1. .chart-item-content의 가장 가까운 부모 요소를 찾습니다.
            parent_item = item.find_parent()
            
            if parent_item:
                # 2. 부모 요소 안에서 순위 텍스트를 포함하는 요소(.chart-listing-item-rank-text)를 찾습니다.
                # 이 클래스는 순위를 포함하는 요소의 고유 클래스 중 하나로 추정됩니다.
                rank_el = parent_item.select_one(".chart-listing-item-rank-text")
                
                if rank_el:
                    parsed_rank = safe_int(rank_el.get_text(strip=True))
                    rank = parsed_rank if parsed_rank is not None else idx + 1
                else:
                    # 랭크 클래스가 없으면, 리스트의 인덱스(idx + 1)를 순위로 사용합니다.
                    print(f"[WARN] Rank Selector (.chart-listing-item-rank-text) 실패. 인덱스 {idx+1} 사용.")


            # 제목 (title) - 사용자 제공 클래스 사용
            # .chart-name 요소에서 제목을 추출합니다.
            title_el = item.select_one(".chart-name")
            if title_el:
                title = title_el.get_text(strip=True)
            else:
                 print(f"[WARN] Title Selector (.chart-name) 실패.")

            # 아티스트 (artist) - 사용자 제공 클래스 사용
            # .chart-artist 요소에서 아티스트를 추출합니다.
            artist_el = item.select_one(".chart-artist")
            if artist_el:
                artist = artist_el.get_text(strip=True)
            else:
                print(f"[WARN] Artist Selector (.chart-artist) 실패.")


            # 메트릭 추출 (LW, Peak, Wks) - item (chart-item-content) 내부에서 찾습니다.
            lw = extract_metric_from_chart_item(item, "LW")
            peak = extract_metric_from_chart_item(item, "PEAK")
            weeks = extract_metric_from_chart_item(item, "WKS")
            
            # 제목 또는 아티스트가 없는 항목은 광고나 비정상적인 요소일 수 있으므로 건너뜁니다.
            if title == "Unknown Title" or artist == "Unknown Artist":
                 print(f"[SKIP] {idx+1}번 항목: 제목/아티스트를 찾을 수 없어 건너뜁니다.")
                 continue

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
