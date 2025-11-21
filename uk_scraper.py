import os
import re
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

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
# 1. 공통 유틸
# =========================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


def safe_int(value: Optional[str]) -> Optional[int]:
    """숫자처럼 보이면 int, 아니면 None."""
    if not value:
        return None
    value = value.strip()
    if not value.isdigit():
        return None
    return int(value)


def extract_chart_date(raw_text: str) -> Optional[str]:
    """
    예시: '14 November 2025 - 20 November 2025'
    앞쪽 날짜를 chart_date 로 사용.
    """
    m = re.search(r"(\d{1,2} \w+ \d{4})\s*-\s*(\d{1,2} \w+ \d{4})", raw_text)
    if not m:
        return None

    start_str = m.group(1)
    try:
        d = datetime.strptime(start_str, "%d %B %Y").date()
        return d.isoformat()
    except ValueError:
        return None


def parse_officialcharts_text(raw_text: str) -> List[Dict]:
    """
    Official Charts 페이지 전체 텍스트(raw_text)를 받아서
    rank / title / artist / LW / Peak / Weeks / chart_date 리스트로 변환.

    👉 "Number 1" 같은 패턴에 의존하지 않고
       "LW:", "Peak:", "Weeks:" 라인을 기준으로 파싱한다.
    """
    chart_date = extract_chart_date(raw_text)

    # 특수 공백(NBSP) → 일반 공백으로 정규화
    text = raw_text.replace("\xa0", " ")

    # 줄 단위로 나누고, 공백 줄 제거
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    entries: List[Dict] = []
    rank_counter = 0
    n = len(lines)
    i = 0

    while i < n:
        line = lines[i]

        # 1) "LW:" 가 들어간 줄을 곡 블록의 기준으로 사용
        if "LW:" not in line:
            i += 1
            continue

        rank_counter += 1  # 1, 2, 3, ... 순서대로 랭크 부여

        # --- 제목 / 아티스트: LW: 라인 바로 위 두 줄 ---
        j = i - 1
        artist = ""
        title = ""

        if j >= 0:
            artist = lines[j].strip()
            j -= 1
            if j >= 0:
                title = lines[j].strip()

        # --- LW 값 파싱 ---
        # 예: "1. LW: 2," 또는 "1. LW: New"
        m_lw = re.search(r"LW\s*:\s*([0-9]+|New|RE)", line, re.IGNORECASE)
        if m_lw:
            lw_raw = m_lw.group(1).strip()
            # "New", "RE" 같은 텍스트는 None 처리
            last_week_rank = safe_int(lw_raw)
        else:
            last_week_rank = None

        peak_rank = None
        weeks_on_chart = None

        # 2) 아래쪽 줄들에서 Peak / Weeks 값 찾기
        k = i + 1
        while k < n and "LW:" not in lines[k]:
            if "Peak:" in lines[k]:
                m_peak = re.search(r"Peak\s*:\s*([0-9]+)", lines[k], re.IGNORECASE)
                if m_peak:
                    peak_rank = safe_int(m_peak.group(1))

            if "Weeks:" in lines[k]:
                m_weeks = re.search(r"Weeks\s*:\s*([0-9]+)", lines[k], re.IGNORECASE)
                if m_weeks:
                    weeks_on_chart = safe_int(m_weeks.group(1))

            # 다음 곡 블록(LW:) 을 만나기 전까지는 같은 곡의 정보라고 본다.
            k += 1

        entries.append(
            {
                "rank": rank_counter,
                "title": title,
                "artist": artist,
                "last_week_rank": last_week_rank,
                "peak_rank": peak_rank,
                "weeks_on_chart": weeks_on_chart,
                "chart_date": chart_date,
            }
        )

        # 다음 탐색 시작 위치 갱신
        i = k

    print(f"[DEBUG] parsed entries 개수: {len(entries)}")
    return entries


def fetch_official_chart(chart_path: str) -> List[Dict]:
    """
    chart_path 예시:
      - 'singles-chart/'
      - 'albums-chart/'
    """
    url = f"https://www.officialcharts.com/charts/{chart_path}"
    print(f"[UK] 요청 URL: {url}")

    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    raw_text = soup.get_text("\n", strip=True)

    entries = parse_officialcharts_text(raw_text)
    print(f"[UK] {chart_path} 에서 {len(entries)}개 항목 파싱")
    return entries


# =========================
# 2. Supabase REST 저장
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
    print("=== UK Official Singles Chart 스크래핑 시작 ===")
    entries = fetch_official_chart("singles-chart/")
    replace_entries_for_date("uk_singles_entries", entries)
    print("=== UK Official Singles Chart 스크래핑 종료 ===\n")


def update_uk_albums_chart():
    print("=== UK Official Albums Chart 스크래핑 시작 ===")
    entries = fetch_official_chart("albums-chart/")
    replace_entries_for_date("uk_albums_entries", entries)
    print("=== UK Official Albums Chart 스크래핑 종료 ===\n")


if __name__ == "__main__":
    try:
        update_uk_singles_chart()
        update_uk_albums_chart()
        print("모든 UK 차트 업데이트 완료 ✅")
    except Exception:
        import traceback

        print("[FATAL] UK 차트 스크래핑 중 오류 발생:")
        traceback.print_exc()
        raise
