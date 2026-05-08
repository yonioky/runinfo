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


# ── 크롤러 1: 마라톤고 (DOM 슬러그 추출 → 상세 fetch) ──────
def crawl_marathongo() -> list[dict]:
    log.info("📡 [1/3] 마라톤고 크롤링 (DOM 슬러그 방식)...")
    BASE     = "https://marathongo.co.kr"
    races    = []
    build_id = ""
    cached   = {}  # slug → 이미 인터셉트된 pageProps

    # ── Step 1: Playwright로 렌더링 + 스크롤 + 슬러그 수집 ──
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page()

            def on_response(response):
                try:
                    url = response.url
                    ct  = response.headers.get("content-type", "")
                    if "json" not in ct:
                        return
                    if "/raceDetail/domestic/" in url and "_next/data/" in url:
                        slug = url.split("/raceDetail/domestic/")[1].split(".json")[0].split("?")[0]
                        data = response.json()
                        pp   = data.get("pageProps", {})
                        cached[slug] = pp
                        log.info(f"  🔗 상세 캐시: {slug}")
                except Exception:
                    pass

            page.on("response", on_response)

            # 전체 목록 URL (raceEnd=전체 필터)
            page.goto(f"{BASE}/raceSchedule/domestic?raceEnd=%EC%A0%84%EC%B2%B4",
                      wait_until="networkidle", timeout=30000)

            # 스크롤 → 새 링크가 나타나지 않을 때까지 계속
            prev_count = 0
            for attempt in range(25):  # 최대 25회
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.5)
                cur_count = page.eval_on_selector_all(
                    'a[href*="/raceDetail/domestic/"]',
                    'els => els.length'
                )
                log.info(f"  🔄 스크롤 {attempt+1}: 링크 {cur_count}개")
                if cur_count == prev_count:
                    log.info("  ✅ 더 이상 새 링크 없음 → 스크롤 종료")
                    break
                prev_count = cur_count

            # buildId 추출
            html = page.content()
            tag  = BeautifulSoup(html, "lxml").find("script", id="__NEXT_DATA__")
            if tag:
                nd       = json.loads(tag.string)
                build_id = nd.get("buildId", "")
                log.info(f"  🔑 buildId: {build_id}")

            # 렌더링된 DOM에서 모든 레이스 상세 링크 추출
            all_links = page.eval_on_selector_all(
                'a[href*="/raceDetail/domestic/"]',
                'els => els.map(el => el.href)'
            )
            browser.close()

    except Exception as e:
        log.warning(f"  Playwright 오류: {e}")
        return []

    # 슬러그 중복 제거
    slugs = []
    seen  = set()
    for href in all_links:
        if "/raceDetail/domestic/" in href:
            slug = href.split("/raceDetail/domestic/")[1].split("?")[0].rstrip("/")
            if slug and slug not in seen:
                slugs.append(slug)
                seen.add(slug)

    log.info(f"  📌 DOM 슬러그: {len(slugs)}개 | 캐시: {len(cached)}개")

    if not slugs:
        log.warning("  → DOM에서 슬러그 추출 실패 (수동 데이터 유지)")
        return []

    # ── Step 2: 슬러그별 상세 fetch ──────────────────────────
    detail_headers = {**HEADERS, "x-nextjs-data": "1",
                      "Referer": f"{BASE}/raceSchedule/domestic"}
    for slug in slugs:
        pp = cached.get(slug)
        if pp is None and build_id:
            detail_url = (f"{BASE}/_next/data/{build_id}"
                          f"/raceDetail/domestic/{slug}.json?raceDetailUrl={slug}")
            try:
                r = requests.get(detail_url, headers=detail_headers, timeout=10)
                if r.status_code == 200 and r.content:
                    pp = r.json().get("pageProps", {})
                    log.info(f"  ✓ fetch {slug} → {list(pp.keys()) if pp else '빈 응답'}")
                else:
                    log.warning(f"  ✗ {slug}: HTTP {r.status_code}")
            except Exception as e:
                log.warning(f"  ✗ {slug}: {e}")
            time.sleep(0.3)

        if pp:
            # pageProps 안에서 레이스 dict 찾기
            race_obj = (pp.get("race") or pp.get("raceDetail") or
                        pp.get("raceInfo") or pp.get("data") or pp)
            if isinstance(race_obj, dict):
                parsed = _parse_marathongo_items([race_obj])
                races.extend(parsed)

    log.info(f"  → 마라톤고 {len(races)}건")
    return races


def _find_race_list(obj, depth=0) -> list:
    """dict/list 구조를 재귀 탐색해서 레이스 데이터로 보이는 리스트 반환"""
    if depth > 5:
        return []
    if isinstance(obj, list) and len(obj) > 2:
        if isinstance(obj[0], dict) and any(
            k in obj[0] for k in ("raceName","name","raceDate","date","startDate","title","raceTitle")
        ):
            return obj
    if isinstance(obj, dict):
        # 건수 기준으로 정렬된 후보 수집
        best = []
        for v in obj.values():
            candidate = _find_race_list(v, depth + 1)
            if len(candidate) > len(best):
                best = candidate
        return best
    return []


def _parse_marathongo_items(items: list) -> list[dict]:
    """마라톤고 API 아이템 파싱"""
    races = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            # 마라톤고 실제 필드명 (확인된 것 + 후보)
            name = (item.get("raceName") or item.get("name") or
                    item.get("title") or item.get("raceTitle") or "")
            date_raw = (item.get("raceDate") or item.get("date") or
                        item.get("startDate") or item.get("raceDay") or "")
            location = (item.get("location") or item.get("racePlace") or
                        item.get("place") or item.get("address") or "")
            reg_s = (item.get("regStartDate") or item.get("registrationStart") or
                     item.get("regStart") or "")
            reg_e = (item.get("regEndDate") or item.get("registrationEnd") or
                     item.get("regEnd") or item.get("regDeadline") or "")
            url_slug = (item.get("raceDetailUrl") or item.get("url") or
                        item.get("slug") or item.get("id") or "")
            organizer = (item.get("organizer") or item.get("host") or
                         item.get("organizerName") or "")
            start_time = (item.get("startTime") or item.get("raceTime") or "")

            # 거리 정보
            dist_raw = item.get("distances") or item.get("distList") or item.get("category") or ""
            if isinstance(dist_raw, list):
                distances = [str(d) for d in dist_raw if d]
            else:
                distances = parse_distances(str(dist_raw) or name)

            if not name or not date_raw:
                continue

            date_str, weekday = parse_date(str(date_raw))
            if not date_str:
                continue

            # url_slug가 슬러그면 상세 URL 조합
            if url_slug and not url_slug.startswith("http"):
                url_full = f"https://marathongo.co.kr/raceDetail/domestic/{url_slug}"
            elif url_slug:
                url_full = url_slug
            else:
                url_full = "https://marathongo.co.kr/raceSchedule/domestic"

            races.append({
                "type": "domestic",
                "date": date_str,
                "weekday": weekday,
                "name": name,
                "location": location,
                "startTime": str(start_time),
                "distances": distances,
                "region": guess_region(location),
                "status": infer_status(
                    str(reg_e)[:10] if reg_e else "",
                    date_str
                ),
                "regStart": str(reg_s)[:10] if reg_s else "",
                "regEnd":   str(reg_e)[:10] if reg_e else "",
                "organizer": organizer,
                "url": url_full,
                "source": "marathongo.co.kr",
                "crawledAt": datetime.now().strftime("%Y-%m-%d"),
            })
            log.info(f"  ✓ [{date_str}] {name}")
        except Exception as e:
            log.debug(f"  파싱 오류: {e}")
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

    # 시도할 URL 패턴 (사이트 구조 불확실)
    urls_to_try = [
        f"{BASE}/index_calendar.html",
        f"{BASE}/sub02_1.html",
        f"{BASE}/calendar.html",
        f"{BASE}/",
    ]

    soup = None
    for try_url in urls_to_try:
        soup = get_soup(try_url, encoding="euc-kr")
        if soup:
            # 페이지에 날짜 형식 데이터가 있는지 확인
            text = soup.get_text()
            if re.search(r"\d{4}[.\-]\d{2}[.\-]\d{2}|\d{4}년\s*\d{1,2}월", text):
                log.info(f"  ✅ 유효한 페이지: {try_url}")
                break
            else:
                log.info(f"  ⚠️  날짜 데이터 없음: {try_url}")
                soup = None

    if not soup:
        log.warning("  → 마라톤온라인 접근 실패")
        return []

    # ── 디버그: 페이지 구조 파악 ──
    tables = soup.find_all("table")
    lists  = soup.find_all(["ul", "ol"])
    all_a  = soup.find_all("a", href=True)
    log.info(f"  📄 테이블:{len(tables)} 리스트:{len(lists)} 링크:{len(all_a)}")
    # 테이블 첫 행 샘플 출력
    for i, tbl in enumerate(tables[:3]):
        rows = tbl.find_all("tr")
        log.info(f"  테이블{i}: {len(rows)}행")
        for row in rows[1:3]:
            cols = [c.get_text(strip=True)[:15] for c in row.find_all(["td","th"])]
            log.info(f"    cols: {cols}")
    # 날짜처럼 보이는 링크 샘플
    for a in all_a[:5]:
        log.info(f"  link: {a['href'][:60]} | {a.get_text(strip=True)[:30]}")

    # ── 파싱: 테이블 기반 ──
    for tbl in tables:
        rows = tbl.find_all("tr")
        for row in rows[1:]:  # 헤더 행 스킵
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            try:
                # 링크(대회명) 찾기
                name_el = row.find("a")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                if not name or len(name) < 3:
                    continue
                href = name_el.get("href", "#")
                link = (BASE + "/" + href.lstrip("/")) if not href.startswith("http") else href

                # 날짜: 첫 번째 td 혹은 날짜 패턴이 있는 td
                date_raw = ""
                for col in cols:
                    txt = col.get_text(strip=True)
                    if re.search(r"\d{4}", txt):
                        date_raw = txt
                        break

                location = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                dist_raw = cols[3].get_text(strip=True) if len(cols) > 3 else ""

                date_str, weekday = parse_date(date_raw)
                if not date_str:
                    continue

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
            except Exception as e:
                log.debug(f"  파싱 오류: {e}")

    # ── 페이지네이션 ──
    if races:
        for page_n in range(2, 6):
            next_url = f"{BASE}/index_calendar.html?page={page_n}"
            s2 = get_soup(next_url, encoding="euc-kr")
            if not s2:
                break
            prev_len = len(races)
            for tbl in s2.find_all("table"):
                for row in tbl.find_all("tr")[1:]:
                    cols = row.find_all("td")
                    if len(cols) < 2:
                        continue
                    name_el = row.find("a")
                    if not name_el:
                        continue
                    name = name_el.get_text(strip=True)
                    if not name or len(name) < 3:
                        continue
                    href = name_el.get("href", "#")
                    link = (BASE + "/" + href.lstrip("/")) if not href.startswith("http") else href
                    date_raw = ""
                    for col in cols:
                        txt = col.get_text(strip=True)
                        if re.search(r"\d{4}", txt):
                            date_raw = txt
                            break
                    date_str, weekday = parse_date(date_raw)
                    if not date_str:
                        continue
                    location = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                    dist_raw = cols[3].get_text(strip=True) if len(cols) > 3 else ""
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
            if len(races) == prev_len:
                break
            time.sleep(DELAY)

    log.info(f"  → {len(races)}건")
    return races


# ── 크롤러 3: 런벙 ───────────────────────────
def crawl_runbung() -> list[dict]:
    log.info("📡 [3/3] 런벙 크롤링...")
    BASE  = "https://www.runbung.app"
    races = []
    cached_api = []  # 인터셉트된 레이스 목록

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page()

            def on_response(response):
                try:
                    url = response.url
                    ct  = response.headers.get("content-type", "")
                    if "json" not in ct:
                        return
                    data = response.json()
                    log.info(f"  🔗 인터셉트: {url}")
                    # 배열이거나 목록 키를 가진 dict
                    items = []
                    if isinstance(data, list) and len(data) > 0:
                        items = data
                    elif isinstance(data, dict):
                        found = _find_race_list(data)
                        if found:
                            items = found
                    if items:
                        cached_api.extend(items)
                        log.info(f"  ✅ {len(items)}건 감지")
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(f"{BASE}/ko/marathons", wait_until="networkidle", timeout=30000)

            # 스크롤로 레이지 로딩 트리거
            for _ in range(5):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(1)

            html = page.content()

            # ── 디버그: 페이지 구조 파악 ──
            all_links = page.eval_on_selector_all(
                'a[href]',
                'els => els.map(el => el.href).filter(h => h.includes("marathon") || h.includes("race") || h.includes("event"))'
            )
            log.info(f"  🃏 marathon/race 관련 링크: {len(all_links)}개")
            for l in all_links[:5]:
                log.info(f"     {l}")

            # 페이지 텍스트 미리보기 (첫 500자)
            soup_text = BeautifulSoup(html, "lxml").get_text(separator=" ")
            log.info(f"  📄 텍스트: {soup_text[:300]}")

            browser.close()

    except Exception as e:
        log.warning(f"  Playwright 오류: {e}")
        return []

    # ── API 인터셉트 결과가 있으면 사용 ──
    if cached_api:
        log.info(f"  📦 인터셉트 총 {len(cached_api)}건 → 파싱 시작")
        races = _parse_api_items(cached_api, "runbung.app")
        log.info(f"  → {len(races)}건 (API)")
        return races

    # ── API 없으면 HTML BeautifulSoup 파싱 시도 ──
    log.info("  ⚠️  API 미감지 → HTML 파싱 시도")
    soup = BeautifulSoup(html, "lxml")
    # 날짜 + 이름 패턴으로 카드 탐색
    for el in soup.find_all(["article", "li", "div"], class_=re.compile(r"card|item|race|marathon|event", re.I)):
        try:
            name_el = el.find(["h1","h2","h3","h4","strong","span"], class_=re.compile(r"name|title", re.I))
            if not name_el:
                name_el = el.find(["h2","h3","h4"])
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            text = el.get_text(" ", strip=True)
            date_str, weekday = parse_date(text)
            if not name or not date_str:
                continue
            a = el.find("a", href=True)
            href = a["href"] if a else ""
            link = (BASE + href) if href.startswith("/") else href or f"{BASE}/ko/marathons"
            races.append({
                "type": "domestic", "date": date_str, "weekday": weekday,
                "name": name, "location": "", "startTime": "",
                "distances": parse_distances(text),
                "region": "기타",
                "status": infer_status("", date_str),
                "regStart": "", "regEnd": "", "organizer": "",
                "url": link, "source": "runbung.app",
                "crawledAt": datetime.now().strftime("%Y-%m-%d"),
            })
            log.info(f"  ✓ [{date_str}] {name}")
        except Exception as e:
            log.debug(f"  HTML 파싱 오류: {e}")

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
    # crawl_marathon_pe_kr()  # 추후 활성화
    # crawl_runbung()         # 추후 활성화

    existing = load_existing()
    merged   = merge(existing, fresh)

    OUTPUT_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info("─" * 55)
    log.info(f"✅ 완료: 총 {len(merged)}건 → {OUTPUT_FILE.name}")
    log.info(f"   신규 크롤링 {len(fresh)}건 / 기존 보존 {len(existing)}건")


if __name__ == "__main__":
    main()
