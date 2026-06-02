# 패션 MD 시장 모니터링 자동화 프로젝트

## 프로젝트 개요
온라인 패션 MD를 위한 시장 트렌드 자동 수집 및 리포팅 시스템.
매일 오전 10시 cron job으로 실행되며, 노션 DB 누적 저장 + HTML 대시보드 자동 생성.

---

## 디렉토리 구조

```
fashion-monitor/
├── CLAUDE.md              # 이 파일
├── main.py                # 전체 실행 진입점
├── config.py              # API 키 및 설정값 관리
├── collectors/
│   ├── musinsa.py         # 무신사 랭킹 스크래퍼
│   ├── google_trends.py   # 구글 트렌드 수집 (pytrends)
│   ├── naver_datalab.py   # 네이버 데이터랩 API
│   └── instagram.py       # 인스타그램 해시태그 (instaloader)
├── analyzers/
│   ├── rank_diff.py       # 전날 대비 순위 변동 분석
│   ├── new_entry.py       # 신규 진입 상품 감지 + 상세 스크래핑
│   ├── price_analysis.py  # 가격대 분포 분석
│   ├── brand_tracker.py   # 경쟁 브랜드 랭킹 추적
│   └── timing_signal.py   # 기획전 타이밍 감지 (트렌드 + 랭킹 교차)
├── exporters/
│   ├── notion_exporter.py # 노션 DB 저장
│   ├── dashboard.py       # HTML 대시보드 생성
│   ├── weekly_report.py   # 주간 리포트 생성 (매주 월요일)
│   └── kakao_notify.py    # 카카오톡 요약 알림 발송
├── data/
│   ├── dashboard.html     # 생성된 대시보드 (자동 덮어쓰기)
│   └── reports/           # 주간 리포트 저장 폴더
└── logs/
    └── run.log            # 실행 로그
```

---

## 수집 모듈별 상세 스펙

### 1. 무신사 랭킹 트래커 (`collectors/musinsa.py`)

**목표**: 무신사 전체 랭킹에서 상의 / 아우터 / 바지 카테고리 상위 30위 수집

**수집 항목**:
- 순위 (rank)
- 상품명 (product_name)
- 브랜드명 (brand)
- 가격 (price)
- 할인율 (discount_rate)
- 상품 URL (url)
- 수집 일자 (collected_at)

**카테고리 코드** (무신사 URL 파라미터 기준):
- 상의: `001`
- 아우터: `002`
- 바지: `003`

**방법**: `requests` + `BeautifulSoup4`로 공개 랭킹 페이지 스크래핑
- User-Agent 설정 필수 (봇 차단 우회)
- 요청 간 1~2초 딜레이 적용
- 실패 시 3회 재시도 로직 포함

---

### 2. 구글 트렌드 (`collectors/google_trends.py`)

**목표**: 패션 관련 키워드 검색 트렌드 수집

**기본 키워드 목록** (config.py에서 수정 가능):
```python
FASHION_KEYWORDS = [
    "무신사", "오버핏", "데님재킷", "린넨셔츠", "슬랙스",
    "캐주얼아우터", "니트조끼", "와이드팬츠", "반팔티", "후드집업"
]
```

**수집 방법**: `pytrends` 라이브러리
- 지역: `KR` (대한민국)
- 기간: 최근 7일 (`today 7-d`)
- 키워드 5개씩 묶어서 요청 (pytrends 제한)

**수집 항목**:
- 키워드별 관심도 점수 (0~100)
- 전주 대비 변화율
- 수집 일자

---

### 3. 네이버 데이터랩 (`collectors/naver_datalab.py`)

**목표**: 네이버 쇼핑 패션 카테고리 검색어 트렌드

**API 정보**:
- 엔드포인트: `https://openapi.naver.com/v1/datalab/shopping/categories`
- 인증: Client ID / Client Secret (config.py에 저장)
- 공식 문서: https://developers.naver.com/docs/serviceapi/datalab/shopping/shopping.md

**수집 카테고리**:
- 상의 (카테고리 ID: `50000000`)
- 아우터 (카테고리 ID: `50000001`)
- 바지 (카테고리 ID: `50000003`)

**수집 항목**:
- 카테고리별 검색량 지수
- 성별/연령별 분포 (제공 시)
- 수집 일자

---

### 4. 인스타그램 해시태그 (`collectors/instagram.py`)

**목표**: 패션 관련 해시태그 게시물 수 및 트렌드 파악

**방법**: `instaloader` 라이브러리
- ⚠️ 불안정할 수 있음 - 실패 시 해당 모듈만 스킵하고 나머지 계속 실행
- 로그인 없이 공개 해시태그만 수집

**수집 해시태그**:
```python
INSTAGRAM_TAGS = [
    "무신사", "오늘의코디", "데일리룩", "패션", "ootd",
    "아우터", "데님", "슬랙스", "오버핏", "스트릿패션"
]
```

**수집 항목**:
- 해시태그별 최근 게시물 수
- 수집 일자

---

## 분석 모듈별 상세 스펙

### 1. 순위 변동 분석 (`analyzers/rank_diff.py`)

**목표**: 전날 데이터와 오늘 데이터를 비교해 순위 변동 계산

**로직**:
- 노션 DB에서 어제 날짜 데이터 조회
- 오늘 수집 데이터와 상품명 기준으로 매칭
- 변동폭 계산: `rank_change = yesterday_rank - today_rank` (양수 = 상승)
- 결과를 오늘 노션 데이터에 `rank_change` 컬럼으로 업데이트

**출력**:
```python
{
  "top_risers": [{"product": "린넨셔츠", "change": +8}, ...],  # 상승 TOP5
  "top_fallers": [{"product": "MA-1재킷", "change": -5}, ...], # 하락 TOP5
  "new_entries": [...],   # 신규 진입
  "dropouts": [...]       # 이탈 상품
}
```

---

### 2. 신규 진입 상품 감지 (`analyzers/new_entry.py`)

**목표**: 어제 랭킹에 없었던 신규 진입 상품을 감지하고 상세 정보 추가 수집

**로직**:
- 어제 랭킹에 없는 상품 = 신규 진입으로 판단
- 신규 진입 상품의 URL로 상세 페이지 추가 스크래핑

**추가 수집 항목**:
- 소재 (material)
- 핏 (fit_type): 오버핏 / 슬림핏 / 레귤러 등
- 주요 색상 (colors)
- 리뷰 수 (review_count)
- 평점 (rating)

**저장**: 노션 별도 DB `신규진입상품` 에 저장

---

### 3. 가격대 분포 분석 (`analyzers/price_analysis.py`)

**목표**: 상위 30위 상품의 가격 분포로 "요즘 잘 팔리는 가격대" 인사이트 추출

**분석 항목**:
- 카테고리별 평균가 / 중간값 / 최빈 가격대
- 가격 구간별 상품 수 (1~3만 / 3~5만 / 5~10만 / 10만 이상)
- 전주 대비 평균가 변화 (가격 트렌드)
- 할인율 TOP 5 상품

**출력 예시**:
```
[상의] 평균 58,000원 | 5~7만원대 가장 많음 (12개) | 전주 대비 -2,000원
[아우터] 평균 142,000원 | 10만 이상 집중 (18개)
[바지] 평균 79,000원 | 7~10만원대 가장 많음 (14개)
```

---

### 4. 경쟁 브랜드 트래킹 (`analyzers/brand_tracker.py`)

**목표**: 관심 브랜드의 랭킹 변동을 별도로 추적

**관심 브랜드 목록** (config.py에서 관리):
```python
WATCH_BRANDS = [
    "MATIN KIM", "COVERNAT", "KIRSH", "ADER ERROR",
    "ROMANTIC CROWN", "CARHARTT WIP"
    # 담당 브랜드 추가 가능
]
```

**분석 항목**:
- 브랜드별 랭킹 내 상품 수
- 브랜드별 최고 순위 상품
- 주간 평균 순위 변화
- 신규 진입 / 이탈 감지

**저장**: 노션 `브랜드트래킹` DB에 누적

---

### 5. 기획전 타이밍 감지 (`analyzers/timing_signal.py`)

**목표**: 트렌드 급등 + 랭킹 상승이 동시에 일어나는 "기획전 골든타임" 자동 감지

**감지 조건** (아래 2가지 동시 충족 시 신호 발생):
- 구글/네이버 트렌드 점수 전주 대비 **+20% 이상** 상승
- 무신사 랭킹 **5계단 이상** 상승 or 신규 진입

**출력 예시**:
```
🎯 기획전 타이밍 시그널 감지!
키워드: 린넨셔츠
- 구글 트렌드: +42% (92점)
- 무신사 랭킹: 상의 1위 (▲3)
→ 추천 기획전 테마: "여름 린넨 컬렉션"
```

**저장**: 노션 `기획전시그널` DB에 저장 + 카카오톡 즉시 알림

---

## 알림 모듈 (`exporters/kakao_notify.py`)

**목표**: 매일 수집 완료 후 핵심 인사이트를 카카오톡으로 발송

**방법**: 카카오톡 나에게 보내기 API (카카오 디벨로퍼스 앱 등록 필요)
- 공식 문서: https://developers.kakao.com/docs/latest/ko/message/rest-api

**발송 내용 (일일 요약)**:
```
[패션 모니터] 06.02 오전 10시

📈 오늘의 급등 키워드
  구글: 린넨셔츠 +42%
  네이버: 슬랙스 +18%

⬆ 신규 진입 상품 (3개)
  나일론점퍼 / MATIN KIM / 128,000원
  오버핏티 / ADER ERROR / 72,000원
  린넨재킷 / THEORY / 185,000원

🔥 TOP 3 (전체)
  1위 오버핏 린넨셔츠 / KIRSH ▲3
  2위 와이드 데님팬츠 / COVERNAT ▲1
  3위 나일론 점퍼 / MATIN KIM NEW

🎯 기획전 시그널
  린넨셔츠 — 트렌드 + 랭킹 동시 급등
```

**기획전 시그널 감지 시**: 일반 알림과 별도로 즉시 추가 발송

---

## 주간 리포트 (`exporters/weekly_report.py`)

**실행 조건**: 매주 월요일 오전 10시 (main.py에서 요일 체크)

**생성 파일**: `data/reports/weekly_YYYYMMDD.pdf`

**포함 내용**:
1. 이번 주 카테고리별 랭킹 변동 요약
2. 주간 TOP 상승 브랜드 / 상품
3. 트렌드 키워드 주간 흐름 차트
4. 신규 진입 상품 목록 (소재 / 가격 포함)
5. 가격대 분포 변화
6. 기획전 시그널 발생 이력
7. 다음 주 주목 키워드 예측

**생성 방법**: `matplotlib` + `reportlab` 으로 PDF 생성
- 노션에도 동일 내용 페이지로 자동 생성

---

## 노션 저장 (`exporters/notion_exporter.py`)

**사전 준비**:
1. 노션 인테그레이션 생성 → API 키 발급
2. 아래 데이터베이스 노션에 미리 생성 후 DB ID를 config.py에 입력

**데이터베이스 구조**:

### DB 1: 무신사 랭킹
| 컬럼 | 타입 |
|------|------|
| 날짜 | Date |
| 카테고리 | Select |
| 순위 | Number |
| 순위변동 | Number |
| 상품명 | Title |
| 브랜드 | Text |
| 가격 | Number |
| 할인율 | Number |
| URL | URL |

### DB 2: 트렌드 키워드
| 컬럼 | 타입 |
|------|------|
| 날짜 | Date |
| 플랫폼 | Select (구글/네이버/인스타) |
| 키워드 | Title |
| 점수/수치 | Number |
| 전주대비 변화 | Number |

### DB 3: 신규진입상품
| 컬럼 | 타입 |
|------|------|
| 날짜 | Date |
| 카테고리 | Select |
| 상품명 | Title |
| 브랜드 | Text |
| 가격 | Number |
| 소재 | Text |
| 핏타입 | Select |
| 리뷰수 | Number |
| 평점 | Number |
| URL | URL |

### DB 4: 브랜드트래킹
| 컬럼 | 타입 |
|------|------|
| 날짜 | Date |
| 브랜드 | Title |
| 랭킹내상품수 | Number |
| 최고순위 | Number |
| 최고순위상품 | Text |

### DB 5: 기획전시그널
| 컬럼 | 타입 |
|------|------|
| 날짜 | Date |
| 키워드 | Title |
| 트렌드상승률 | Number |
| 랭킹변동 | Number |
| 추천테마 | Text |

---

## HTML 대시보드 (`exporters/dashboard.py`)

**생성 파일**: `data/dashboard.html` (매일 덮어쓰기)
**브라우저에서 바로 열 수 있는 단일 HTML 파일로 생성**

**포함 섹션**:
1. 오늘 날짜 + 마지막 업데이트 시각
2. 오늘의 기획전 시그널 하이라이트
3. 무신사 랭킹 TOP 10 (카테고리별 탭, 순위변동 표시)
4. 신규 진입 상품 카드
5. 구글/네이버 트렌드 키워드 차트
6. 인스타 해시태그 인기순 목록
7. 가격대 분포 차트 (카테고리별)
8. 브랜드 트래킹 현황

**차트 라이브러리**: Chart.js (CDN, 인터넷 연결 필요)

---

## 설정 파일 (`config.py`)

```python
# 네이버 데이터랩 API
NAVER_CLIENT_ID = ""
NAVER_CLIENT_SECRET = ""

# 노션 API
NOTION_API_KEY = ""
NOTION_RANKING_DB_ID = ""
NOTION_TREND_DB_ID = ""
NOTION_NEW_ENTRY_DB_ID = ""
NOTION_BRAND_DB_ID = ""
NOTION_SIGNAL_DB_ID = ""

# 카카오톡 나에게 보내기
KAKAO_ACCESS_TOKEN = ""

# 인스타그램 (선택, 로그인 없이도 동작)
INSTAGRAM_USERNAME = ""
INSTAGRAM_PASSWORD = ""

# 수집 설정
MUSINSA_TOP_N = 30          # 카테고리별 상위 몇 위까지
REQUEST_DELAY = 1.5         # 요청 간 딜레이 (초)
DASHBOARD_OUTPUT_PATH = "data/dashboard.html"
REPORT_OUTPUT_DIR = "data/reports/"
LOG_PATH = "logs/run.log"

# 관심 브랜드 (브랜드 트래킹용)
WATCH_BRANDS = [
    "MATIN KIM", "COVERNAT", "KIRSH", "ADER ERROR",
    "ROMANTIC CROWN", "CARHARTT WIP"
]

# 기획전 시그널 감지 임계값
TREND_SURGE_THRESHOLD = 20   # 트렌드 상승률 (%)
RANK_SURGE_THRESHOLD = 5     # 랭킹 상승 계단 수
```

---

## 실행 방법

### 수동 실행
```bash
cd ~/fashion-monitor
python main.py
```

### cron job 설정 (매일 오전 10시)
```bash
# crontab -e 에 추가
0 10 * * * cd ~/fashion-monitor && /usr/bin/python3 main.py >> logs/cron.log 2>&1
```

### 대시보드 열기
```bash
open data/dashboard.html
```

---

## 의존성 설치

```bash
pip install requests beautifulsoup4 pytrends instaloader notion-client matplotlib reportlab
```

---

## 에러 처리 원칙

- 각 수집/분석 모듈은 독립적으로 실행 → 하나 실패해도 나머지는 계속 진행
- 모든 에러는 `logs/run.log`에 기록
- 무신사 스크래핑 실패 시: 3회 재시도 후 스킵
- 인스타 수집 실패 시: 경고 로그만 남기고 스킵 (가장 불안정)
- 노션 저장 실패 시: 로컬 CSV 백업 (`data/backup_YYYYMMDD.csv`)
- 카카오 발송 실패 시: 로그만 기록하고 계속 진행

---

## 주의사항

- 무신사 스크래핑은 공개 페이지 기준으로만 수집 (로그인 불필요)
- 과도한 요청은 IP 차단 가능 → `REQUEST_DELAY` 1.5초 이상 유지
- 인스타그램 instaloader는 자주 막힐 수 있음 → 실패해도 무시하도록 설계
- API 키는 절대 코드에 직접 입력하지 말고 `config.py`에만 저장
- `config.py`는 `.gitignore`에 추가할 것

---

## 작업 시작 순서 (Claude Code에서 실행 시)

1. `config.py` 생성 및 API 키 입력 안내
2. `collectors/musinsa.py` 작성 및 테스트
3. `collectors/google_trends.py` 작성 및 테스트
4. `collectors/naver_datalab.py` 작성 및 테스트
5. `collectors/instagram.py` 작성 및 테스트
6. `analyzers/rank_diff.py` 작성 및 테스트
7. `analyzers/new_entry.py` 작성 및 테스트
8. `analyzers/price_analysis.py` 작성 및 테스트
9. `analyzers/brand_tracker.py` 작성 및 테스트
10. `analyzers/timing_signal.py` 작성 및 테스트
11. `exporters/notion_exporter.py` 작성 및 테스트
12. `exporters/kakao_notify.py` 작성 및 테스트
13. `exporters/dashboard.py` 작성 및 테스트
14. `exporters/weekly_report.py` 작성 및 테스트
15. `main.py` 통합 실행 테스트
16. cron job 등록
