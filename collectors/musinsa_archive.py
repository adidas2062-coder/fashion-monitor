"""
무신사 월간 랭킹 아카이브 수집기.

공식 아카이브 API(/api2/dp/v1/ranking-archive/goods)를 사용해
특정 연월의 월간 랭킹 TOP 30을 수집한다.

주요 용도: 작년 동기 대비 YoY 비교
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

_GOODS_URL = "https://api.musinsa.com/api2/dp/v1/ranking-archive/goods"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.musinsa.com/ranking/archive",
}
_RETRY_MAX = 3
_RETRY_DELAY = 3.0

# 카테고리 코드 매핑 (archive API는 3자리 코드 사용)
_ARCHIVE_CATEGORIES = {
    "상의":  "001",
    "아우터": "002",
    "바지":  "003",
}


def _fetch(year_month: str, category_code: str) -> Optional[List[Dict]]:
    """단일 카테고리·월 아카이브 수집."""
    url = f"{_GOODS_URL}?yearMonth={year_month}&gf=A&category={category_code}"
    for attempt in range(1, _RETRY_MAX + 1):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("data", {}).get("list", [])
        except Exception as exc:
            logger.warning("아카이브 수집 실패 (시도 %d/%d) [%s/%s]: %s",
                           attempt, _RETRY_MAX, year_month, category_code, exc)
            if attempt < _RETRY_MAX:
                time.sleep(_RETRY_DELAY)
    return None


def collect(year_month: Optional[str] = None) -> List[Dict]:
    """
    월간 아카이브 랭킹 수집.

    Args:
        year_month: "YYYYMM" 형식. None이면 작년 같은 달.

    Returns:
        상의/아우터/바지 통합 상품 목록.
        각 항목: rank, category, product_name, brand, url, year_month
    """
    if year_month is None:
        today = datetime.now(timezone.utc)
        # 작년 같은 달
        year_month = f"{today.year - 1}{today.month:02d}"

    logger.info("무신사 아카이브 수집: %s", year_month)
    results: List[Dict] = []

    for i, (cat_name, cat_code) in enumerate(_ARCHIVE_CATEGORIES.items()):
        if i > 0:
            time.sleep(config.REQUEST_DELAY)

        goods = _fetch(year_month, cat_code)
        if goods is None:
            logger.error("아카이브 [%s/%s] 수집 실패", year_month, cat_name)
            continue

        for g in goods:
            results.append({
                "rank":          g.get("rank"),
                "category":      cat_name,
                "product_name":  g.get("goodsName", ""),
                "brand":         g.get("brandName", ""),
                "goods_no":      g.get("goodsNo"),
                "url":           f"https://www.musinsa.com/products/{g.get('goodsNo','')}",
                "year_month":    year_month,
                "memo":          g.get("rankAdditionalText", ""),
            })

    logger.info("아카이브 수집 완료: %s, 총 %d건", year_month, len(results))
    return results
