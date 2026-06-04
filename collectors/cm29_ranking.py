"""
29CM 남성 베스트 랭킹 수집기.

recommend-api.29cm.co.kr 의 /api/v4/best/items 엔드포인트를 사용해
남성 의류 카테고리별 베스트 TOP 30을 수집한다.
"""

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

_BASE_URL = "https://recommend-api.29cm.co.kr/api/v4/best/items"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.29cm.co.kr/best-items",
    "Origin": "https://www.29cm.co.kr",
}

_RETRY_MAX   = 3
_RETRY_DELAY = 3.0

# 남성 카테고리 코드 (display-bff-api 기반)
_MEN_CATEGORIES = {
    "남성_전체":   "272100100",
    "남성_상의":   "272103100",
    "남성_하의":   "272104100",
    "남성_아우터": "272102100",
    "남성_니트":   "272110100",
    "남성_셋업":   "272112100",
}



def _kst_today() -> str:
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")

def _fetch(category_code: str, limit: int = 30, period_sort: str = "NOW") -> Optional[List[Dict]]:
    """단일 카테고리 베스트 아이템 수집."""
    params = (
        f"categoryList={category_code}"
        f"&periodSort={period_sort}"
        f"&gender="
        f"&limit={limit}"
        f"&offset=0"
    )
    url = f"{_BASE_URL}?{params}"

    for attempt in range(1, _RETRY_MAX + 1):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", {}).get("content", [])
        except Exception as exc:
            logger.warning("29CM API 실패 (시도 %d/%d) [%s]: %s",
                           attempt, _RETRY_MAX, category_code, exc)
            if attempt < _RETRY_MAX:
                time.sleep(_RETRY_DELAY)
    return None


def _parse(raw: List[Dict], category_name: str, period: str) -> List[Dict]:
    """API 응답 → 정규화된 상품 dict 목록."""
    collected_at = _kst_today()
    results = []
    for rank, item in enumerate(raw, 1):
        sale_price     = item.get("lastSalePrice") or item.get("consumerPrice") or 0
        original_price = item.get("consumerPrice") or sale_price
        discount_rate  = item.get("lastSalePercent") or 0
        results.append({
            "rank":          rank,
            "period":        period,
            "category":      category_name,
            "platform":      "29CM",
            "item_no":       item.get("itemNo"),
            "product_name":  item.get("itemName", ""),
            "brand":         item.get("frontBrandNameKor", ""),
            "brand_eng":     item.get("frontBrandNameEng", ""),
            "price":         sale_price,
            "original_price": original_price,
            "discount_rate": discount_rate,
            "review_count":  item.get("reviewCount", 0),
            "review_score":  item.get("reviewAveragePoint", 0.0),
            "is_sold_out":   item.get("isSoldOut", False),
            "url":           f"https://www.29cm.co.kr/product/detail?itemNo={item.get('itemNo','')}",
            "collected_at":  collected_at,
        })
    return results


def collect(
    categories: Optional[Dict[str, str]] = None,
    period_sort: str = "NOW",
    top_n: int = 30,
) -> List[Dict]:
    """
    29CM 남성 카테고리별 베스트 랭킹 수집.

    Args:
        categories:   {카테고리명: 카테고리코드} dict. None이면 _MEN_CATEGORIES 사용.
        period_sort:  "NOW"(실시간) | "DAILY"(일간) | "WEEKLY"(주간) | "MONTHLY"(월간)
        top_n:        카테고리별 수집 건수.

    Returns:
        카테고리·순위 순으로 정렬된 상품 목록.
    """
    categories = categories or _MEN_CATEGORIES
    period_label = {"NOW": "실시간", "DAILY": "1일", "WEEKLY": "주간", "MONTHLY": "월간"}.get(period_sort, period_sort)

    results: List[Dict] = []
    for i, (cat_name, cat_code) in enumerate(categories.items()):
        if i > 0:
            time.sleep(config.REQUEST_DELAY)

        logger.info("29CM [%s/%s] 수집 시작 (TOP %d)", cat_name, period_label, top_n)
        raw = _fetch(cat_code, limit=top_n, period_sort=period_sort)
        if raw is None:
            logger.error("29CM [%s] 수집 실패", cat_name)
            continue

        items = _parse(raw, cat_name, period_label)
        results.extend(items)
        logger.info("29CM [%s/%s] 수집 완료: %d건", cat_name, period_label, len(items))

    logger.info("29CM 전체 수집 완료: 총 %d건 (%d카테고리)", len(results), len(categories))
    return results
