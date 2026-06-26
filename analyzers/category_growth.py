"""카테고리 성장률 분석기 — 노션 DB 주간 데이터 집계."""
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


def analyze_items_history(items_history: List[List[Dict]]) -> List[Dict]:
    """최근 날짜별 전체 스냅샷으로 카테고리 성장률을 계산한다.

    연속된 일자 쌍(day N → day N+1)에서 공통 상품의 순위 변화를 집계한 뒤,
    전반기 평균 vs 후반기 평균을 비교한다 (양수 = 최근 더 오름, 즉 성장).

    각 대분류 아래 세분류(반소매티셔츠, 후드집업 등)도 `subcategories`에 포함한다.
    """
    if len(items_history) < 2:
        return []
    midpoint = max(1, len(items_history) // 2)

    def _build_pairs(days):
        return [(days[i], days[i + 1]) for i in range(len(days) - 1)]

    first_pairs  = _build_pairs(items_history[:midpoint])
    second_pairs = _build_pairs(items_history[midpoint:])
    # 한 쪽이 비면 전체 히스토리의 첫·마지막 쌍으로 대체
    if not first_pairs:
        first_pairs  = [(items_history[0], items_history[1])]
    if not second_pairs:
        second_pairs = [(items_history[-2], items_history[-1])]

    def _pair_momentum(prev_day, curr_day, key_fn) -> Dict[str, float]:
        """연속 두 스냅샷에서 카테고리별 공통 상품 평균 순위 변화 (양수 = 개선)."""
        prev_ranks: Dict[str, Dict[str, int]] = defaultdict(dict)
        for item in prev_day:
            if item.get("period", "1일") != "1일":
                continue
            key = key_fn(item.get("category", ""))
            pname = item.get("product_name", "")
            rank  = item.get("rank")
            if key and pname and rank:
                prev_ranks[key][pname] = rank

        cat_changes: Dict[str, list] = defaultdict(list)
        for item in curr_day:
            if item.get("period", "1일") != "1일":
                continue
            key  = key_fn(item.get("category", ""))
            pname = item.get("product_name", "")
            rank  = item.get("rank")
            if key and pname and rank and pname in prev_ranks.get(key, {}):
                cat_changes[key].append(prev_ranks[key][pname] - rank)

        return {k: sum(v) / len(v) for k, v in cat_changes.items() if v}

    def _avg_momentum(pairs, key_fn) -> Dict[str, float]:
        all_changes: Dict[str, list] = defaultdict(list)
        for prev_day, curr_day in pairs:
            for key, avg_c in _pair_momentum(prev_day, curr_day, key_fn).items():
                all_changes[key].append(avg_c)
        return {k: sum(v) / len(v) for k, v in all_changes.items()}

    def _build(key_fn) -> List[Dict]:
        prev_m = _avg_momentum(first_pairs, key_fn)
        this_m = _avg_momentum(second_pairs, key_fn)

        results = []
        for key in set(prev_m) | set(this_m):
            if not key:
                continue
            this_val = this_m.get(key)
            prev_val = prev_m.get(key)
            if this_val is None:
                continue
            # 후반기 모멘텀 - 전반기 모멘텀 (양수 = 최근 더 많이 상승)
            change = round(this_val - prev_val, 2) if prev_val is not None else round(this_val, 2)
            # 카테고리 내 최대 일일 순위 변화 폭(29)으로 정규화
            growth = round(change / 29 * 100, 1)
            results.append({
                "category":   key,
                "this_avg":   round(this_val, 2),
                "prev_avg":   round(prev_val, 2) if prev_val is not None else None,
                "rank_change": change,
                "growth_pct": growth,
                "trend": "📈 상승" if change > 0.3 else ("📉 하락" if change < -0.3 else "➡️ 유지"),
            })
        return sorted(results, key=lambda row: row["growth_pct"], reverse=True)

    main_results = _build(lambda c: c.split("_")[0] if c else "")

    # 세분류는 "전체" 탭(대분류 합계와 중복)을 제외하고 집계한다.
    def _sub_key(category: str):
        if "_" not in category:
            return None
        sub = category.split("_", 1)[1]
        return None if sub == "전체" else category

    sub_by_main: Dict[str, List[Dict]] = defaultdict(list)
    for row in _build(_sub_key):
        parts = row["category"].split("_", 1)
        if len(parts) == 2:
            main, sub = parts
            row["subcategory"] = sub
            sub_by_main[main].append(row)

    for row in main_results:
        row["subcategories"] = sub_by_main.get(row["category"], [])
    return main_results


def analyze(client, ranking_db_id: str, weeks: int = 2) -> List[Dict]:
    """
    최근 N주 랭킹 데이터로 카테고리별 평균 순위 변화 계산.
    순위가 낮아질수록(숫자 작아질수록) 성장.
    """
    today      = date.today()
    this_start = (today - timedelta(days=6)).isoformat()
    prev_start = (today - timedelta(days=13)).isoformat()
    prev_end   = (today - timedelta(days=7)).isoformat()

    def _query(start, end):
        try:
            pages = []
            cursor = None
            while True:
                resp = client.databases.query(
                    database_id=ranking_db_id,
                    filter={"and": [
                        {"property": "날짜", "date": {"on_or_after": start}},
                        {"property": "날짜", "date": {"on_or_before": end}},
                    ]},
                    start_cursor=cursor,
                )
                pages.extend(resp.get("results", []))
                if not resp.get("has_more"):
                    break
                cursor = resp.get("next_cursor")
            return pages
        except Exception as e:
            logger.error("카테고리 성장률 조회 실패: %s", e)
            return []

    def _avg_rank(pages) -> Dict[str, float]:
        cat_ranks = defaultdict(list)
        for p in pages:
            props = p.get("properties", {})
            cat   = (props.get("카테고리",{}).get("select") or {}).get("name","")
            rank  = props.get("순위",{}).get("number")
            if cat and rank:
                # 대분류만
                main = cat.split("_")[0]
                cat_ranks[main].append(rank)
        return {cat: sum(ranks)/len(ranks) for cat, ranks in cat_ranks.items()}

    this_pages = _query(this_start, today.isoformat())
    prev_pages = _query(prev_start, prev_end)

    this_avg = _avg_rank(this_pages)
    prev_avg = _avg_rank(prev_pages)

    results = []
    all_cats = set(list(this_avg.keys()) + list(prev_avg.keys()))
    for cat in all_cats:
        this_r = this_avg.get(cat)
        prev_r = prev_avg.get(cat)
        if not this_r:
            continue
        if prev_r:
            # 순위 개선 = prev가 더 큼 (숫자 큰 게 낮은 순위) → 양수가 상승
            change = round(prev_r - this_r, 1)
            change_pct = round(change / prev_r * 100, 1) if prev_r else 0
        else:
            change = 0
            change_pct = 0

        results.append({
            "category":    cat,
            "this_avg":    round(this_r, 1),
            "prev_avg":    round(prev_r, 1) if prev_r else None,
            "rank_change": change,
            "growth_pct":  change_pct,
            "trend":       "📈 상승" if change > 2 else ("📉 하락" if change < -2 else "➡️ 유지"),
        })

    results.sort(key=lambda x: x["growth_pct"], reverse=True)
    logger.info("카테고리 성장률 분석: %d개", len(results))
    return results
