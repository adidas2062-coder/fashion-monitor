"""
경쟁 브랜드 랭킹 추적기.

config.WATCH_BRANDS 목록에 있는 브랜드의 랭킹 내 상품 수,
최고 순위 상품, 전날 대비 변화를 분석한다.
"""

import logging
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def analyze(
    today: List[Dict],
    yesterday: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    관심 브랜드별 랭킹 현황 분석.

    Args:
        today:     오늘 수집된 무신사 상품 dict 목록.
        yesterday: 전날 데이터 (없으면 변화 비교 스킵).

    Returns:
        브랜드별 분석 dict 목록:
        {
          brand:            브랜드명,
          product_count:    랭킹 내 상품 수,
          best_rank:        최고 순위,
          best_product:     최고 순위 상품명,
          best_category:    최고 순위 카테고리,
          prev_count:       전날 상품 수 (없으면 None),
          count_change:     상품 수 변화 (없으면 None),
          new_entries:      신규 진입 상품 목록,
          dropouts:         이탈 상품 목록,
          products:         오늘 랭킹 내 전체 상품 목록,
          collected_at:     수집 일자,
        }
    """
    watch = [b.upper() for b in config.WATCH_BRANDS]

    # 브랜드명 대소문자 무관 매칭을 위해 upper 비교
    def _brand_match(item: Dict, target_upper: str) -> bool:
        return item.get("brand", "").upper() == target_upper

    # 어제 데이터 인덱스
    yesterday_brand_items: Dict[str, List[Dict]] = {}
    if yesterday:
        for item in yesterday:
            for brand_upper in watch:
                if _brand_match(item, brand_upper):
                    yesterday_brand_items.setdefault(brand_upper, []).append(item)

    collected_at = today[0]["collected_at"] if today else ""
    results: List[Dict] = []

    for brand_upper in watch:
        brand_original = next(
            (b for b in config.WATCH_BRANDS if b.upper() == brand_upper),
            brand_upper,
        )
        # URL 기준 중복 제거 (같은 상품이 세분류 여러 카테고리에 동시 진입 시)
        seen_urls: set = set()
        brand_items = []
        for i in sorted([x for x in today if _brand_match(x, brand_upper)],
                        key=lambda x: x.get("rank", 999)):
            url = i.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                brand_items.append(i)

        if not brand_items:
            # 랭킹 내 없음
            prev_items = yesterday_brand_items.get(brand_upper, [])
            dropouts = [i["product_name"] for i in prev_items]
            results.append({
                "brand":         brand_original,
                "product_count": 0,
                "best_rank":     None,
                "best_product":  None,
                "best_category": None,
                "prev_count":    len(prev_items) if yesterday else None,
                "count_change":  -len(prev_items) if yesterday and prev_items else None,
                "new_entries":   [],
                "dropouts":      dropouts,
                "products":      [],
                "collected_at":  collected_at,
            })
            continue

        best = min(brand_items, key=lambda x: x["rank"])
        prev_items = yesterday_brand_items.get(brand_upper, [])
        prev_names = {i["product_name"] for i in prev_items}
        today_names = {i["product_name"] for i in brand_items}

        count = len(brand_items)
        prev_count = len(prev_items) if yesterday else None
        count_change = (count - prev_count) if prev_count is not None else None

        results.append({
            "brand":         brand_original,
            "product_count": count,
            "best_rank":     best["rank"],
            "best_product":  best["product_name"],
            "best_category": best["category"],
            "prev_count":    prev_count,
            "count_change":  count_change,
            "new_entries":   [n for n in today_names if n not in prev_names],
            "dropouts":      [n for n in prev_names if n not in today_names],
            "products":      brand_items,
            "collected_at":  collected_at,
        })

        logger.info(
            "브랜드 [%s] 랭킹 내 %d개 | 최고 %d위(%s)",
            brand_original, count, best["rank"], best["category"],
        )

    # 랭킹 내 상품 수 내림차순 정렬
    results.sort(key=lambda x: (x["product_count"] == 0, -(x["product_count"] or 0)))
    logger.info("브랜드 트래킹 완료: 총 %d개 브랜드", len(results))
    return results
