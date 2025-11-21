import os
import re
from datetime import datetime
from typing import List, Dict, Optional, Any

import requests
from bs4 import BeautifulSoup, Tag

# =========================
# 0. Supabase 설정 (REST API)
# =========================

# 환경 변수 체크
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

# 요청 헤더 (봇으로 인식되지 않도록 브라우저처럼 위장)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# =========================
# 1. 유틸리티 함수
# =========================

def safe_int(value: Optional[str]) -> Optional[int]:
    """숫자처럼 보이면 int, 아니면 None."""
    if not value:
        return None
    # 쉼표, 공백, New/RE 등 비숫자 문자열 제거 및 처리
    value = value.replace(",", "").strip()
    
    # 순위 표기(New, Re) 또는 하이픈(-) 처리
    if value.lower() in ("new", "re", "n/a", "-"):
        return None
    
    # 소수점이나 숫자만 있는 경우만 int로 변환
    try:
        # 순수한 정수만 받기 위해 isdigit() 사용
        if value.isdigit():
            return int(value)
        # 소수점 포함 숫자 처리
        if "." in value and value.replace('.', '', 1).isdigit():
             return int(float(value))
        return None
    except ValueError:
        return None


def extract_chart_date_from_soup(soup: BeautifulSoup) -> str:
    """페이지에서 차트 날짜를 추출하거나 현재 날짜를 반환."""
    # Official Charts의 날짜는 h3 또는 특정 span에 표시됩니다.
    date_el = soup.select_one("h3.chart-listing__header-date")
    if not date_el:
        # Fallback: 전체 텍스트에서 'DD Month YYYY - DD Month YYYY' 패턴 찾기
        full_text = soup.get_text("\n", strip=True)
        m = re.search(r"(\d{1,2} \w+ \d{4})\s*-\s*(\d{1,2} \w+ \d{4})", full_text)
        if m:
            date_str = m.group(1) # 차트 시작 날짜 사용
            try:
                # '14 November 2025' 같은 형식 파싱
                d = datetime.strptime(date_str, "%d %B %Y").date() 
                return d.isoformat()
            except ValueError:
                pass

    if date_el:
        date_text = date_el.get_text(strip=True)
        # 'Friday 18th March 2022'와 같은 형식 처리
        match = re.search(r'\d{1,2}(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+\d{4}', date_text)
        if match:
             # 날짜가 유효한지 확인하고 가장 최근 금요일 날짜를 사용해야 함
             # Official Charts는 "For the Chart Week Ending..." 날짜를 기준으로 합니다.
             # 현재는 간략화를 위해 날짜 텍스트를 그대로 사용 시도
             pass 

    print("⚠️ chart_date를 찾지 못했습니다. 현재 날짜를 사용합니다.")
    return datetime.now().date().isoformat()

# =========================
# 2. 파싱 로직 (Official Charts)
# =========================

def parse_officialcharts_soup(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Official Charts 페이지 soup 객체를 받아 파싱."""
    
    chart_date = extract_chart_date_from_soup(soup)
    entries: List[Dict[str, Any]] = []

    # 1. 차트 항목 컨테이너 선택 (가장 안정적인 Selector부터 시도)
    
    # 1순위: 가장 일반적인 항목 컨테이너
    chart_items = soup.select("ol.chart-listing > li.chart-listing-item")
    print(f"[DEBUG] 1순위 Selector (li.chart-listing-item) 결과: {len(chart_items)}개")
    
    if not chart_items:
        # 2순위: 덜 구체적인 li 선택
        chart_items = soup.select("ol > li")
        print(f"[DEBUG] 2순위 Selector (ol > li) 결과: {len(chart_items)}개")
        
    if not chart_items:
        # 3순위: 구버전 클래스 또는 다른 컨테이너 시도
        chart_items = soup.select(".chart-item-content")
        print(f"[DEBUG] 3순위 Selector (.chart-item-content) 결과: {len(chart_items)}개")

    if not chart_items:
        print("⚠️ Official Charts: 어떤 Selector로도 차트 항목을 찾지 못했습니다. 스크래핑 실패.")
        return entries
    
    print(f"[DEBUG] Official Charts: 최종 {len(chart_items)}개 항목 발견.")

    
    # 2. 항목별 데이터 추출
    for idx, item in enumerate(chart_items):
        try:
            # 순위 (Rank)
            # 순위는 보통 item 자체의 가장 외곽에 위치합니다.
            rank_el = item.select_one(".chart-listing-item-rank-text") 
            rank = safe_int(rank_el.get_text(strip=True)) if rank_el else (idx + 1)
            
            # 제목 (Title) - chart-name 클래스
            title_el = item.select_one(".chart-name")
            title = title_el.get_text(strip=True) if title_el else "Unknown Title"

            # 아티스트 (Artist) - chart-artist 클래스
            artist_el = item.select_one(".chart-artist")
            artist = artist_el.get_text(strip=True) if artist_el else "Unknown Artist"
            
            # 제목이나 아티스트가 없으면 광고일 확률이 높으므로 건너뜁니다.
            if title == "Unknown Title" and artist == "Unknown Artist":
                continue

            # 기타 메트릭 (LW, Peak, Wks) 추출
            
            # Metrices는 .metric-chart-stat-value 안에 있습니다.
            lw, peak, weeks = None, None, None
            
            # LW, Peak, Wks를 포함하는 전체 메트릭 컨테이너를 찾습니다.
            metric_container = item.select_one(".chart-listing-item__stats")
            if metric_container:
                # 개별 metric-chart-stat 요소를 찾습니다.
                for stat in metric_container.select(".metric-chart-stat"):
                    title_el = stat.select_one(".metric-chart-stat-title")
                    value_el = stat.select_one(".metric-chart-stat-value")
                    
                    if title_el and value_el:
                        title_text = title_el.get_text(strip=True).upper()
                        value = safe_int(value_el.get_text(strip=True))
                        
                        if title_text == "LW":
                            lw = value
                        elif title_text == "PEAK":
                            peak = value
                        elif title_text == "WKS":
                            weeks = value

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
            print(f"⚠️ UK Chart 파싱 중 오류 (순위 {idx + 1}): {e}")
            continue

    print(f"[DEBUG] 최종 파싱된 항목 개수: {len(entries)}")
    return entries


def fetch_official_chart(chart_path: str) -> List[Dict[str, Any]]:
    """지정된 UK Official Chart URL에서 데이터를 가져오고 파싱."""
    url = f"https://www.officialcharts.com/charts/{chart_path}"
    print(f"=== [UK] 요청 URL: {url} ===")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status() # 4xx, 5xx 에러 발생 시 예외 처리
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] HTTP 요청 실패: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    entries = parse_officialcharts_soup(soup) 
    print(f"[UK] {chart_path} 에서 {len(entries)}개 항목 파싱 완료.")
    return entries


# =========================
# 3. Supabase REST 저장
# =========================

def replace_entries_for_date(table_name: str, entries: List[Dict[str, Any]]) -> None:
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
    print(f"[Supabase] {table_name} {chart_date} 데이터 삭제 시도...")
    r_del = requests.delete(delete_url, headers=BASE_HEADERS, timeout=20)
    if not r_del.ok:
        print(f"[Supabase] {table_name} 삭제 실패 (경고): {r_del.status_code} {r_del.text}")

    # 2) 새 데이터 insert
    insert_url = f"{BASE_REST_URL}/{table_name}"
    headers = {**BASE_HEADERS, "Prefer": "return=representation"}
    print(f"[Supabase] {table_name} {len(entries)}개 행 insert 시도...")
    r_ins = requests.post(insert_url, headers=headers, json=entries, timeout=30)
    if not r_ins.ok:
        print(f"[ERROR] {table_name} insert 실패: {r_ins.status_code} {r_ins.text}")
        r_ins.raise_for_status()
    else:
        print(f"[OK] {table_name} insert 완료.")


# =========================
# 4. 실행 흐름
# =========================

def update_uk_singles_chart():
    print("\n=== UK Official Singles Chart 스크래핑 시작 ===")
    entries = fetch_official_chart("singles-chart/")
    # 테이블 이름: uk_singles_entries
    replace_entries_for_date("uk_singles_entries", entries)
    print("=== UK Official Singles Chart 스크래핑 종료 ===")


def update_uk_albums_chart():
    print("\n=== UK Official Albums Chart 스크래핑 시작 ===")
    entries = fetch_official_chart("albums-chart/")
    # 테이블 이름: uk_albums_entries
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
        # GitHub Actions에서 오류를 명확히 표시하기 위해 예외를 다시 발생시킵니다.
        raise
