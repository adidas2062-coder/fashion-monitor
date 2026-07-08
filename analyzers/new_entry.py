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


def _parse_detail(html: str) -> Dict:
    """HTML에서 상세 정보 파싱 → 부분 결과 dict."""
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

        # 색상 — 옵션 내 colorName 탐색
        colors_found: List[str] = []
        def _collect_colors(obj, depth=0):
            if depth > 6 or len(colors_found) >= 5:
                return
            if isinstance(obj, dict):
                if "colorName" in obj:
                    colors_found.append(obj["colorName"])
                for v in obj.values():
                    _collect_colors(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _collect_colors(item, depth + 1)
        _collect_colors(meta_data.get("goodsOption", {}))
        detail["colors"] = colors_found[:5]

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

        detail = _parse_detail(html)
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
