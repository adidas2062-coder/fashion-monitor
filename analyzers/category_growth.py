"""카테고리 성장률 분석기 — 노션 DB 주간 데이터 집계."""
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


def analyze_items_history(items_history: List[List[Dict]]) -> List[Dict]:
    """최근 날짜별 전체 스냅샷으로 카테고리 성장률을 계산한다.

    대분류(상의/아우터/바지) 3건 외에, 각 대분류 안의 세분류(반소매티셔츠,
    후드집업 등)별 성장률도 `subcategories`에 담아 더 디테일하게 볼 수 있게 한다.
    """
    if len(items_history) < 2:
        return []
    midpoint = max(1, len(items_history) // 2)

    def _collect(days: List[List[Dict]], key_fn) -> Dict[str, List[int]]:
        ranks = defaultdict(list)
        for items in days:
            for item in items:
                if item.get("period", "1일") != "1일":
                    continue
                key = key_fn(item.get("category", ""))
                rank = item.get("rank")
                if key and rank:
                    ranks[key].append(rank)
        return ranks

    def _build(key_fn) -> List[Dict]:
        previous = {
            k: sum(v) / len(v)
            for k, v in _collect(items_history[:midpoint], key_fn).items() if v
        }
        current = {
            k: sum(v) / len(v)
            for k, v in _collect(items_history[midpoint:], key_fn).items() if v
        }
        results = []
        for key, current_rank in current.items():
            previous_rank = previous.get(key)
            change = round(previous_rank - current_rank, 1) if previous_rank else 0
            growth = round(change / previous_rank * 100, 1) if previous_rank else 0
            results.append({
                "category": key,
                "this_avg": round(current_rank, 1),
                "prev_avg": round(previous_rank, 1) if previous_rank else None,
                "rank_change": change,
                "growth_pct": growth,
                "trend": "📈 상승" if change > 2 else ("📉 하락" if change < -2 else "➡️ 유지"),
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
        main, sub = row["category"].split("_", 1)
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
