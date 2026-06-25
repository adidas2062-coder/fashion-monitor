"""무신사와 29CM에서 동시에 반응하는 브랜드를 찾는다.

브랜드만 일치하면 교차로 잡으면 "한쪽은 아우터, 한쪽은 반팔티"처럼 서로
무관한 두 상품이 같은 시그널로 묶여 MD를 오도할 수 있다. 그래서 같은
대분류 카테고리(상의/아우터/바지)에서 동시에 반응하는 경우만 교차로 본다.
"""

from typing import Dict, List, Optional

# 29CM 세부 카테고리 → 무신사 대분류 라벨로 정규화.
# '전체'(혼합 베스트)·'셋업'(상하의 모두 가능)은 실제 카테고리를 특정할 수
# 없어 매칭 대상에서 제외한다.
_CM29_CATEGORY_MAP = {
    "상의": "상의",
    "아우터": "아우터",
    "하의": "바지",
    "니트웨어": "상의",
}


def _brand(value: str) -> str:
    return "".join(str(value).lower().split())


def _musinsa_category(item: Dict) -> str:
    return (item.get("category") or "").split("_")[0]


def _cm29_category(item: Dict) -> Optional[str]:
    raw = item.get("category") or ""
    sub = raw.split("_", 1)[1] if "_" in raw else raw
    return _CM29_CATEGORY_MAP.get(sub)


def _brand_category_stats(items: List[Dict], category_fn) -> Dict[str, Dict[str, Dict]]:
    """브랜드 → 카테고리 → {count, best_rank, best_url, products} 로 집계."""
    stats: Dict[str, Dict[str, Dict]] = {}
    for item in items:
        name = item.get("brand", "")
        brand_key = _brand(name)
        category = category_fn(item)
        if not brand_key or not category:
            continue
        by_cat = stats.setdefault(brand_key, {})
        row = by_cat.setdefault(category, {
            "brand": name, "count": 0, "best_rank": 999, "best_url": "", "products": [],
        })
        row["count"] += 1
        rank = item.get("rank") or 999
        if rank < row["best_rank"]:
            row["best_rank"] = rank
            row["best_url"] = item.get("url", "")
        if len(row["products"]) < 3:
            row["products"].append(item.get("product_name", ""))
    return stats


def analyze(
    musinsa: List[Dict],
    cm29: List[Dict],
    previous_musinsa: List[Dict] = None,
    previous_cm29: List[Dict] = None,
) -> List[Dict]:
    current_m = _brand_category_stats(musinsa, _musinsa_category)
    current_c = _brand_category_stats(cm29, _cm29_category)
    prev_m = _brand_category_stats(previous_musinsa or [], _musinsa_category)
    prev_c = _brand_category_stats(previous_cm29 or [], _cm29_category)

    rows = []
    for brand_key in current_m.keys() & current_c.keys():
        m_cats = current_m[brand_key]
        c_cats = current_c[brand_key]
        shared = m_cats.keys() & c_cats.keys()
        if not shared:
            continue  # 같은 카테고리에서 동시에 반응해야만 진짜 교차 신호로 본다.

        # 두 플랫폼 합산 최고순위가 가장 좋은 공유 카테고리를 대표로 잡는다.
        category = min(shared, key=lambda cat: min(m_cats[cat]["best_rank"], c_cats[cat]["best_rank"]))
        m, c = m_cats[category], c_cats[category]

        prev_m_cat = prev_m.get(brand_key, {}).get(category, {})
        prev_c_cat = prev_c.get(brand_key, {}).get(category, {})
        previous_best = min(
            prev_m_cat.get("best_rank", 999),
            prev_c_cat.get("best_rank", 999),
        )
        current_best = min(m["best_rank"], c["best_rank"])
        rank_change = (
            previous_best - current_best if previous_best < 999 else None
        )
        # 두 플랫폼 동시 진입을 기본 신호로 두고 노출 상품 수와 최근 순위 상승을 가산한다.
        score = min(
            100,
            35
            + min(m["count"] + c["count"], 10) * 4
            + (20 if rank_change and rank_change >= 5 else 0),
        )
        rows.append({
            "brand": m["brand"] or c["brand"],
            "category": category,
            "musinsa_count": m["count"],
            "cm29_count": c["count"],
            "musinsa_best_rank": m["best_rank"],
            "cm29_best_rank": c["best_rank"],
            "musinsa_url": m["best_url"],
            "cm29_url": c["best_url"],
            "rank_change": rank_change,
            "score": score,
            "products": list(dict.fromkeys(m["products"] + c["products"]))[:4],
        })

    rows.sort(key=lambda row: (-row["score"], min(
        row["musinsa_best_rank"], row["cm29_best_rank"]
    )))
    return rows[:10]
