"""카테고리 성장률 분석기 — 노션 DB 주간 데이터 집계."""
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


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
            resp = client.databases.query(
                database_id=ranking_db_id,
                filter={"and": [
                    {"property": "날짜", "date": {"on_or_after": start}},
                    {"property": "날짜", "date": {"on_or_before": end}},
                ]},
            )
            return resp.get("results", [])
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
