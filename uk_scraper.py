import os
import re
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup


# ===== 0. Supabase 설정 =====

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


# ===== 1. 공통 유틸 =====

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


def extract_chart_date(text: str) -> Optional[str]:
    """
    예시: '14 November 2025 - 20 November 2025'
    앞쪽 날짜(14 November 2025)를 chart_date 로 사용.
    """
    m = re.search(r"(\d{1,2} \w+ \d{4})\s*-\s*(\d{1,2} \w+ \d{4})", text)
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
    """
    chart_date = extract_chart_date(raw_text)

    # 👉 노브레이크 스페이스(\xa0)를 일반 공백으로 통일
    text = raw_text.replace("\xa0", " ")

    # "Number <순위>" 패턴 기준으로 쪼개기
    parts = re.split(r"Number\s+(\d+)", text)
    entries: List[Dict] = []

    # parts 구조: ["앞부분", "1", "<1번 내용>", "2", "<2번 내용>", ...]
    if len(parts) < 3:
        print("[DEBUG] 'Number <n>' 패턴을 찾지 못했습니다.")
        return []

    for i in range(1, len(parts), 2):
        rank_str = parts[i]
        body = parts[i + 1]

        rank = safe_int(rank_str)
        if rank is None:
            continue

        # 줄 단위로 나누고, 공백 제거
        lines = [ln.strip() for ln in body.splitlines()]
        lines = [ln for ln in lines if ln]  # 빈 줄 제거

        # "Image: ... cover art" 같은 잡음 라인은 제거
        while lines and (
            lines[0].startswith("Image:")
            or "cover art" in lines[0]
            or lines[0].startswith("view as")
            or lines[0].startswith("Official Singles Chart")
            or lines[0].startswith("Official Albums Chart")
        ):
            lines.pop(0)

        if len(lines) < 2:
            # 제목 + 아티스트 두 줄이 안 나오면 스킵
            continue

        title = lines[0]
        artist = lines[1]

        # LW / Peak / Weeks 값은 body 전체에서 정규식으로 찾기
        m_lw = re.search(r"LW:\s*([0-9]+|New|RE)", body, re.IGNORECASE)
        m_peak = re.search(r"Peak:\s*([0-9]+)", body, re.IGNORECASE)
        m_weeks = re.search(r"Weeks:\s*([0-9]+)", body, re.IGNORECASE)

        if m_lw:
            lw_raw = m_lw.group(1)
            # "New", "RE" 같은 건 None 처리
            last_week_rank = safe_int(lw_raw)
        else:
            last_week_rank = None

        peak_rank = safe_int(m_peak.group(1)) if m_peak else None
        weeks_on_chart = safe_int(m_weeks.group(1)) if m_weeks else None

        entries.append(
            {
                "rank": rank,
                "title": title,
                "artist": artist,
                "last_week_rank": last_week_rank,
                "peak_rank": peak_rank,
                "weeks_on_chart": weeks_on_chart,
                "chart_date": chart_date,
            }
        )

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


# ===== 2. Supabase REST 로 저장 =====

def replace_entries_for_date(table_name: str, entries: List[Dict]) -> None:
    """같은 chart_date 데이터 싹 지우고 새로 넣기."""
    if not entries:
        print(f"[WARN] {table_name}: 저장할 데이터가 없습니다.")
        return

    chart_date = entries[0]["chart_date"]
    if not chart_date:
        print(f"[WARN] {table_name}: chart_date 없음, 저장 스킵.")
        return

    # 1) 해당 날짜 데이터 삭제
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


# ===== 3. 실제 스크래핑 & 저장 흐름 =====

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


