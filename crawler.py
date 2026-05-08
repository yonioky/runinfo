"""
RunInfo 마라톤 크롤러 v2
========================
국내 마라톤 정보를 수집해 races.json 으로 저장합니다.
GitHub Actions에서 매주 자동 실행됩니다.

로컬 실행:
    pip install requests beautifulsoup4 lxml
    python crawler.py
"""

import json
import re
import time
import logging
from datetime import datetime
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "requests", "beautifulsoup4", "lxml", "-q"])
    import requests
    from bs4 import BeautifulSoup

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("runinfo")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}
REQUEST_DELAY = 0.5   # 초 (서버 부하 방지)
OUTPUT_FILE   = Path(__file__).parent / "races.json"

# ─────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────
def get_soup(url: str, encoding: str | None = None) -> BeautifulSoup | None:
    """URL을 가져와 BeautifulSoup 객체로 반환. 실패 시 None."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        if encoding:
            res.encoding = encoding
        return BeautifulSoup(res.text, "lxml")
    except requests.RequestException as e:
        log.warning(f"HTTP 오류 {url}: {e}")
        return None


def parse_date(text: str) -> tuple[str, str]:
    """
    다양한 날짜 형식을 파싱합니다.
      '2026-05-09(토)' → ('2026-05-09', '토')
      '2026년 5월 9일' → ('2026-05-09', '토')
    """
    m = re.search(r"(\d{4})[.\-/년\s]?\s*(\d{1,2})[.\-/월\s]?\s*(\d{1,2})", text)
    if not m:
        return ("", "")
    y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    date_str = f"{y}-{mo}-{d}"

    # 명시된 요일
    wd_m = re.search(r"[（(]([월화수목금토일])[)）]", text)
    if wd_m:
        return date_str, wd_m.group(1)

    # 날짜로 요일 계산
    try:
        KR_WD = ["월","화","수","목","금","토","일"]
        weekday = KR_WD[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    except ValueError:
        weekday = ""
    return date_str, weekday


def infer_status(reg_end: str, race_date: str) -> str:
    """접수종료일·대회일 기준으로 상태 추정"""
    today = datetime.today().date()
    try:
        end  = datetime.strptime(reg_end,   "%Y-%m-%d").date() if reg_end   else None
        race = datetime.strptime(race_date, "%Y-%m-%d").date() if race_date else None
    except ValueError:
        return "upcoming"

    if race and race < today:
        return "closed"          # 대회 자체가 지남
    if end:
        if end < today:
            return "closed"      # 접수 마감
        if (end - today).days <= 45:
            return "open"        # 접수 중
    return "upcoming"


REGION_PATTERNS = [
    (r"서울",                                    "서울"),
    (r"경기|인천|수원|성남|고양|부천|안산|화성|용인|평택|시흥|파주|의정부|남양주|김포", "경기"),
    (r"강원|춘천|강릉|원주|속초|동해|태백|삼척", "강원"),
    (r"충청|대전|청주|천안|충주|세종|아산|보령|공주|논산", "충청"),
    (r"전라|광주|전주|여수|순천|목포|익산|군산|나주",       "전라"),
    (r"경상|경북|경남|부산|대구|울산|포항|창원|구미|안동|경주|진주|거제", "영남"),
    (r"제주",                                    "제주"),
]

def guess_region(location: str) -> str:
    for pattern, name in REGION_PATTERNS:
        if re.search(pattern, location):
            return name
    return "기타"


DIST_PATTERNS = [
    (r"풀.{0,4}마라톤|42\.?195|full\s*marathon", "풀"),
    (r"하프.{0,4}마라톤|21\.?0975|half\s*marathon", "하프"),
    (r"10\s*km|10k\b",  "10km"),
    (r"5\s*km|5k\b",    "5km"),
    (r"100\s*km",       "100km"),
    (r"50\s*km",        "50km"),
    (r"울트라",          "울트라"),
]

def parse_distances(raw: str) -> list[str]:
    raw_lower = raw.lower()
    found = []
    for pattern, label in DIST_PATTERNS:
        if re.search(pattern, raw_lower) and label not in found:
            found.append(label)
    return found or ["기타"]


# ─────────────────────────────────────────
# 크롤러 1 — 마라톤온라인
#   http://www.marathon.pe.kr/schedule/
# ─────────────────────────────────────────
def crawl_marathon_pe_kr() -> list[dict]:
    log.info("📡 마라톤온라인 크롤링 시작")
    BASE = "http://www.marathon.pe.kr"
    races: list[dict] = []

    # 1페이지 ~ 3페이지 순회 (대회 수에 따라 조정)
    for page in range(1, 4):
        url = f"{BASE}/schedule/?page={page}"
        soup = get_soup(url, encoding="euc-kr")
        if not soup:
            break

        rows = soup.select("table tr")
        found_any = False

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4:
                continue
            try:
                date_raw = cols[0].get_text(" ", strip=True)
                name_el  = cols[1].find("a")
                if not name_el:
                    continue
                name     = name_el.get_text(strip=True)
                link     = BASE + name_el["href"] if name_el.get("href","").startswith("/") else name_el.get("href","#")
                location = cols[2].get_text(strip=True)
                dist_raw = cols[3].get_text(strip=True)

                date_str, weekday = parse_date(date_raw)
                if not date_str or not name:
                    continue

                race = {
                    "type":       "domestic",
                    "date":       date_str,
                    "weekday":    weekday,
                    "name":       name,
                    "location":   location,
                    "startTime":  "",
                    "distances":  parse_distances(dist_raw),
                    "region":     guess_region(location),
                    "status":     infer_status("", date_str),
                    "regStart":   "",
                    "regEnd":     "",
                    "organizer":  "",
                    "url":        link,
                    "source":     "marathon.pe.kr",
                    "crawledAt":  datetime.now().strftime("%Y-%m-%d"),
                }
                races.append(race)
                found_any = True
                log.info(f"  ✓ [{date_str}] {name}")
            except Exception as e:
                log.debug(f"  파싱 오류 (row): {e}")
            time.sleep(REQUEST_DELAY)

        if not found_any:
            break   # 빈 페이지면 종료

    log.info(f"  → 총 {len(races)}건 수집")
    return races


# ─────────────────────────────────────────
# 크롤러 2 — 달리자
#   https://www.dallija.com/board/raceSchedule
# ─────────────────────────────────────────
def crawl_dallija() -> list[dict]:
    log.info("📡 달리자 크롤링 시작")
    BASE = "https://www.dallija.com"
    races: list[dict] = []

    soup = get_soup(f"{BASE}/board/raceSchedule")
    if not soup:
        return races

    # 달리자 실제 DOM 구조에 맞는 selector (구조 변경 시 수정)
    items = (
        soup.select("div.schedule_list_area li")
        or soup.select("ul.list_area li")
        or soup.select("div.board_list tbody tr")
    )

    for item in items:
        try:
            name_el = (
                item.select_one("strong.tit")
                or item.select_one(".subject")
                or item.select_one("a")
            )
            date_el = item.select_one(".date") or item.select_one("span.d_day")
            loc_el  = item.select_one(".place") or item.select_one(".location")
            link_el = item.find("a", href=True)

            name     = name_el.get_text(strip=True) if name_el else ""
            date_raw = date_el.get_text(strip=True) if date_el else ""
            location = loc_el.get_text(strip=True)  if loc_el  else ""
            href     = link_el["href"] if link_el else "#"
            link     = (BASE + href) if href.startswith("/") else href

            if not name:
                continue

            date_str, weekday = parse_date(date_raw)
            race = {
                "type":       "domestic",
                "date":       date_str,
                "weekday":    weekday,
                "name":       name,
                "location":   location,
                "startTime":  "",
                "distances":  ["기타"],   # 상세 페이지 파싱 시 갱신 가능
                "region":     guess_region(location),
                "status":     infer_status("", date_str),
                "regStart":   "",
                "regEnd":     "",
                "organizer":  "",
                "url":        link,
                "source":     "dallija.com",
                "crawledAt":  datetime.now().strftime("%Y-%m-%d"),
            }
            races.append(race)
            log.info(f"  ✓ [{date_str}] {name}")
        except Exception as e:
            log.debug(f"  파싱 오류: {e}")
        time.sleep(REQUEST_DELAY)

    log.info(f"  → 총 {len(races)}건 수집")
    return races


# ─────────────────────────────────────────
# 기존 races.json 병합 (수동 입력 데이터 유지)
# ─────────────────────────────────────────
def load_existing() -> list[dict]:
    if OUTPUT_FILE.exists():
        try:
            return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """
    수동 입력 레코드(source 없음)는 항상 유지.
    크롤링 레코드는 (name, date) 기준으로 중복 제거 후 병합.
    """
    manual  = [r for r in existing if not r.get("source")]
    crawled_keys = {(r["name"], r["date"]) for r in fresh}

    # 기존 크롤링 데이터 중 새 데이터에 없는 것은 제거(갱신됐다고 간주)
    merged = manual[:]
    seen   = {(r["name"], r["date"]) for r in manual}

    for r in fresh:
        key = (r["name"], r["date"])
        if key not in seen:
            merged.append(r)
            seen.add(key)

    return sorted(merged, key=lambda x: (x.get("date",""), x.get("type","")))


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    log.info("=" * 50)
    log.info("   RunInfo 크롤러 v2 시작")
    log.info(f"   실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 50)

    fresh: list[dict] = []
    fresh.extend(crawl_marathon_pe_kr())
    fresh.extend(crawl_dallija())

    existing = load_existing()
    merged   = merge(existing, fresh)

    OUTPUT_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    log.info("─" * 50)
    log.info(f"✅ 완료: {len(merged)}건 → {OUTPUT_FILE}")
    log.info(f"   (신규 크롤링 {len(fresh)}건 / 기존 보존 {len(existing)}건)")


if __name__ == "__main__":
    main()
