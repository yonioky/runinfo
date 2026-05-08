# 🏃 RunInfo — 마라톤 대회 정보 포털

국내/해외 마라톤 대회 일정을 모아서 보여주는 웹사이트입니다.  
**GitHub Actions**로 매주 자동 크롤링하고, **GitHub Pages**로 무료 호스팅합니다.

---

## 📁 파일 구성

```
marathon-project/
├── .github/
│   └── workflows/
│       ├── crawl.yml       ← 매주 자동 크롤링 (월 오전 9시 KST)
│       └── pages.yml       ← GitHub Pages 자동 배포
├── index.html              ← 웹사이트 (races.json 자동 로드)
├── crawler.py              ← 마라톤 정보 크롤러
├── races.json              ← 대회 데이터 (크롤러가 자동 갱신)
└── README.md
```

---

## 🚀 GitHub에 올려서 무료 호스팅하기 (5단계)

### 1단계 — GitHub 저장소 만들기
1. [github.com](https://github.com) 로그인
2. 우측 상단 **`+`** → **New repository**
3. 저장소 이름: `runinfo` (또는 원하는 이름)
4. **Public** 선택 후 **Create repository**

### 2단계 — 파일 업로드
방법 A (드래그앤드롭):
- 저장소 페이지에서 **`uploading an existing file`** 클릭
- 이 폴더 전체를 드래그해서 업로드
- `.github` 폴더가 포함됐는지 꼭 확인

방법 B (Git CLI):
```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/runinfo.git
git push -u origin main
```

### 3단계 — GitHub Pages 활성화
1. 저장소 → **Settings** → **Pages**
2. Source: **GitHub Actions** 선택
3. 저장

### 4단계 — Actions 권한 설정
1. 저장소 → **Settings** → **Actions** → **General**
2. **Workflow permissions** → **Read and write permissions** 체크
3. 저장

### 5단계 — 첫 배포 & 크롤링
1. **Actions** 탭 → `마라톤 데이터 자동 수집` → **Run workflow**
2. **Actions** 탭 → `GitHub Pages 배포` → **Run workflow**
3. 잠시 후 `https://YOUR_USERNAME.github.io/runinfo` 접속!

---

## ⏰ 자동화 스케줄

| 작업 | 주기 | 시각 |
|------|------|------|
| 크롤링 | 매주 월요일 | 오전 9:00 (KST) |
| Pages 배포 | races.json 변경 시 | 자동 트리거 |

> 크롤링 → races.json 업데이트 → Pages 배포 순으로 자동 진행됩니다.

---

## 🔧 데이터 직접 추가하기

`races.json`에 항목을 추가하면 사이트에 즉시 반영됩니다.

```json
{
  "type": "domestic",
  "date": "2026-07-05",
  "weekday": "일",
  "name": "내가 만든 마라톤 대회",
  "location": "서울 | 한강공원",
  "startTime": "07:00",
  "distances": ["풀", "하프", "10km"],
  "region": "서울",
  "status": "upcoming",
  "regStart": "2026-05-01",
  "regEnd": "2026-06-30",
  "organizer": "주최기관명",
  "url": "https://대회공식사이트.com"
}
```

`status` 값:
- `"open"` → 접수중 (초록)
- `"upcoming"` → 접수전 (노랑)
- `"closed"` → 접수마감 (회색)

---

## 📋 크롤링 대상 사이트

| 사이트 | URL | 비고 |
|--------|-----|------|
| 마라톤온라인 | http://www.marathon.pe.kr | 국내 최대 마라톤 정보 |
| 달리자 | https://www.dallija.com | 러닝 대회 일정 |

---

## 🗺️ 향후 개발 아이디어

- [ ] 해외 대회 크롤러 추가 (World Athletics, AIMS)
- [ ] 페이스 계산기 탭
- [ ] 대회 즐겨찾기 & 캘린더 내보내기
- [ ] 지도로 대회 위치 보기 (Kakao Maps API)
- [ ] 모바일 최적화 / PWA
