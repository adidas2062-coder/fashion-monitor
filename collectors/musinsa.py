"""
무신사 카테고리별 실시간 랭킹 수집기.

Musinsa 내부 API(api.musinsa.com)를 사용해 상의/아우터/바지 TOP N을 수집한다.
robots.txt 준수를 위해 요청 간 딜레이를 적용하고, 실패 시 최대 3회 재시도한다.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────

_RANKING_API = (
    "https://api.musinsa.com/api2/hm/web/v5/pans/ranking/sections/200"
    "?storeCode=musinsa&categoryCode={category_code}&contentsId="
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.musinsa.com/",
}

_MAX_RETRY = 3
_RETRY_DELAY = 3.0  # 재시도 전 대기 (초)


# ── 내부 함수 ─────────────────────────────────────────────────────────────────

def _fetch_json(url: str) -> dict:
    """단순 GET 요청 → JSON dict 반환. 실패 시 예외를 그대로 전파."""
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_with_retry(url: str) -> Optional[Dict]:
    """최대 _MAX_RETRY 회 재시도. 모두 실패하면 None 반환."""
    for attempt in range(1, _MAX_RETRY + 1):
        try:
            return _fetch_json(url)
        except (urllib.error.URLError, json.JSONDecodeError, Exception) as exc:
            logger.warning("무신사 API 요청 실패 (시도 %d/%d): %s", attempt, _MAX_RETRY, exc)
            if attempt < _MAX_RETRY:
                time.sleep(_RETRY_DELAY)
    return None


def _parse_items(raw_data: Dict, category_name: str, top_n: int) -> List[Dict]:
    """API 응답에서 상품 리스트를 파싱해 정규화된 dict 목록으로 반환."""
    modules = raw_data.get("data", {}).get("modules", [])
    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    items: List[Dict] = []
    for module in modules:
        if module.get("type") != "MULTICOLUMN":
            continue
        for item in module.get("items", []):
            rank = item.get("image", {}).get("rank")
            if rank is None or rank > top_n:
                continue
            info = item.get("info", {})
            url = item.get("onClick", {}).get("url", "")
            items.append({
                "rank": rank,
                "category": category_name,
                "product_name": info.get("productName", ""),
                "brand": info.get("brandName", ""),
                "price": info.get("finalPrice", 0),
                "discount_rate": info.get("discountRatio", 0),
                "is_sold_out": info.get("isSoldOut", False),
                "url": url,
                "collected_at": collected_at,
            })

    items.sort(key=lambda x: x["rank"])
    return items


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def fetch_category(category_name: str, category_code: str, top_n: int) -> List[Dict]:
    """
    단일 카테고리 랭킹 수집.

    Returns:
        rank 오름차순 정렬된 상품 dict 목록. 수집 실패 시 빈 리스트.
    """
    url = _RANKING_API.format(category_code=category_code)
    logger.info("무신사 [%s] 랭킹 수집 시작 (TOP %d)", category_name, top_n)

    raw = _fetch_with_retry(url)
    if raw is None:
        logger.error("무신사 [%s] 수집 실패 — 재시도 초과", category_name)
        return []

    items = _parse_items(raw, category_name, top_n)
    logger.info("무신사 [%s] 수집 완료: %d건", category_name, len(items))
    return items


def collect() -> List[Dict]:
    """
    config에 정의된 전체 카테고리 랭킹 수집.

    Returns:
        전체 카테고리 통합 상품 목록 (카테고리별 순서 유지).
    """
    top_n = config.MUSINSA_TOP_N
    categories = config.MUSINSA_CATEGORIES  # {"상의": "001", "아우터": "002", "바지": "003"}
    delay = config.REQUEST_DELAY

    results: List[Dict] = []
    for i, (name, code) in enumerate(categories.items()):
        if i > 0:
            time.sleep(delay)
        items = fetch_category(name, code, top_n)
        results.extend(items)

    logger.info("무신사 전체 수집 완료: 총 %d건", len(results))
    return results
