import os
import re
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client


# ===== 0. Supabase 설정 =====

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("환경변수 SUPABASE_URL / SUPABASE_SERVICE_KEY 를 설정하세요.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


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

    HTML 구조(class 이름)를 쓰지 않고,
    'Number 1', 'Number 2'… 'LW:', 'Peak:', 'Weeks:' 패턴만 이용해서 파싱한다.
    """
    # chart_date 추출
    chart_date = extract_chart_date(raw_text)

    # 'Number 1' 이후만 잘라서 파싱
    start_idx = raw_text.find("Number 1")
    if start_idx == -1:
        return []

    text = raw_text[start_idx:]

    # "Number <rank>" 기준으로 split
    # parts 구조: ["", "1", "<1번 내용>", "2", "<2번 내용>", ...]
    parts = re.split(r"Number\s+(\d+)", text)
    entries: List[Dict] = []

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
        m_lw = re.search(r"LW:\s*([0-9]+|New)", body, re.IGNORECASE)
        m_peak = re.search(r"Peak:\s*([0-9]+)", body, re.IGNORECASE)
        m_weeks = re.search(r"Weeks:\s*([0-9]+)", body, re.IGNORECASE)

        if m_lw:
            lw_raw = m_lw.group(1)
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

    반환: entries 리스트 (parse_officialcharts_text 결과)
    """
    url = f"https://www.officialcharts.com/charts/{chart_path}"
    print(f"[UK] 요청 URL: {url}")

    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    # BeautifulSoup으로 HTML을 파싱하고, 텍스트만 추출해서 분석
    soup = BeautifulSoup(resp.text, "html.parser")
    raw_text = soup.get_text("\n", strip=True)

    entries = parse_officialcharts_text(raw_text)
    print(f"[UK] {chart_path} 에서 {len(entries)}개 항목 파싱")
    return entries


def save_entries(table_name: str, entries: List[Dict]) -> None:
    """
    기존 데이터를 싹 지우고, 새 entries를 넣는다.
    """
    if not entries:
        print(f"[WARN] {table_name}: 저장할 데이터가 없습니다.")
        return

    print(f"[Supabase] {table_name} 기존 데이터 삭제...")
    supabase.table(table_name).delete().neq("id", 0).execute()

    # Supabase에 한 번에 insert (1000건 미만이라 문제 없음)
    print(f"[Supabase] {table_name}에 {len(entries)}개 행 insert...")
    res = supabase.table(table_name).insert(entries).execute()
    if res.get("error"):
        print(f"[ERROR] {table_name} insert 실패:", res["error"])
    else:
        print(f"[OK] {table_name} insert 완료.")


# ===== 2. 실제 스크래핑 & 저장 흐름 =====

def update_uk_singles_chart():
    print("=== UK Official Singles Chart 스크래핑 시작 ===")
    entries = fetch_official_chart("singles-chart/")
    save_entries("uk_singles_entries", entries)
    print("=== UK Official Singles Chart 스크래핑 종료 ===\n")


def update_uk_albums_chart():
    print("=== UK Official Albums Chart 스크래핑 시작 ===")
    entries = fetch_official_chart("albums-chart/")
    save_entries("uk_albums_entries", entries)
    print("=== UK Official Albums Chart 스크래핑 종료 ===\n")


if __name__ == "__main__":
    # 깃허브 액션이나 로컬에서 직접 실행할 때 둘 다 업데이트
    try:
        update_uk_singles_chart()
        update_uk_albums_chart()
        print("모든 UK 차트 업데이트 완료 ✅")
    except Exception as e:
        # 에러 로그 보기 쉽게
        import traceback

        print("[FATAL] UK 차트 스크래핑 중 오류 발생:")
        traceback.print_exc()
        raise
