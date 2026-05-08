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


def get_html_and_api(url: str) -> tuple[str, list[dict]]:
    """
    Playwright로 페이지를 열고:
    1) 모든 fetch/XHR 응답을 가로채서 JSON API 응답 수집
    2) 최종 렌더링된 HTML 반환
    """
    api_responses = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # ── 모든 네트워크 응답 가로채기 ──
            def handle_response(response):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" not in ct:
                        return
                    # API URL 로그 출력
                    log.info(f"  🔗 API 감지: {response.url}")
                    data = response.json()
                    # 배열이거나 list 키를 가진 dict인 경우 수집
                    if isinstance(data, list) and len(data) > 0:
                        api_responses.append({"url": response.url, "data": data})
                    elif isinstance(data, dict):
                        for key in ("data", "list", "items", "races", "result", "results", "content"):
                            if isinstance(data.get(key), list) and len(data[key]) > 0:
                                api_responses.append({"url": response.url, "key": key, "data": data[key]})
                                break
                except Exception:
                    pass

            page.on("response", handle_response)
            page.goto(url, wait_until="networkidle", timeout=30000)
            time.sleep(2)  # 추가 로딩 대기
            html = page.content()
            browser.close()
            return html, api_responses
    except Exception as e:
        log.warning(f"Playwright 오류: {e}")
        return "", []


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


# ── 크롤러 1: 마라톤고 ────────────────────────
def crawl_marathongo() -> list[dict]:
    log.info("📡 [1/3] 마라톤고 크롤링...")
    url   = "https://marathongo.co.kr/raceSchedule/domestic"
    races = []

    html, api_responses = get_html_and_api(url)

    # ── 방법 A: API 응답에서 직접 파싱 ──────────
    if api_responses:
        log.info(f"  ✅ API 응답 {len(api_responses)}개 감지 → JSON 파싱 시도")
        for resp in api_responses:
            log.info(f"     URL: {resp['url']}")
            for item in resp["data"][:3]:
                log.info(f"     샘플 키: {list(item.keys()) if isinstance(item, dict) else type(item)}")
            races.extend(_parse_api_items(resp["data"], "marathongo.co.kr"))
        if races:
            log.info(f"  → {len(races)}건 (API)")
            return races

    # ── 방법 B: HTML 파싱 (API 실패 시 fallback) ─
    log.info("  ⚠️  API 미감지 → HTML 파싱 시도")
    if not html:
        log.warning("  → HTML도 없음, 스킵")
        return []

    # 디버그: 실제 HTML 구조 일부 출력
    soup = BeautifulSoup(html, "lxml")
    body_text = soup.get_text()[:500]
    log.info(f"  📄 페이지 텍스트 미리보기: {body_text[:200]}")

    # 가능한 모든 selector 시도
    for selector in [
        "li[class*='race']", "div[class*='race']",
        "li[class*='schedule']", "div[class*='schedule']",
        "li[class*='item']", "div[class*='item']",
        "tr[class*='race']", "tbody tr",
        "article", ".card",
    ]:
        items = soup.select(selector)
        if items:
            log.info(f"  🎯 selector '{selector}' → {len(items)}개 매칭")
            for item in items[:2]:
                log.info(f"     HTML: {str(item)[:200]}")
            break
    else:
        log.warning("  → 매칭된 selector 없음. Actions 로그의 API/HTML 미리보기를 확인하세요.")

    log.info(f"  → {len(races)}건")
    return races


def _parse_api_items(items: list, source: str) -> list[dict]:
    """JSON API 응답 아이템을 race dict로 변환"""
    races = []
    # 가능한 필드명 매핑 (사이트마다 다름)
    NAME_KEYS  = ["raceName","name","title","eventName","대회명","raceTitle"]
    DATE_KEYS  = ["raceDate","date","startDate","eventDate","대회일","raceDay"]
    LOC_KEYS   = ["location","place","venue","address","장소","racePlace"]
    DIST_KEYS  = ["distances","distance","category","종목","raceType","distList"]
    REG_S_KEYS = ["regStartDate","registrationStart","접수시작","regStart"]
    REG_E_KEYS = ["regEndDate","registrationEnd","접수마감","regEnd","regDeadline"]
    URL_KEYS   = ["url","link","detailUrl","raceUrl"]
    ORG_KEYS   = ["organizer","host","주최","organizerName"]

    def pick(d, keys):
        for k in keys:
            if k in d and d[k]: return str(d[k])
        return ""

    for item in items:
        if not isinstance(item, dict): continue
        try:
            name     = pick(item, NAME_KEYS)
            date_raw = pick(item, DATE_KEYS)
            location = pick(item, LOC_KEYS)
            dist_raw = pick(item, DIST_KEYS)
            reg_s    = pick(item, REG_S_KEYS)
            reg_e    = pick(item, REG_E_KEYS)
            url_val  = pick(item, URL_KEYS)
            org      = pick(item, ORG_KEYS)

            if not name or not date_raw: continue
            date_str, weekday = parse_date(date_raw)
            if not date_str: continue

            # distances가 리스트인 경우 처리
            dist_field = item.get("distances") or item.get("distList") or item.get("category")
            if isinstance(dist_field, list):
                distances = [str(d) for d in dist_field if d]
            else:
                distances = parse_distances(dist_raw or name)

            races.append({
                "type": "domestic", "date": date_str, "weekday": weekday,
                "name": name, "location": location, "startTime": "",
                "distances": distances,
                "region": guess_region(location),
                "status": infer_status(reg_e[:10] if reg_e else "", date_str),
                "regStart": reg_s[:10] if reg_s else "",
                "regEnd":   reg_e[:10] if reg_e else "",
                "organizer": org,
                "url": url_val or "#",
                "source": source,
                "crawledAt": datetime.now().strftime("%Y-%m-%d"),
            })
            log.info(f"  ✓ [{date_str}] {name}")
        except Exception as e:
            log.debug(f"  파싱 오류: {e}")
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


# ── 크롤러 3: 런벙 ───────────────────────────
def crawl_runbung() -> list[dict]:
    log.info("📡 [3/3] 런벙 크롤링...")
    url   = "https://www.runbung.app/ko/marathons"
    races = []

    html, api_responses = get_html_and_api(url)

    if api_responses:
        log.info(f"  ✅ API 응답 {len(api_responses)}개 감지")
        for resp in api_responses:
            log.info(f"     URL: {resp['url']}")
            races.extend(_parse_api_items(resp["data"], "runbung.app"))
        if races:
            log.info(f"  → {len(races)}건 (API)")
            return races

    log.info("  ⚠️  API 미감지 → HTML 파싱 시도")
    if not html: return []
    soup  = BeautifulSoup(html, "lxml")
    log.info(f"  📄 페이지 텍스트 미리보기: {soup.get_text()[:200]}")
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
