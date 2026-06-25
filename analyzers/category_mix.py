"""무신사 카테고리 통합("전체 베스트") 랭킹에서 실제 카테고리 비중을 계산한다.

무신사 카테고리별 랭킹 API(categoryCode=000, gf=A)로 상의·아우터·바지를 안 가린
진짜 통합 TOP N을 받아올 수 있지만, 그 응답 자체에는 각 상품이 어느 대분류인지
표시되지 않는다. 그래서 이미 수집한 카테고리별 랭킹(상의_전체/아우터_전체/
바지_전체 등)에서 URL→대분류 매핑표를 만들어, 통합 랭킹 속 상품을 역으로
매칭해 실제 비중을 구한다.
"""

from typing import Dict, List, Tuple

_MAIN_CATS = ["상의", "아우터", "바지"]


def _product_key(item: Dict) -> str:
    return item.get("url") or item.get("product_name", "")


def build_category_lookup(categorized_items: List[Dict]) -> Dict[str, str]:
    """이미 카테고리가 붙은 랭킹 데이터로 URL(상품 식별자) → 대분류 매핑을 만든다."""
    lookup: Dict[str, str] = {}
    for item in categorized_items:
        cat = item.get("category", "") or ""
        main = next((m for m in _MAIN_CATS if cat.startswith(m)), "")
        key = _product_key(item)
        if main and key:
            lookup[key] = main
    return lookup


def compute_category_weight(
    overall_items: List[Dict],
    categorized_items: List[Dict],
) -> Tuple[Dict[str, float], Dict[str, int]]:
    """통합 랭킹(overall_items)에서 실제 카테고리 비중을 가중치(0.6~1.6)로 환산한다.

    Args:
        overall_items: musinsa.fetch_category("전체", "000", ...) 결과 — 카테고리를
            안 가린 진짜 통합 TOP N.
        categorized_items: 이미 카테고리가 붙은 랭킹 데이터(예: all_overall) —
            URL→대분류 매핑표를 만드는 데 쓴다.

    Returns:
        (weights, matched_counts) — weights는 대분류별 가중치(매칭이 너무 적으면
        빈 dict), matched_counts는 대분류별 매칭된 상품 수(투명성용, 표본 크기를
        MD/디버깅에서 바로 확인할 수 있게).
    """
    lookup = build_category_lookup(categorized_items)
    counts: Dict[str, int] = {m: 0 for m in _MAIN_CATS}
    matched = 0
    for item in overall_items:
        main = lookup.get(_product_key(item))
        if main:
            counts[main] += 1
            matched += 1

    # 표본이 너무 적으면(예: 매칭 10건 미만) 비중 추정이 불안정하므로 가중치를
    # 적용하지 않고 빈 dict를 반환해 호출부가 기본값(1.0, 중립)을 쓰게 한다.
    if matched < 10:
        return {}, counts

    avg = matched / len(_MAIN_CATS)
    weights = {
        cat: max(0.6, min(1.6, round(count / avg, 2)))
        for cat, count in counts.items()
    }
    return weights, counts
