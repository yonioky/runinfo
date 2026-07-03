#!/usr/bin/env python3
"""
prerender.py — races.json의 대회 목록을 index.html에 정적 HTML로 주입한다.

목적: index.html은 JS로 races.json을 fetch해서 대회 카드를 그린다(클라이언트 렌더링).
그래서 JS를 실행하지 않는 구글 크롤러 / 애드센스 리뷰어 / 단순 fetch 에는
대회 목록이 '빈 페이지'로 보인다. 이 스크립트는 렌더 결과와 동일한 카드 HTML을
빌드 시점에 미리 생성해 index.html 원본에 박아넣어, JS 없이도 실제 콘텐츠가 보이게 한다.

크롤러가 볼 기본 화면 = 브라우저 초기 화면과 동일하게 맞춘다:
  국내(domestic) 대회 중 오늘 이후(date >= today), 날짜 오름차순.
JS가 로드되면 renderRaces()가 동일 내용으로 다시 그리므로 사용자에겐 차이가 없다.

재실행 안전(idempotent): <!--PRERENDER--> ... <!--/PRERENDER--> 마커 사이만 교체한다.
crawler.py 로 races.json 을 갱신한 뒤 이 스크립트를 한 번 돌리면 된다.
"""
import json
import re
import html
import datetime
import pathlib
from urllib.parse import quote

ROOT = pathlib.Path(__file__).parent
RACES_JSON = ROOT / "races.json"
INDEX_HTML = ROOT / "index.html"

# index.html 의 매핑을 그대로 복제
DIST_CLS = {
    "풀": "b-full", "하프": "b-half", "10km": "b-10k", "5km": "b-5k", "3km": "b-5k",
    "100km": "b-ultra", "50km": "b-ultra", "울트라": "b-ultra",
    "트레일": "b-trail", "25km": "b-other",
}
STATUS_KR = {"upcoming": "접수전", "open": "접수중", "closed": "접수마감"}
STATUS_CLS = {"open": "s-open", "upcoming": "s-upcoming", "closed": "s-closed"}


def get_dday(date_str, today):
    y, m, d = map(int, date_str.split("-"))
    diff = (datetime.date(y, m, d) - today).days
    if diff < 0:
        return ("종료", "dday-past")
    if diff == 0:
        return ("D-DAY", "dday-today")
    if diff <= 30:
        return (f"D-{diff}", "dday-soon")
    if diff <= 90:
        return (f"D-{diff}", "dday-mid")
    return (f"D-{diff}", "dday-far")


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def render_card(r, today):
    mo_i = int(r["date"].split("-")[1])
    d_i = int(r["date"].split("-")[2])
    is_intl = r.get("type") == "intl"
    label, cls = get_dday(r["date"], today)
    badges = "".join(
        f'<span class="badge {DIST_CLS.get(x, "b-other")}">{esc(x)}</span>'
        for x in r.get("distances", [])
    )
    naver = "https://search.naver.com/search.naver?query=" + quote(r.get("name", ""))
    start = f'<span>{esc(r["startTime"])} 출발</span>' if r.get("startTime") else ""
    reg = (
        f'접수 {esc(r["regStart"])}<br>~ {esc(r.get("regEnd", ""))}'
        if r.get("regStart") else ""
    )
    return f"""      <div class="race-card" onclick="window.open('{esc(naver)}','_blank')">
        <div class="race-date{' intl' if is_intl else ''}">
          <span class="rd-month">{mo_i}월</span>
          <span class="rd-day">{d_i}</span>
          <span class="rd-week">({esc(r.get("weekday", ""))})</span>
          <span class="dday-badge {cls}">{label}</span>
        </div>
        <div class="race-body">
          <div class="race-badges">{badges}</div>
          <div class="race-name">{esc(r.get("name", ""))}</div>
          <div class="race-meta">
            <span>{esc(r.get("location", ""))}</span>
            {start}
          </div>
        </div>
        <div class="race-right">
          <span class="status-badge {STATUS_CLS.get(r.get("status"), "")}">{STATUS_KR.get(r.get("status"), "")}</span>
          <div class="reg-period">{reg}</div>
        </div>
      </div>"""


def main():
    today = datetime.date.today()
    today_str = today.isoformat()
    races = json.loads(RACES_JSON.read_text(encoding="utf-8"))

    default_list = sorted(
        (r for r in races
         if r.get("type") == "domestic" and r.get("date", "") >= today_str),
        key=lambda r: r["date"],
    )
    cards = "\n".join(render_card(r, today) for r in default_list)
    count = len(default_list)

    text = INDEX_HTML.read_text(encoding="utf-8")

    # 1) race-list 컨테이너 내부를 마커와 함께 교체.
    #    바로 뒤 empty-state div 를 앵커로 삼아 컨테이너 범위를 정확히 잡는다.
    inner = f"<!--PRERENDER-->\n{cards}\n      <!--/PRERENDER-->\n  "
    container_re = re.compile(
        r'(<div class="race-list" id="race-list">).*?(</div>\s*<div class="empty-state")',
        re.DOTALL,
    )
    if not container_re.search(text):
        raise SystemExit("race-list 컨테이너를 찾지 못함 — index.html 구조 확인 필요")
    text = container_re.sub(lambda m: m.group(1) + inner + m.group(2), text, count=1)

    # 2) 결과 개수 표시 갱신
    text = re.sub(r'(<strong id="count">)\d*(</strong>)',
                  rf"\g<1>{count}\g<2>", text, count=1)

    INDEX_HTML.write_text(text, encoding="utf-8")
    print(f"[prerender] 국내 예정 대회 {count}건을 index.html 에 정적 주입 완료 (기준일 {today_str})")


if __name__ == "__main__":
    main()
