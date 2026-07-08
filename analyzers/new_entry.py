"""
신규 진입 상품 상세 정보 수집기.

rank_diff.analyze()가 반환한 new_entries 목록을 받아
각 상품 URL로 무신사 상세 페이지를 추가 스크래핑한다.

수집 항목: 소재(material), 핏(fit_type), 주요 색상(colors),
           리뷰 수(review_count), 평점(rating).
"""

import json
import logging
import re
import time
import urllib.request
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

# Scrapling이 설치돼 있으면(.venv 등) 실제 브라우저 지문으로 요청해
# 무신사 봇 차단(429)을 완화한다. 없으면(시스템 python cron 등) urllib로 폴백해
# 기존 동작을 그대로 유지한다 — 어느 환경에서도 import 실패로 죽지 않게 한다.
try:
    from scrapling.fetchers import Fetcher as _ScraplingFetcher
    _HAS_SCRAPLING = True
except Exception:  # pragma: no cover - 설치 안 된 환경
    _ScraplingFetcher = None
    _HAS_SCRAPLING = False

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": "https://www.musinsa.com/",
}

_RETRY_MAX   = 3
_RETRY_DELAY = 3.0

# 핏 키워드 → 정규화 맵
_FIT_KEYWORDS = {
    "오버핏": "오버핏", "oversized": "오버핏", "over fit": "오버핏",
    "슬림핏": "슬림핏", "slim fit": "슬림핏", "slim": "슬림핏",
    "레귤러": "레귤러",  "regular": "레귤러",
    "와이드":  "와이드",  "wide": "와이드",
    "루즈":   "루즈핏",  "loose": "루즈핏",
    "크롭":   "크롭",    "crop": "크롭",
}

# 영문 색상 토큰 → 한글. 무신사 옵션 API 색상칩(name)이 'BLK0_BLACK' 처럼 오므로
# '_' 뒤 영문 토큰을 뽑아 매핑한다. (알 수 없는 코드는 버려서 쓰레기값 방지)
_COLOR_MAP = {
    "BLACK": "블랙", "WHITE": "화이트", "IVORY": "아이보리", "CREAM": "크림",
    "NAVY": "네이비", "BLUE": "블루", "SKY": "스카이", "DENIM": "데님",
    "RED": "레드", "PINK": "핑크", "CORAL": "코랄", "BURGUNDY": "버건디",
    "GREEN": "그린", "OLIVE": "올리브", "MINT": "민트", "KHAKI": "카키",
    "BEIGE": "베이지", "BROWN": "브라운", "CAMEL": "카멜", "TAN": "탄",
    "GRAY": "그레이", "GREY": "그레이", "CHARCOAL": "차콜", "SILVER": "실버",
    "PURPLE": "퍼플", "LAVENDER": "라벤더", "VIOLET": "바이올렛",
    "YELLOW": "옐로우", "ORANGE": "오렌지", "GOLD": "골드", "MULTI": "멀티",
}

# 상품명에서 찾을 한글 색상 단어(폴백용)
_KO_COLORS = [
    "블랙", "화이트", "아이보리", "크림", "네이비", "블루", "스카이", "데님",
    "레드", "핑크", "코랄", "버건디", "그린", "올리브", "민트", "카키",
    "베이지", "브라운", "카멜", "그레이", "차콜", "실버", "퍼플", "라벤더",
    "옐로우", "오렌지", "골드", "멀티", "연청", "중청", "진청", "흑청",
]

# 소재명(비율)로 추출할 대표 소재 사전
_MATERIALS = [
    "폴리에스터", "폴리에스테르", "나일론", "코튼", "면", "울", "린넨", "레이온",
    "스판덱스", "폴리우레탄", "아크릴", "캐시미어", "텐셀", "모달", "비스코스",
    "알파카", "실크", "데님", "가죽", "스웨이드", "앙고라",
]


def _normalize_color(raw: str) -> str:
    """옵션 색상칩 name('BLK0_BLACK')이나 영문/한글 색을 한글 색상으로 정규화.

    알 수 없는 영문 코드(예: 'BLK0')는 쓰레기값을 남기지 않도록 빈 문자열 반환.
    """
    if not raw:
        return ""
    token = raw.split("_")[-1] if "_" in raw else raw       # BLK0_BLACK → BLACK
    if re.search(r"[가-힣]", token):                          # 이미 한글이면 그대로
        return token
    key = re.sub(r"[^A-Za-z]", "", token).upper()
    return _COLOR_MAP.get(key, "")


def _extract_colors_from_options(options_json: Optional[Dict]) -> List[str]:
    """무신사 옵션 API 응답에서 색상칩(COLOR_CHIP) 값을 한글 색상 목록으로 추출."""
    if not options_json:
        return []
    colors: List[str] = []
    data = options_json.get("data", {}) or {}
    for group_key in ("basic", "additional"):
        for node in data.get(group_key, []) or []:
            if node.get("displayType") != "COLOR_CHIP":
                continue
            for ov in node.get("optionValues", []) or []:
                c = _normalize_color(ov.get("name", ""))
                if c and c not in colors:
                    colors.append(c)
    return colors[:5]


def _colors_from_name(name: str) -> List[str]:
    """상품명에서 한글 색상 단어를 추출(옵션 API 실패 시 폴백)."""
    found: List[str] = []
    for c in _KO_COLORS:
        if c in (name or "") and c not in found:
            found.append(c)
    return found[:5]


def _material_from_html(html: str) -> str:
    """상세 HTML에서 대표 소재를 '소재(비율)' 형태로 추출. 못 찾으면 빈 문자열."""
    if not html:
        return ""
    # 1) '겉감:폴리에스터(100)' 우선 (색상코드 접두 [BLK0] 등은 무시)
    m = re.search(r"겉감[:：]?\s*([가-힣A-Za-z]+)\s*\((\d+)\)", html)
    if m and any(mat in m.group(1) for mat in _MATERIALS):
        return f"{m.group(1)}({m.group(2)})"
    # 2) 일반 '소재(비율)' — 사전에 있는 소재만
    for mat in _MATERIALS:
        m = re.search(re.escape(mat) + r"\s*\((\d+)\)", html)
        if m:
            return f"{mat}({m.group(1)})"
    return ""


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _fetch_html_scrapling(url: str) -> Optional[str]:
    """Scrapling Fetcher로 HTML 반환. 실패 시 None (호출부가 urllib로 폴백)."""
    try:
        page = _ScraplingFetcher.get(url, stealthy_headers=True, timeout=15)
    except Exception as exc:
        logger.warning("Scrapling 요청 실패 %s: %s", url, exc)
        return None
    if getattr(page, "status", 200) >= 400:
        logger.warning("Scrapling 응답 상태 %s: %s", page.status, url)
        return None
    return getattr(page, "body", None) or getattr(page, "html_content", None)


def _fetch_html_urllib(url: str) -> Optional[str]:
    """urllib로 HTML 반환. 실패 시 None."""
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_html(url: str) -> Optional[str]:
    """상세 페이지 HTML 반환. Scrapling 우선, 실패 시 urllib 폴백. 최종 실패 시 None."""
    for attempt in range(1, _RETRY_MAX + 1):
        try:
            if _HAS_SCRAPLING:
                html = _fetch_html_scrapling(url)
                if html is not None:
                    return html
                # Scrapling이 None이면 같은 시도 안에서 urllib로 폴백
            return _fetch_html_urllib(url)
        except Exception as exc:
            logger.warning("상세 페이지 요청 실패 (시도 %d/%d) %s: %s", attempt, _RETRY_MAX, url, exc)
            if attempt < _RETRY_MAX:
                time.sleep(_RETRY_DELAY)
    return None


_OPTIONS_API = "https://goods-detail.musinsa.com/api2/goods/{goods_no}/options"


def _goods_no_from_url(url: str) -> str:
    """상품 URL에서 goodsNo 추출. 예: .../products/4693117 → '4693117'."""
    m = re.search(r"/products/(\d+)", url or "")
    return m.group(1) if m else ""


def _fetch_options(goods_no: str) -> Optional[Dict]:
    """무신사 옵션 API(JSON) 반환. 실패 시 None (색상은 상품명 폴백으로 처리)."""
    if not goods_no:
        return None
    url = _OPTIONS_API.format(goods_no=goods_no)
    try:
        html = _fetch_html(url)  # Scrapling/urllib 폴백 재사용
        if not html:
            return None
        # 응답이 <html><body>{...}</body></html> 로 감싸 오는 경우가 있어 JSON만 추출
        m = re.search(r"\{.*\}", html, re.DOTALL)
        return json.loads(m.group(0)) if m else None
    except Exception as exc:
        logger.warning("옵션 API 요청/파싱 실패 %s: %s", goods_no, exc)
        return None


def _extract_next_data(html: str) -> Optional[Dict]:
    """Next.js __NEXT_DATA__ JSON 추출."""
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _parse_detail(html: str, name: str = "", options_json: Optional[Dict] = None) -> Dict:
    """HTML에서 상세 정보 파싱 → 부분 결과 dict.

    Args:
        name:         상품명 (색상 추출 폴백에 사용).
        options_json: 무신사 옵션 API 응답 (색상칩 추출용, 선택).
    """
    detail: Dict = {
        "material":     "",
        "fit_type":     "",
        "colors":       [],
        "review_count": 0,
        "rating":       0.0,
    }

    # ── Next.js 구조화 데이터 우선 시도 ──────────────────────────────────────
    nd = _extract_next_data(html)
    if nd:
        # 실제 경로: props.pageProps.meta.data
        meta_data = (
            nd.get("props", {})
              .get("pageProps", {})
              .get("meta", {})
              .get("data", {})
        )

        # 리뷰 수, 평점
        review_obj = meta_data.get("goodsReview", {})
        if review_obj.get("totalCount") is not None:
            detail["review_count"] = int(review_obj["totalCount"])
        if review_obj.get("satisfactionScore") is not None:
            detail["rating"] = float(review_obj["satisfactionScore"])

        # 핏 / 소재 — goodsMaterial.materials 배열
        materials = meta_data.get("goodsMaterial", {}).get("materials", [])
        for mat_group in materials:
            group_name = mat_group.get("name", "")
            selected = [i["name"] for i in mat_group.get("items", []) if i.get("isSelected")]
            if not selected:
                continue
            if group_name == "핏":
                detail["fit_type"] = selected[0]
            elif group_name in ("소재", "원단"):
                detail["material"] = selected[0]

    # ── 색상: 옵션 API 색상칩 우선, 실패 시 상품명에서 추출 ──────────────────────
    # (무신사 개편으로 예전 goodsOption 경로가 사라져 항상 빈 값이던 문제 해결)
    detail["colors"] = _extract_colors_from_options(options_json) or _colors_from_name(name)

    # ── 소재: goodsMaterial(구버전)이 비면 상세 HTML에서 '소재(비율)' 추출 ────────
    if not detail["material"]:
        detail["material"] = _material_from_html(html)

    # ── HTML 정규식 폴백 ──────────────────────────────────────────────────────

    # 리뷰 수
    if detail["review_count"] == 0:
        m = re.search(r'"totalCount"\s*:\s*(\d+)', html)
        if m:
            detail["review_count"] = int(m.group(1))

    # 평점
    if detail["rating"] == 0.0:
        m = re.search(r'"satisfactionScore"\s*:\s*([\d.]+)', html)
        if m:
            detail["rating"] = float(m.group(1))

    # 핏 — 상품명·상품 설명에서 핏 키워드 탐색 (최후 폴백)
    if not detail["fit_type"]:
        text_lower = html.lower()
        for kw, normalized in _FIT_KEYWORDS.items():
            if kw in text_lower:
                detail["fit_type"] = normalized
                break

    return detail


def _dig(obj, key: str):
    """중첩 dict/list에서 첫 번째 key 값을 DFS로 탐색."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _dig(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _dig(item, key)
            if found is not None:
                return found
    return None


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def enrich(new_entries: List[Dict]) -> List[Dict]:
    """
    신규 진입 상품 목록에 상세 정보를 추가해 반환한다.

    Args:
        new_entries: rank_diff.analyze() 결과의 new_entries 목록.

    Returns:
        각 상품 dict에 material / fit_type / colors / review_count / rating 추가.
    """
    if not new_entries:
        return []

    enriched: List[Dict] = []
    for i, item in enumerate(new_entries):
        if i > 0:
            time.sleep(config.REQUEST_DELAY * 2)   # 429 방지: 일반 딜레이의 2배

        url = item.get("url", "")
        if not url:
            enriched.append(item)
            continue

        logger.info("신규 진입 상세 수집: %s / %s", item.get("brand"), item.get("product_name", "")[:30])
        html = _fetch_html(url)
        if html is None:
            logger.warning("상세 페이지 수집 실패 — 기본값 사용: %s", url)
            enriched.append({**item, "material": "", "fit_type": "", "colors": [], "review_count": 0, "rating": 0.0})
            continue

        options_json = _fetch_options(_goods_no_from_url(url))
        detail = _parse_detail(html, name=item.get("product_name", ""), options_json=options_json)
        enriched.append({**item, **detail})
        logger.info(
            "  → 소재=%s 핏=%s 리뷰=%d 평점=%.1f 색상=%s",
            detail["material"] or "-",
            detail["fit_type"] or "-",
            detail["review_count"],
            detail["rating"],
            detail["colors"],
        )

    logger.info("신규 진입 상품 상세 수집 완료: %d건", len(enriched))
    return enriched
