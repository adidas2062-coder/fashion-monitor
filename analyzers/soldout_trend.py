"""카테고리별 이탈률 추이 분석 — 품절/수요 초과 간접 신호.

랭킹 API는 재고 있는 상품만 반환하므로 직접 품절 수집이 불가하다.
대신 'top30에 있다 사라진 상품 비율(이탈률)'을 추적한다:
  이탈률 급증 = 수요 초과로 인한 품절 가능성 또는 급격한 트렌드 교체.
"""
import logging
from collections import defaultdict
from typing import Dict, List

logger = logging.getLogger(__name__)

_THRESHOLD_SURGE = 15.0   # 이탈률이 이 값(%) 이상 급등하면 경고
_TREND_WINDOW    = 3       # 연속 N일 이상 상승 시 지속 신호


def analyze(items_history: List[List[Dict]]) -> List[Dict]:
    """14일 랭킹 히스토리에서 카테고리별 이탈률 추이를 계산한다.

    Args:
        items_history: load_history() 결과 (날짜 오래된 순).

    Returns:
        [
          {
            "category":      "아우터_나일론코치",
            "main_category": "아우터",
            "today_rate":    37.0,   # 오늘(최근 쌍) 이탈률 %
            "avg_rate":      18.5,   # 전체 기간 평균 이탈률 %
            "delta":         +18.5,  # 최근 3일 평균 - 이전 평균 (양수 = 급증)
            "streak":        3,      # 연속 상승 일수
            "trend":         "🔴 급증",
          }, ...
        ]
    """
    if len(items_history) < 2:
        return []

    # 연속 일자 쌍별 이탈률 계산
    daily_dropout: List[Dict[str, float]] = []
    for i in range(1, len(items_history)):
        prev_day = items_history[i - 1]
        curr_day = items_history[i]

        prev_sets: Dict[str, set] = defaultdict(set)
        for item in prev_day:
            if item.get("period", "1일") != "1일":
                continue
            cat = item.get("category", "")
            if cat:
                prev_sets[cat].add(item.get("product_name", ""))

        curr_sets: Dict[str, set] = defaultdict(set)
        for item in curr_day:
            if item.get("period", "1일") != "1일":
                continue
            cat = item.get("category", "")
            if cat:
                curr_sets[cat].add(item.get("product_name", ""))

        rates: Dict[str, float] = {}
        for cat, prev_products in prev_sets.items():
            if not prev_products:
                continue
            dropped = prev_products - curr_sets.get(cat, set())
            rates[cat] = len(dropped) / len(prev_products) * 100
        daily_dropout.append(rates)

    if not daily_dropout:
        return []

    all_cats = set().union(*daily_dropout)
    results = []

    for cat in all_cats:
        series = [d.get(cat) for d in daily_dropout if d.get(cat) is not None]
        if len(series) < 2:
            continue

        today_rate = series[-1]
        avg_rate   = sum(series) / len(series)

        # 최근 3일 평균 vs 이전 평균
        recent = series[-min(3, len(series)):]
        prev   = series[:-min(3, len(series))] or series[:1]
        recent_avg = sum(recent) / len(recent)
        prev_avg   = sum(prev) / len(prev)
        delta = round(recent_avg - prev_avg, 1)

        # 연속 상승 streak
        streak = 0
        for j in range(len(series) - 1, 0, -1):
            if series[j] > series[j - 1]:
                streak += 1
            else:
                break

        if delta >= _THRESHOLD_SURGE:
            trend = "🔴 급증"
        elif delta >= 5:
            trend = "🟡 상승"
        elif delta <= -_THRESHOLD_SURGE:
            trend = "🟢 안정"
        else:
            trend = "→ 유지"

        results.append({
            "category":      cat,
            "main_category": cat.split("_")[0],
            "today_rate":    round(today_rate, 1),
            "avg_rate":      round(avg_rate, 1),
            "delta":         delta,
            "streak":        streak,
            "trend":         trend,
        })

    results.sort(key=lambda x: x["delta"], reverse=True)
    logger.info("이탈률 분석 완료: %d 카테고리", len(results))
    return results
