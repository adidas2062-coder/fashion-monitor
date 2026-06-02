# config.example.py — API 키 입력 템플릿
# 이 파일을 복사해서 config.py 로 만든 후 실제 값을 입력하세요.
# config.py 는 .gitignore 에 포함되어 있어 커밋되지 않습니다.
#
#   cp config.example.py config.py
#   vi config.py   # 아래 빈 문자열에 실제 키를 입력

# ── 네이버 데이터랩 API ──────────────────────────────────────────────────────
# https://developers.naver.com/apps/ 에서 앱 등록 후 발급
NAVER_CLIENT_ID = ""
NAVER_CLIENT_SECRET = ""

# ── 노션 API ─────────────────────────────────────────────────────────────────
# https://www.notion.so/my-integrations 에서 인테그레이션 생성 후 발급
NOTION_API_KEY = ""

# 노션 DB ID (각 DB 페이지 URL에서 복사)
# 예) https://www.notion.so/<workspace>/<DB_ID>?v=...
NOTION_RANKING_DB_ID = ""       # 무신사 랭킹 DB
NOTION_TREND_DB_ID = ""         # 트렌드 키워드 DB
NOTION_NEW_ENTRY_DB_ID = ""     # 신규진입상품 DB
NOTION_BRAND_DB_ID = ""         # 브랜드트래킹 DB
NOTION_SIGNAL_DB_ID = ""        # 기획전시그널 DB

# ── 카카오톡 나에게 보내기 ────────────────────────────────────────────────────
# https://developers.kakao.com/ 앱 등록 → 내 애플리케이션 → REST API 키
# 토큰 발급: https://developers.kakao.com/docs/latest/ko/kakaologin/rest-api
KAKAO_ACCESS_TOKEN = ""

# ── 인스타그램 (선택사항) ─────────────────────────────────────────────────────
# 로그인 없이도 공개 해시태그 수집 가능. 실패 시 자동 스킵됨.
INSTAGRAM_USERNAME = ""
INSTAGRAM_PASSWORD = ""

# ── 수집 설정 ────────────────────────────────────────────────────────────────
MUSINSA_TOP_N = 30          # 카테고리별 상위 몇 위까지 수집
REQUEST_DELAY = 1.5         # 무신사 요청 간 딜레이 (초) — 1.5 이상 유지

# ── 출력 경로 ────────────────────────────────────────────────────────────────
DASHBOARD_OUTPUT_PATH = "data/dashboard.html"
REPORT_OUTPUT_DIR = "data/reports/"
LOG_PATH = "logs/run.log"

# ── 관심 브랜드 (브랜드 트래킹용) ────────────────────────────────────────────
WATCH_BRANDS = [
    "MATIN KIM",
    "COVERNAT",
    "KIRSH",
    "ADER ERROR",
    "ROMANTIC CROWN",
    "CARHARTT WIP",
    # 추가 브랜드를 여기에 입력
]

# ── 기획전 시그널 감지 임계값 ─────────────────────────────────────────────────
TREND_SURGE_THRESHOLD = 20  # 트렌드 상승률 (%) — 이 값 이상이면 시그널
RANK_SURGE_THRESHOLD = 5    # 랭킹 상승 계단 수 — 이 값 이상이면 시그널

# ── 구글 트렌드 모니터링 키워드 ──────────────────────────────────────────────
FASHION_KEYWORDS = [
    "무신사", "오버핏", "데님재킷", "린넨셔츠", "슬랙스",
    "캐주얼아우터", "니트조끼", "와이드팬츠", "반팔티", "후드집업",
]

# ── 인스타그램 모니터링 해시태그 ─────────────────────────────────────────────
INSTAGRAM_TAGS = [
    "무신사", "오늘의코디", "데일리룩", "패션", "ootd",
    "아우터", "데님", "슬랙스", "오버핏", "스트릿패션",
]

# ── 무신사 카테고리 코드 ──────────────────────────────────────────────────────
MUSINSA_CATEGORIES = {
    "상의": "001",
    "아우터": "002",
    "바지": "003",
}
