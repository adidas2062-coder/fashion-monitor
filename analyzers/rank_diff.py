"""
전날 대비 순위 변동 분석기.

오늘 수집한 무신사 랭킹 데이터와 직전 수집일 데이터를 비교해
상승/하락/신규/이탈 상품을 판별한다.

직전 데이터 소스: 로컬 스냅샷 또는 노션 DB에서 주입.
노션 연동 전에도 단독으로 사용 가능하도록 순수 데이터 변환 함수로 구현.
"""

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _key(item: Dict) -> Tuple[str, str, str]:
    """상품 동일성 판단 기준: (기간, 카테고리, 상품명)."""
    return (
        item.get("period", "1일"),
        item.get("category", ""),
        item.get("product_name", ""),
    )


def _product_key(item: Dict) -> str:
    """카테고리와 무관한 상품 식별자. URL이 없으면 상품명을 사용한다."""
    return item.get("url") or item.get("product_name", "")


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def analyze(today: List[Dict], yesterday: List[Dict]) -> Dict:
    """
    오늘 랭킹과 직전 수집일 랭킹을 비교해 변동 정보를 반환한다.

    Args:
        today:     오늘 수집된 무신사 상품 dict 목록 (collectors/musinsa.py 출력 형식).
        yesterday: 직전 수집일의 무신사 상품 dict 목록 (동일 형식).

    Returns:
        {
          "items":       오늘 상품 목록에 rank_change 필드 추가된 버전,
          "top_risers":  상승 TOP 5,
          "top_fallers": 하락 TOP 5,
          "new_entries": 신규 진입 상품 목록,
          "dropouts":    이탈 상품 목록,
          "summary":     카테고리별 요약 문자열,
        }
    """
    baseline_available = bool(yesterday)
    baseline_periods = {
        item.get("period", "1일") for item in yesterday
    }

    # 직전 수집일 데이터를 (카테고리, 상품명) → 순위 맵으로 변환
    yesterday_map: Dict[Tuple, int] = {_key(item): item["rank"] for item in yesterday}
    today_keys = {_key(item) for item in today}
    yesterday_product_keys = {
        _product_key(item) for item in yesterday if _product_key(item)
    }
    today_product_keys = {
        _product_key(item) for item in today if _product_key(item)
    }

    enriched: List[Dict] = []
    for item in today:
        k = _key(item)
        comparison_available = item.get("period", "1일") in baseline_periods
        yesterday_rank = yesterday_map.get(k)
        if yesterday_rank is None:
            rank_change = None
        else:
            rank_change = yesterday_rank - item["rank"]  # 양수=상승
        enriched.append({
            **item,
            "rank_change": rank_change,
            "comparison_available": comparison_available,
        })

    # 비교 기준이 없는 첫 실행에서는 오늘 전체를 신규로 오판하지 않는다.
    new_by_product: Dict[str, Dict] = {}
    if baseline_available:
        for item in enriched:
            product_key = _product_key(item)
            if (
                item["comparison_available"]
                and product_key
                and product_key not in yesterday_product_keys
            ):
                existing = new_by_product.get(product_key)
                if not existing or item.get("rank", 999) < existing.get("rank", 999):
                    new_by_product[product_key] = item
    new_entries = sorted(
        new_by_product.values(), key=lambda item: item.get("rank", 999)
    )

    # 이탈: 직전 수집일에는 있었지만 오늘 없는 상품
    dropout_by_product: Dict[str, Dict] = {}
    for item in yesterday:
        product_key = _product_key(item)
        if product_key and product_key not in today_product_keys:
            existing = dropout_by_product.get(product_key)
            if not existing or item.get("rank", 999) < existing.get("rank", 999):
                dropout_by_product[product_key] = item
    dropouts = sorted(
        dropout_by_product.values(), key=lambda item: item.get("rank", 999)
    )

    # 순위 변동 랭킹 (신규 제외)
    changed = [
        i for i in enriched
        if i["comparison_available"] and i["rank_change"] is not None
    ]
    top_risers  = sorted(changed, key=lambda x: x["rank_change"], reverse=True)[:5]
    top_fallers = sorted(changed, key=lambda x: x["rank_change"])[:5]

    # 카테고리별 요약
    summary_lines: List[str] = []
    cats = dict.fromkeys(i["category"] for i in enriched)
    for cat in cats:
        cat_items = [i for i in enriched if i["category"] == cat]
        new_cnt = (
            sum(
                1 for i in cat_items
                if i["comparison_available"] and i["rank_change"] is None
            )
            if baseline_available else 0
        )
        rise_cnt = sum(1 for i in cat_items if i["rank_change"] and i["rank_change"] > 0)
        fall_cnt = sum(1 for i in cat_items if i["rank_change"] and i["rank_change"] < 0)
        summary_lines.append(
            f"[{cat}] 신규:{new_cnt} 상승:{rise_cnt} 하락:{fall_cnt}"
        )

    result = {
        "items":       enriched,
        "top_risers":  top_risers,
        "top_fallers": top_fallers,
        "new_entries": new_entries,
        "dropouts":    dropouts,
        "summary":     " | ".join(summary_lines),
        "baseline_available": baseline_available,
    }

    logger.info(
        "순위 변동 분석 완료 — 신규:%d 이탈:%d 상승TOP:%s 하락TOP:%s",
        len(new_entries),
        len(dropouts),
        [f"{i['product_name'][:10]}(+{i['rank_change']})" for i in top_risers[:3]],
        [f"{i['product_name'][:10]}({i['rank_change']})"  for i in top_fallers[:3]],
    )
    return result
