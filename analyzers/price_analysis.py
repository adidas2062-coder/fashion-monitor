"""
가격대 분포 분석기.

무신사 랭킹 상위 30위 상품의 가격 분포로
"요즘 잘 팔리는 가격대" 인사이트를 추출한다.
"""

import logging
import statistics
from collections import Counter
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 가격 구간 정의 (상한값, 라벨)
_PRICE_BRACKETS: List[Tuple[int, str]] = [
    (30_000,  "3만원 미만"),
    (50_000,  "3~5만원"),
    (100_000, "5~10만원"),
    (200_000, "10~20만원"),
    (float("inf"), "20만원 이상"),
]


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _bracket_label(price: int) -> str:
    for ceiling, label in _PRICE_BRACKETS:
        if price < ceiling:
            return label
    return "20만원 이상"


def _stats(prices: List[int]) -> Dict:
    if not prices:
        return {"avg": 0, "median": 0, "mode_bracket": "-", "count": 0}
    avg    = round(statistics.mean(prices))
    median = round(statistics.median(prices))
    bracket_counts = Counter(_bracket_label(p) for p in prices)
    mode_bracket = bracket_counts.most_common(1)[0][0]
    return {
        "avg":          avg,
        "median":       median,
        "mode_bracket": mode_bracket,
        "count":        len(prices),
        "bracket_dist": dict(bracket_counts),
    }


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def analyze(
    today: List[Dict],
    yesterday: Optional[List[Dict]] = None,
) -> Dict:
    """
    오늘 랭킹 데이터의 가격 분포를 분석한다.

    Args:
        today:     오늘 수집된 무신사 상품 dict 목록.
        yesterday: 전날 데이터 (전주 평균가 비교용, 없으면 스킵).

    Returns:
        {
          "by_category":   카테고리별 통계 dict,
          "overall":       전체 통계,
          "top_discounts": 할인율 TOP 5,
          "avg_changes":   전날 대비 평균가 변화 (yesterday 있을 때만),
          "summary":       요약 문자열,
        }
    """
    # 카테고리별 가격 수집
    cat_prices: Dict[str, List[int]] = {}
    for item in today:
        cat = item.get("category", "기타")
        cat_prices.setdefault(cat, []).append(item.get("price", 0))

    # 전날 평균가
    yesterday_avgs: Dict[str, float] = {}
    if yesterday:
        cat_prev: Dict[str, List[int]] = {}
        for item in yesterday:
            cat = item.get("category", "기타")
            cat_prev.setdefault(cat, []).append(item.get("price", 0))
        yesterday_avgs = {
            cat: round(statistics.mean(prices))
            for cat, prices in cat_prev.items() if prices
        }

    by_category: Dict[str, Dict] = {}
    summary_parts: List[str] = []
    for cat, prices in cat_prices.items():
        st = _stats(prices)
        prev_avg = yesterday_avgs.get(cat, 0)
        avg_change = st["avg"] - prev_avg if prev_avg else None
        by_category[cat] = {**st, "avg_change": avg_change}
        change_txt = (
            f" 전일비{'+' if avg_change >= 0 else ''}{avg_change:,}원"
            if avg_change is not None
            else ""
        )
        summary_parts.append(
            f"[{cat}] 평균{st['avg']:,}원 | 최빈가격대:{st['mode_bracket']}"
            f"({st['bracket_dist'].get(st['mode_bracket'],0)}개){change_txt}"
        )

    # 전체 통계
    all_prices = [item.get("price", 0) for item in today]
    overall = _stats(all_prices)

    # 할인율 TOP 5
    top_discounts = sorted(
        [i for i in today if i.get("discount_rate", 0) > 0],
        key=lambda x: x["discount_rate"],
        reverse=True,
    )[:5]

    result = {
        "by_category":   by_category,
        "overall":       overall,
        "top_discounts": top_discounts,
        "avg_changes":   {
            cat: data["avg_change"]
            for cat, data in by_category.items()
            if data["avg_change"] is not None
        },
        "summary": "\n".join(summary_parts),
    }

    logger.info("가격 분포 분석 완료:\n%s", result["summary"])
    return result
