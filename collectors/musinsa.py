"""
무신사 카테고리별 랭킹 수집기.

Musinsa 내부 API(api.musinsa.com)를 사용해
1일 / 주간 / 월간 기간별로 상의·아우터·바지 세분류 TOP N을 수집한다.
실시간(REALTIME)은 수집하지 않는다.

요청 간 딜레이를 적용하고, 실패 시 최대 3회 재시도한다.
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

# sectionId=199 = ranking_cat (1일/주간/월간 기간 필터 지원)
# gf=M → 남성 필터
_RANKING_API = (
    "https://api.musinsa.com/api2/hm/web/v5/pans/ranking/sections/199"
    "?storeCode=musinsa&categoryCode={category_code}&contentsId=&period={period}&gf=M"
)

_PERIOD_LABELS = {
    "DAILY":   "1일",
    "WEEKLY":  "주간",
    "MONTHLY": "월간",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.musinsa.com/",
}

_MAX_RETRY   = 3
_RETRY_DELAY = 3.0


# ── 내부 함수 ─────────────────────────────────────────────────────────────────


def _kst_today() -> str:
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")

def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_with_retry(url: str) -> Optional[Dict]:
    for attempt in range(1, _MAX_RETRY + 1):
        try:
            return _fetch_json(url)
        except (urllib.error.URLError, json.JSONDecodeError, Exception) as exc:
            logger.warning("무신사 API 요청 실패 (시도 %d/%d): %s", attempt, _MAX_RETRY, exc)
            if attempt < _MAX_RETRY:
                time.sleep(_RETRY_DELAY)
    return None


def _parse_items(
    raw_data: Dict,
    category_name: str,
    period: str,
    top_n: int,
) -> List[Dict]:
    modules = raw_data.get("data", {}).get("modules", [])
    collected_at = _kst_today()
    period_label = _PERIOD_LABELS.get(period, period)

    items: List[Dict] = []
    for module in modules:
        if module.get("type") != "MULTICOLUMN":
            continue
        for item in module.get("items", []):
            rank = item.get("image", {}).get("rank")
            if rank is None or rank > top_n:
                continue
            info = item.get("info", {})
            url  = item.get("onClick", {}).get("url", "")
            items.append({
                "rank":          rank,
                "period":        period_label,       # "1일" / "주간" / "월간"
                "category":      category_name,
                "product_name":  info.get("productName", ""),
                "brand":         info.get("brandName", ""),
                "price":         info.get("finalPrice", 0),
                "discount_rate": info.get("discountRatio", 0),
                "is_sold_out":   info.get("isSoldOut", False),
                "url":           url,
                "collected_at":  collected_at,
            })

    items.sort(key=lambda x: x["rank"])
    return items


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def fetch_category(
    category_name: str,
    category_code: str,
    period: str,
    top_n: int,
) -> List[Dict]:
    """
    단일 카테고리 + 단일 기간 랭킹 수집.

    Args:
        period: "DAILY" | "WEEKLY" | "MONTHLY"
    """
    url = _RANKING_API.format(category_code=category_code, period=period)
    label = _PERIOD_LABELS.get(period, period)
    logger.info("무신사 [%s/%s] 수집 시작 (TOP %d)", category_name, label, top_n)

    raw = _fetch_with_retry(url)
    if raw is None:
        logger.error("무신사 [%s/%s] 수집 실패 — 재시도 초과", category_name, label)
        return []

    items = _parse_items(raw, category_name, period, top_n)
    logger.info("무신사 [%s/%s] 수집 완료: %d건", category_name, label, len(items))
    return items


def collect(
    periods: Optional[List[str]] = None,
    categories: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """
    config에 정의된 기간 × 카테고리 전체 수집.

    Args:
        periods:    수집 기간 목록. None이면 config.MUSINSA_PERIODS 사용.
        categories: 카테고리 dict. None이면 config.MUSINSA_CATEGORIES 사용.

    Returns:
        기간·카테고리 순서로 정렬된 통합 상품 목록.
        각 항목에 "period" 필드("1일"/"주간"/"월간") 포함.
    """
    periods    = periods    or config.MUSINSA_PERIODS
    categories = categories or config.MUSINSA_CATEGORIES
    top_n      = config.MUSINSA_TOP_N
    delay      = config.REQUEST_DELAY

    # REALTIME 은 수집하지 않음
    periods = [p for p in periods if p != "REALTIME"]

    results: List[Dict] = []
    total = len(periods) * len(categories)
    idx = 0
    for period in periods:
        for cat_name, cat_code in categories.items():
            if idx > 0:
                time.sleep(delay)
            items = fetch_category(cat_name, cat_code, period, top_n)
            results.extend(items)
            idx += 1

    logger.info(
        "무신사 전체 수집 완료: 총 %d건 (%d기간 × %d카테고리)",
        len(results), len(periods), len(categories),
    )
    return results
