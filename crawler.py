"""
RunInfo 마라톤 크롤러 v3
========================
3개 사이트에서 국내 마라톤 정보를 수집해 races.json 으로 저장합니다.
GitHub Actions에서 매주 자동 실행됩니다.

지원 사이트:
  1. 마라톤고    https://marathongo.co.kr/raceSchedule/domestic
  2. 마라톤온라인 http://www.marathon.pe.kr/index_calendar.html
  3. 런벙        https://www.runbung.app/ko/marathons

로컬 실행:
    pip install requests beautifulsoup4 lxml playwright
    playwright install chromium
    python crawler.py
"""

import json, re, time, logging
from datetime import datetime
from pathlib import Path

# ── 의존성 자동 설치 ──────────────────────────
def _install(*pkgs):
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", *pkgs, "-q"])

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    _install("requests", "beautifulsoup4", "lxml")
    import requests
    from bs4 import BeautifulSoup

# ── 설정 ─────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("runinfo")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "ko-KR,ko;q=0.9",
}
DELAY       = 0.6
OUTPUT_FILE = Path(__file__).parent / "races.json"

# ── 유틸 ─────────────────────────────────────
def get_soup(url: str, encoding: str | None = None) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        if encoding: r.encoding = encoding
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        log.warning(f"HTTP 오류 {url}: {e}")
        return None


def get_html_playwright(url: str) -> str | None:
    """JavaScript 렌더링이 필요한 SPA 사이트용"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            # 리스트가 로드될 때까지 최대 5초 대기
            try:
                page.wait_for_selector("li, tr, .race, .event, .card", timeout=5000)
            except Exception:
                pass
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        log.warning(f"Playwright 오류: {e}")
        return None


def parse_date(text: str) -> tuple[str, str]:
    m = re.search(r"(\d{4})[.\-/년\s]?\s*(\d{1,2})[.\-/월\s]?\s*(\d{1,2})", text)
    if not m: return ("", "")
    y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    date_str = f"{y}-{mo}-{d}"
    wd_m = re.search(r"[（(]([월화수목금토일])[)）]", text)
    if wd_m: return date_str, wd_m.group(1)
    try:
        KR = ["월","화","수","목","금","토","일"]
        wd = KR[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    except ValueError:
        wd = ""
    return date_str, wd


def infer_status(reg_end: str, race_date: str) -> str:
    today = datetime.today().date()
    def p(s):
        try: return datetime.strptime(s, "%Y-%m-%d").date()
        except: return None
    rd = p(race_date); re_ = p(reg_end)
    if rd and rd < today: return "closed"
    if re_:
        if re_ < today: return "closed"
        if (re_ - today).days <= 45: return "open"
    return "upcoming"


REGION_MAP = [
    (r"서울", "서울"),
    (r"경기|인천|수원|성남|고양|부천|안산|화성|용인|평택|시흥|파주|의정부|남양주|김포|안양|광명|과천|하남", "경기"),
    (r"강원|춘천|강릉|원주|속초|동해|태백|삼척|홍천|횡성|영월|평창|정선|철원|화천|양구|인제|고성|양양", "강원"),
    (r"충청|대전|청주|천안|충주|세종|아산|보령|공주|논산|계룡|당진|서산|홍성|예산|태안|청양|부여|서천|금산|옥천|영동|증평|진천|괴산|음성|단양", "충청"),
    (r"전라|광주|전주|여수|순천|목포|익산|군산|나주|광양|담양|곡성|구례|고흥|보성|화순|장흥|강진|해남|영암|무안|함평|영광|장성|완도|진도|신안|남원|정읍|고창|부안|임실|순창|무주|진안|장수", "전라"),
    (r"경상|경북|경남|부산|대구|울산|포항|창원|구미|안동|경주|진주|거제|통영|사천|김해|밀양|거창|합천|의령|함안|창녕|고성|남해|하동|산청|함양|고령|성주|칠곡|예천|영주|영양|청송|울진|울릉|봉화|의성|군위|영천|청도|경산|달성|문경|상주", "영남"),
    (r"제주", "제주"),
]

def guess_region(loc: str) -> str:
    for pattern, name in REGION_MAP:
        if re.search(pattern, loc): return name
    return "기타"


DIST_MAP = [
    (r"풀.{0,4}마라톤|42\.?195|full\s*marathon", "풀"),
    (r"하프.{0,4}마라톤|21\.?0975|half\s*marathon", "하프"),
    (r"10\s*km|10k\b", "10km"),
    (r"5\s*km|5k\b", "5km"),
    (r"100\s*km", "100km"),
    (r"50\s*km", "50km"),
    (r"울트라", "울트라"),
]

def parse_distances(raw: str) -> list[str]:
    found = []
    for pat, label in DIST_MAP:
        if re.search(pat, raw.lower()) and label not in found:
            found.append(label)
    return found or ["기타"]


# ── 크롤러 1: 마라톤고 (SPA → Playwright) ────
def crawl_marathongo() -> list[dict]:
    log.info("📡 [1/3] 마라톤고 크롤링...")
    url = "https://marathongo.co.kr/raceSchedule/domestic"
    html = get_html_playwright(url)
    if not html:
        log.warning("  → Playwright 실패, requests 재시도")
        soup = get_soup(url)
        html = str(soup) if soup else ""

    if not html: return []
    soup = BeautifulSoup(html, "lxml")
    races = []

    # 마라톤고 DOM 구조: 카드형 리스트
    items = (soup.select("div.race-item, li.race-item, div.schedule-item") or
             soup.select("ul.list li") or
             soup.select("table tbody tr"))

    for item in items:
        try:
            name_el = (item.select_one(".race-name, .title, h3, h4, strong, td:nth-child(2) a") or
                       item.find("a"))
            date_el = item.select_one(".race-date, .date, time, td:first-child")
            loc_el  = item.select_one(".location, .place, .venue, td:nth-child(3)")
            dist_el = item.select_one(".distance, .distances, td:nth-child(4)")

            name     = name_el.get_text(strip=True) if name_el else ""
            date_raw = date_el.get_text(strip=True) if date_el else ""
            location = loc_el.get_text(strip=True)  if loc_el  else ""
            dist_raw = dist_el.get_text(strip=True)  if dist_el else ""
            link_el  = item.find("a", href=True)
            href     = link_el["href"] if link_el else "#"
            url_full = ("https://marathongo.co.kr" + href) if href.startswith("/") else href

            if not name or len(name) < 2: continue
            date_str, weekday = parse_date(date_raw)
            if not date_str: continue

            races.append({
                "type": "domestic", "date": date_str, "weekday": weekday,
                "name": name, "location": location, "startTime": "",
                "distances": parse_distances(dist_raw or name),
                "region": guess_region(location),
                "status": infer_status("", date_str),
                "regStart": "", "regEnd": "", "organizer": "",
                "url": url_full, "source": "marathongo.co.kr",
                "crawledAt": datetime.now().strftime("%Y-%m-%d"),
            })
            log.info(f"  ✓ [{date_str}] {name}")
        except Exception as e:
            log.debug(f"  파싱 오류: {e}")
        time.sleep(DELAY)

    log.info(f"  → {len(races)}건")
    return races


# ── 크롤러 2: 마라톤온라인 캘린더 ─────────────
def crawl_marathon_pe_kr() -> list[dict]:
    log.info("📡 [2/3] 마라톤온라인 크롤링...")
    BASE = "http://www.marathon.pe.kr"
    races = []

    for page in range(1, 5):
        url = f"{BASE}/index_calendar.html?page={page}"
        soup = get_soup(url, encoding="euc-kr")
        if not soup: break

        rows = soup.select("table tr, ul.race-list li")
        found = False
        for row in rows:
            cols = row.find_all(["td", "li"])
            if len(cols) < 2: continue
            try:
                name_el = row.find("a")
                if not name_el: continue
                name    = name_el.get_text(strip=True)
                href    = name_el.get("href", "#")
                link    = (BASE + href) if href.startswith("/") else href

                date_raw = cols[0].get_text(strip=True)
                location = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                dist_raw = cols[3].get_text(strip=True) if len(cols) > 3 else ""

                date_str, weekday = parse_date(date_raw)
                if not date_str or not name: continue

                races.append({
                    "type": "domestic", "date": date_str, "weekday": weekday,
                    "name": name, "location": location, "startTime": "",
                    "distances": parse_distances(dist_raw or name),
                    "region": guess_region(location),
                    "status": infer_status("", date_str),
                    "regStart": "", "regEnd": "", "organizer": "",
                    "url": link, "source": "marathon.pe.kr",
                    "crawledAt": datetime.now().strftime("%Y-%m-%d"),
                })
                log.info(f"  ✓ [{date_str}] {name}")
                found = True
            except Exception as e:
                log.debug(f"  파싱 오류: {e}")
            time.sleep(DELAY)

        if not found: break

    log.info(f"  → {len(races)}건")
    return races


# ── 크롤러 3: 런벙 (SPA → Playwright) ────────
def crawl_runbung() -> list[dict]:
    log.info("📡 [3/3] 런벙 크롤링...")
    url  = "https://www.runbung.app/ko/marathons"
    html = get_html_playwright(url)
    if not html:
        soup = get_soup(url)
        html = str(soup) if soup else ""
    if not html: return []

    soup  = BeautifulSoup(html, "lxml")
    races = []

    items = (soup.select("article, div.marathon-card, li.marathon-item") or
             soup.select("div[class*='card'], div[class*='item'], div[class*='race']"))

    for item in items:
        try:
            name_el = (item.select_one("h2, h3, h4, [class*='title'], [class*='name']") or
                       item.find("a"))
            date_el = item.select_one("time, [class*='date'], [class*='Date']")
            loc_el  = item.select_one("[class*='location'], [class*='place'], [class*='venue']")
            link_el = item.find("a", href=True)

            name     = name_el.get_text(strip=True) if name_el else ""
            date_raw = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
            location = loc_el.get_text(strip=True) if loc_el else ""
            href     = link_el["href"] if link_el else "#"
            url_full = ("https://www.runbung.app" + href) if href.startswith("/") else href

            if not name or len(name) < 2: continue
            date_str, weekday = parse_date(date_raw)
            if not date_str: continue

            races.append({
                "type": "domestic", "date": date_str, "weekday": weekday,
                "name": name, "location": location, "startTime": "",
                "distances": parse_distances(name),
                "region": guess_region(location),
                "status": infer_status("", date_str),
                "regStart": "", "regEnd": "", "organizer": "",
                "url": url_full, "source": "runbung.app",
                "crawledAt": datetime.now().strftime("%Y-%m-%d"),
            })
            log.info(f"  ✓ [{date_str}] {name}")
        except Exception as e:
            log.debug(f"  파싱 오류: {e}")
        time.sleep(DELAY)

    log.info(f"  → {len(races)}건")
    return races


# ── 병합 (수동 데이터 보존) ───────────────────
def load_existing() -> list[dict]:
    if OUTPUT_FILE.exists():
        try: return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        except: pass
    return []


def merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    manual = [r for r in existing if not r.get("source")]
    seen   = {(r["name"], r["date"]) for r in manual}
    merged = manual[:]
    for r in fresh:
        key = (r["name"], r["date"])
        if key not in seen:
            merged.append(r)
            seen.add(key)
    return sorted(merged, key=lambda x: (x.get("date",""), x.get("type","")))


# ── MAIN ─────────────────────────────────────
def main():
    log.info("=" * 55)
    log.info("   RunInfo 크롤러 v3")
    log.info(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 55)

    fresh = []
    fresh.extend(crawl_marathongo())
    fresh.extend(crawl_marathon_pe_kr())
    fresh.extend(crawl_runbung())

    existing = load_existing()
    merged   = merge(existing, fresh)

    OUTPUT_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info("─" * 55)
    log.info(f"✅ 완료: 총 {len(merged)}건 → {OUTPUT_FILE.name}")
    log.info(f"   신규 크롤링 {len(fresh)}건 / 기존 보존 {len(existing)}건")


if __name__ == "__main__":
    main()
