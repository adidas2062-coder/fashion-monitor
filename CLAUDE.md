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
│   └── timing_signal.py   # 기획전 타이밍 감지 (내부 랭킹·검색어 우선, 트렌드는 참고)
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

**목표**: 무신사/29CM 내부 흐름 급등을 "기획전 골든타임"으로 자동 감지 (내부 데이터 우선판, 2026-07-02 개편)

**설계 원칙 (내부 데이터 우선)**: 무신사/29CM **내부 지표가 주**, 네이버/구글 검색
트렌드는 **참고 가점**이다. 시그널은 내부 근거(랭킹 급등·신규 진입 매칭 / 실시간
검색어 상승 / 내부 키워드 흐름 뚜렷한 증가) 중 하나 이상 있어야만 생성된다 —
검색 트렌드 급등만으로는 시그널이 만들어지지 않는다(내부 근거 게이트). 후보
키워드는 트렌드 급등 ∪ 실시간 검색어 상승 ∪ 내부 사전(`FASHION_KEYWORDS`+테마
키워드)이 랭킹 급등/신규 상품 2개 이상과 매칭되는 경우의 합집합이다.

**감지 지표** (0~100점 신뢰도 점수로 종합, 2026-07-02 2차 개편 — 강도형 배점):
1. 랭킹 강도 — 매칭 존재 "여부"가 아니라 **강도**로 차등 (1차 개편의 포화 문제 해소):
   기본 4~15점(신규 진입/10계단 이상 급등 15, `RANK_SURGE_THRESHOLD` 이상 10, 그 외 4)
   + 매칭 상품 개수 보너스 5점×(개수-1, 최대 10) + 매칭 최고 순위 TOP10 보너스 5
   = 최대 30점, 카테고리 실측 비중 가중 후 35점 캡 [내부·주]
2. 내부 키워드 흐름 — 랭킹 내 키워드 포함 상품 수의 최근 2일 vs 직전 5일 추세
   (`_keyword_flow`, **-15~+25점**: 급증 +25 / 증가 +15 / 안정 +3 / 감소 -8 / 급감 -15;
   4일 미만 히스토리 또는 평균 3개 미만 표본이면 0점) [내부·주]
3. 실시간 검색어 — 무신사 실시간 검색어 TOP30 (`collectors/musinsa_keywords`) 진입/상승
   (NEW·▲3 이상 20점 / 상승 12점 / 유지 5점) [내부·주]
4. 트렌드 급등 — 구글/네이버 전주 대비 **+20% 이상**(`TREND_SURGE_THRESHOLD`) 상승 (최대 10점).
   절대 지수가 `TREND_MIN_ABS_SCORE`(기본 20) 미만이면 백분율이 커도 노이즈로 간주해
   0점 (예: 지수 1.5→4.6 = +197% 저기저 노이즈 차단) [외부·참고]
5. 할인율 급등 — 카테고리 평균 할인율 전날 대비 5%p 이상 상승 (10점)
6. 복수 카테고리 교차 — 매칭 상품이 상의/아우터/바지 중 2개 대분류 이상에 분포 (5점,
   내부 랭킹 기준 — 과거 트렌드 의존 정의는 발동률 0%라 폐기)
7. 품절 비율 급증 — 카테고리 내 품절 상품 20% 이상 (3점)
8. YoY 비교 — 작년 동기(`musinsa_archive`) 동일 키워드 랭킹 대비 순위 상승 (3점)
9. 할인 지속성 — `snapshot_store` 히스토리 기준 카테고리 평균 할인율이 N일 연속 상승 중인지 (최대 5점 보너스)
10. 가격대 경쟁력 — 매칭 상품 가격이 동일 카테고리 평균가 대비 **±30% 이상** 벗어났는데도
   랭킹이 급등한 경우(저가 회전 수요 또는 고가 프레스티지 수요 추정, 최대 3점 보너스).
   평균가 비교군이 3건 미만이면 보정 없음(0점, 정보 부족으로 판단).

**중복 억제**: 같은 날 포함관계 키워드(후드 ⊂ 후드집업)는 점수가 높은 대표 1개만 남긴다.
**대시보드 노출 상한**: 주의(50점) 이상 상위 5건만 카드, 나머지는 접힌 목록(`_signal_cards`).

`detect()`는 맨 끝 선택 인자 `realtime_keywords`(=`musinsa_keywords.collect()` 반환)를
받으며 main.py가 전달한다. 실시간 검색어는 `musinsa_keywords` 스냅샷으로도 매일 저장된다.

**정기 재보정**: `python3 signal_score_audit.py` — 스냅샷 전 기간 소급 시뮬레이션으로
지표 발동률(포화/사망), day7 백테스트 적중률, 점수↔성과 상관을 출력한다. 배점 조정 전후
비교용. 2~4주마다 실행 권장 (2026-07-02 기준: 상대 적중률 33%, 50점대 45% vs 30점대 28%,
점수↔상대성과 r=+0.22 — 점수 버킷 간 변별력은 생겼으나 미세 점수 차는 아직 무의미).

**계절 보정 (점진적, 단순 on/off 아님)**: 기존 "최고기온 28도 이상이면 겨울 키워드 -20점"
같은 단순 규칙 대신, 기온이 카테고리별 기준 구간(겨울 키워드 24도, 여름 키워드 14도)을
벗어난 정도와 카테고리별 계절 감도 가중치(`_WINTER_SEASON_WEIGHT`/`_SUMMER_SEASON_WEIGHT`,
예: 패딩·코트는 강하게, 니트·조끼는 약하게)를 곱해 **-20 ~ +5점 사이의 연속값**으로 보정한다.
계절이 맞아떨어지면 소폭(+5점) 보너스도 부여한다.

**백테스트 피드백 연결**: `detect()`는 선택 인자 `backtest_feedback`(=
`signal_backtest.keyword_hit_weights()` 반환 dict, 기본값 `None`)을 받는다. 주어지면
동일 키워드 패턴의 과거 적중률(50% 기준점, -10~+10점)을 점수에 가산/감산한다.
표본이 2건 미만인 키워드는 과신을 막기 위해 가중치를 적용하지 않는다. 기존 위치인자
호출(`detect(trend_data, rank_result, archive_data, weather_data)`)은 그대로 동작하며,
이 인자는 맨 끝에 추가되어 하위호환을 깨지 않는다.

**점수 산출 투명성**: 각 시그널 dict에는 다음 필드가 포함되어 MD가 점수의 근거와
다음 행동을 바로 파악할 수 있다.
- `score_breakdown`: 지표별 기여 점수 dict (트렌드/랭킹/할인/품절/교차/YoY/할인지속성/
  가격대경쟁력/계절보정/백테스트피드백)
- `score_range`: 보강 지표 개수에 따른 점수 상/하한 휴리스틱 범위(`confidence_band`는
  동일 값을 가리키는 하위호환용 별칭). **통계적 신뢰구간이 아니다** — 표본 수·과거
  분산·백테스트 적중률을 사용하지 않고, "보강 지표가 몇 개 함께 확인됐는지"만으로
  범위를 넓히거나 좁히는 단순 휴리스틱이다. 통계적으로 검증된 신뢰도가 필요하면
  `signal_backtest.aggregate_stats()`의 카테고리/점수대별 표본 수·적중률을 함께 봐야 한다.
- `evidence_detail`: "왜 이 점수인지"를 설명하는 한국어 문장 목록
- `next_checks`: 기획전 오픈 전 MD가 추가로 확인해야 할 체크리스트(카테고리 페이지, 트렌드 추이,
  재입고 일정, 가격대 적정성 등)
- `price_competitiveness_bonus` / `price_note`: 가격대 경쟁력 보너스 값과 그 근거 설명
- `weather_conflict`: 기존 단순 on/off 판정(`_weather_conflict`, 최고기온 28도/8도
  기준)뿐 아니라, 신규 점진적 보정값 `seasonal_adjustment`가 음수(역행 페널티 적용)인
  경우도 `True`로 반영한다. 예를 들어 25도에서 후드 키워드는 점진적 보정으로
  `seasonal_adjustment=-3.9`(역행 감지)가 나오는데, 이 필드가 기존 on/off 기준으로만
  `False`였다면 `main.py`/`exporters/dashboard.py`처럼 이 필드만 소비하는 호출부가
  계절 충돌을 놓치게 된다 — 두 판정 중 하나라도 역행이면 `True`로 통일했다.
- 계절 보정 공식은 기준 기온(겨울 24도/여름 14도)에서 정확히 0점으로 시작해
  연속적으로 증가하는 1차 함수(`(temp_max - 24) * 1.3 * weight`)다. 과거에는
  기준 통과 즉시 고정 베이스 페널티가 붙어 23.9도→0점, 24.0도→-5.8점처럼
  불연속적으로 점프했으나, 이를 제거해 진정한 연속(점진적) 보정으로 수정했다.

**출력 예시**:
```
🎯 기획전 타이밍 시그널 감지!
키워드: 린넨셔츠
- 구글 트렌드: +42% (92점)
- 무신사 랭킹: 상의 1위 (▲3)
→ 추천 기획전 테마: "여름 린넨 컬렉션"
→ score_breakdown: trend 30 / rank 15 / discount_surge 15 / seasonal_adjustment +5
→ next_checks: ["무신사 상의 카테고리 랭킹 재확인", "할인 종료 예정일 확인", ...]
```

**저장**: 노션 `기획전시그널` DB에 저장 + 카카오톡 즉시 알림

---

### 6. 과거 추천 백테스트 (`analyzers/signal_backtest.py`)

**목표**: 과거 기획전 시그널이 실제로 랭킹 상승에 기여했는지, 시장 전체(시즌)
상승효과와 분리해 검증하고, 그 결과를 다음 시그널 스코어링에 피드백한다.

**`evaluate(signals_by_date, rankings_by_date, today=None)`**: 시그널 발생일 기준
+3일/+7일 후 평균 랭킹 변화로 적중(day7_change>=3)/부분 적중/실패/보류를 판정한다
(기존 동작 그대로 유지). 추가로 다음 신규 필드를 포함한다.
- `market_day3_change` / `market_day7_change`: 동일 카테고리 시장 전체(또는 카테고리
  무관 전체)의 같은 기간 평균 순위 변화 — 시즌효과 베이스라인. 기준일 코호트(시그널
  상품 자신은 제외) 중 후속일에 랭킹 밖으로 완전히 이탈한 상품은 평균 계산에서
  제외하지 않고 "TOP N 바로 밖(N+1위)"으로 떨어졌다고 간주해 포함한다(생존자
  편향 방지 — 살아남은 상품만으로 시장 성과를 평균 내면 실제로 시장이 하락했어도
  양수로 왜곡될 수 있다).
- `relative_day3_change` / `relative_day7_change`: `day*_change - market_day*_change`,
  시장효과를 제거한 시그널 고유의 순수 기여분.
- `relative_status`: 상대성과 기준의 별도 판정(적중/부분 적중/실패/보류). 절대 변화
  기준 `status`와 상호보완적으로 사용한다.
- `day3_change_dropout` / `day7_change_dropout`: 추천 상품(키워드/상품명 기준)이
  해당 기간 후속 랭킹에서 완전히 매칭되지 않으면(품절·순위 밖 탈락) True가 된다.
  이 경우 카테고리 평균으로 대체하지 않고 `day*_change`를 `None`으로 유지해
  "이탈했는데도 카테고리 평균 순위로 부분 적중 처리되는" 허위 판정을 막는다
  (`status`는 `보류`가 되며 `reason`에 이탈 사실이 명시된다).

기존 반환 키(`signal_date`/`keyword`/`theme`/`score`/`base_rank`/`day3_change`/
`day7_change`/`status`/`reason`)는 모두 그대로 유지된다.

**상품 매칭은 카테고리로 먼저 좁힌다**: `_matching()`은 시그널의 `category`와
동일한 카테고리 풀에서 상품명/키워드를 매칭한 뒤, 매칭 실패 시에만 카테고리
필터 없이 전체로 폴백한다. 그렇지 않으면 "상의" 시그널의 키워드가 "바지"
카테고리의 동명 상품과 우연히 일치해 순위 변동이 잘못 합산될 수 있다.

**같은 날 발생한 형제 시그널의 시장 베이스라인 누수 방지**: `evaluate()`는
같은 `signal_date`에 발생한 '모든' 시그널이 매칭한 상품 집합을 먼저 한 번
모아 각 시그널의 `_market_baseline_change()` 호출에 공통으로 `exclude_products`로
전달한다. 이렇게 하지 않으면 같은 날 발생한 다른 시그널이 추천한(역시 급등한)
상품이 시장 코호트에 남아, 그 상승분이 "시장 전체 효과"로 잘못 흡수되어
`relative_day*_change`(순수 기여분)가 과소평가된다.

**`aggregate_stats(results)`**: `evaluate()` 결과를 카테고리별·점수대별(30~49/
50~79/80+)로 묶어 적중률 통계(`hit_rate`, `hit_or_partial_rate`, 표본 수)를
집계한다. 절대 기준(`overall`/`by_category`/`by_score_bucket`)과 상대성과 기준
(`overall_relative`/`by_category_relative`/`by_score_bucket_relative`)을 모두
제공한다. `md_actions.py`와 대시보드 백테스트 섹션은 절대 적중률을 참고용으로
병기하되, 의사결정 근거는 상대성과(시장효과 차감) 기준을 우선 사용한다 — 절대
적중률만 보면 시즌 동반상승을 카테고리/점수대 자체의 성과로 오인할 수 있기 때문이다.
**중요**: 적중률 통계(`aggregate_stats`/`keyword_hit_weights`)는 랭킹 이탈
(`day7_change_dropout=True`, `status="보류"`)을 분모에서 빼지 않고 **실패로
포함**시켜 집계한다. 이탈은 실질적으로 추천이 틀린 결과이므로, 단순히 표본에서
제외하면 적중률이 과대평가된다(예: 이탈 1건+적중 2건을 "보류라서 제외"하면
적중률 100%로 잘못 집계되지만, 이탈을 실패로 보면 66.7%다). `evaluate()`가
반환하는 원본 `status`/`relative_status` 필드 자체는 `보류`를 그대로 유지하며,
이 처리는 통계 집계 단계에서만 일어난다.

**`keyword_hit_weights(results, min_samples=2, max_weight=10.0)`**: 키워드
패턴별 과거 적중률(이탈=실패 포함)을 50% 기준점으로 -10~+10점 가중치로 환산한다.
표본이 `min_samples` 미만인 키워드는 제외(과신 방지). `main.py`에서
`timing_signal.detect()`의 `backtest_feedback` 인자로 전달되어 다음 시그널
점수에 자동 반영된다.

---

### 7. 오늘의 MD 액션 (`analyzers/md_actions.py`)

**목표**: 기획전 시그널/플랫폼 교차/날씨/리뷰 인사이트를 MD가 바로 실행할 수 있는
액션 카드로 요약한다. `build(signals, weather, cross_platform, reviewed_entries,
limit=3, backtest_stats=None)` — 기존 시그니처와 반환 키(`title`/`action`/
`deadline`/`confidence`/`evidence`/`source`)는 그대로 유지하며, 카드마다 다음
실무 디테일 필드를 추가한다.
- `checklist`: 오늘 바로 확인할 구체적 항목 리스트 (예: "무신사/29CM 상의 카테고리
  랭킹 TOP30에서 '린넨' 포함 상품 직접 검색·정렬 확인").
- `where_to_look`: 어떤 페이지/대시보드 섹션을 봐야 하는지.
- `decision_criteria`: 진행/보류를 가르는 구체적 점수 기준(예: "80점 이상이면
  3~5일 내 즉시 오픈 검토, 50~79점이면 1주일 내 추가 확인").
- `priority_reason`: 이 카드가 왜 이 우선순위(confidence)를 받았는지 — 주요 기여
  지표(`score_breakdown` 중 최대값) 및 `backtest_stats`(카테고리/점수대 적중률)를
  근거로 설명한다. 카테고리/점수대 적중률은 절대값(`hit_rate`)과 시장효과를 차감한
  상대성과(`*_relative`)를 함께 병기해, 시즌 동반상승을 키워드 자체 성과로 오인하지
  않도록 한다.

기존 limit·source 중복 제거(같은 source는 1개씩만 우선 선택) 동작은 그대로 유지된다.
동일 source 후보(예: 기획전 시그널이 여러 개)가 `limit`보다 많아도 confidence가
가장 높은 1건만 채택하며, 부족분을 채우기 위한 별도의 무조건 추가 루프가 없어
같은 source가 결과에 중복으로 다시 섞여 들어가지 않는다(고유 source 수가
`limit`보다 적으면 그만큼만 반환된다).

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
2. 오늘의 기획전 시그널 하이라이트 — `score_breakdown`(지표별 기여 점수, "점수 산출
   근거" 펼침 영역에 전체 항목이 실제로 렌더링됨), `score_range`(보강 지표 개수 기반
   점수 범위 휴리스틱, 통계적 신뢰구간 아님), `evidence_detail`/`next_checks`를 카드에 노출
   (입력에 해당 필드가 없어도 `.get` 기본값으로 안전하게 생략됨)
3. 무신사 랭킹 TOP 10 (카테고리별 탭, 순위변동 표시)
4. 신규 진입 상품 카드
5. 구글/네이버 트렌드 키워드 차트
6. 인스타 해시태그 인기순 목록
7. 가격대 분포 차트 (카테고리별)
8. 브랜드 트래킹 현황
9. 오늘의 MD 액션 — `checklist`/`where_to_look`/`decision_criteria`/`priority_reason` 노출
10. 과거 시그널 백테스트 — 절대 변화(`day3/day7_change`)와 시장효과를 차감한
    상대성과(`relative_day7_change`), 카테고리별·점수대별 적중률 통계(`aggregate_stats`)
11. 데이터 출처·분석 방법론(`_methodology_block`) — 점진적 계절 보정, 백테스트
    피드백 가중치, 상대성과 판정 기준을 설명

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

프로젝트 전용 **venv**(`.venv/`)에 설치해 사용한다. 시스템 python의 pip가 너무 낡아
(pyobjc 등) 네이티브 빌드가 실패하므로 venv에서 pip를 최신화한 뒤 설치한다.

```bash
cd ~/fashion-monitor
python3 -m venv .venv
.venv/bin/pip install -U pip wheel
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium        # 판매통계·기획전 크롤링용 브라우저
```

- `collectors/musinsa.py`는 무신사 **내부 JSON API**를 쓰므로 별도 HTML 파서 불필요.
- `analyzers/new_entry.py`의 상세페이지 HTML 수집은 **Scrapling** 우선(실제 브라우저
  지문으로 429·봇차단 완화), 미설치 환경에서는 자동으로 urllib 폴백한다.
- 실행 스크립트(`run_fashion_monitor.sh`/`run_sales_update.sh`)는 `.venv/bin/python`을
  사용하고, venv가 없으면 `/usr/bin/python3`으로 폴백한다(`PY` 변수). crontab은
  bash 스크립트를 호출하므로 별도 수정 불필요.

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
