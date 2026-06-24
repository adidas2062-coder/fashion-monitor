"""무신사와 29CM에서 동시에 반응하는 브랜드를 찾는다."""

from typing import Dict, List


def _brand(value: str) -> str:
    return "".join(str(value).lower().split())


def _brand_stats(items: List[Dict]) -> Dict[str, Dict]:
    stats: Dict[str, Dict] = {}
    for item in items:
        name = item.get("brand", "")
        key = _brand(name)
        if not key:
            continue
        row = stats.setdefault(key, {
            "brand": name,
            "count": 0,
            "best_rank": 999,
            "products": [],
        })
        row["count"] += 1
        row["best_rank"] = min(row["best_rank"], item.get("rank") or 999)
        if len(row["products"]) < 3:
            row["products"].append(item.get("product_name", ""))
    return stats


def analyze(
    musinsa: List[Dict],
    cm29: List[Dict],
    previous_musinsa: List[Dict] = None,
    previous_cm29: List[Dict] = None,
) -> List[Dict]:
    current_m = _brand_stats(musinsa)
    current_c = _brand_stats(cm29)
    prev_m = _brand_stats(previous_musinsa or [])
    prev_c = _brand_stats(previous_cm29 or [])

    rows = []
    for key in current_m.keys() & current_c.keys():
        m = current_m[key]
        c = current_c[key]
        previous_best = min(
            prev_m.get(key, {}).get("best_rank", 999),
            prev_c.get(key, {}).get("best_rank", 999),
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
            "musinsa_count": m["count"],
            "cm29_count": c["count"],
            "musinsa_best_rank": m["best_rank"],
            "cm29_best_rank": c["best_rank"],
            "rank_change": rank_change,
            "score": score,
            "products": list(dict.fromkeys(m["products"] + c["products"]))[:4],
        })

    rows.sort(key=lambda row: (-row["score"], min(
        row["musinsa_best_rank"], row["cm29_best_rank"]
    )))
    return rows[:10]
