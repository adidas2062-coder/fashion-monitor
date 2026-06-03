"""
트렌드 예측기.

최근 수집된 트렌드 점수와 랭킹 데이터를 이동평균으로 분석해
다음 주 주목할 키워드를 예측한다.

데이터가 3주 이상 쌓이면 더 정확해지며,
초기에는 최근 점수 기반 단순 정렬로 동작한다.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _moving_avg(values: List[float]) -> float:
    """가중 이동평균 (최신 데이터에 더 큰 가중치)."""
    if not values:
        return 0.0
    n = len(values)
    weights = [i + 1 for i in range(n)]   # 1, 2, 3, ...n
    weighted = sum(v * w for v, w in zip(values, weights))
    return round(weighted / sum(weights), 1)


def _growth_rate(values: List[float]) -> float:
    """최초 대비 최근 성장률 (%)."""
    if len(values) < 2 or values[0] == 0:
        return 0.0
    return round((values[-1] - values[0]) / values[0] * 100, 1)


def forecast_from_notion(client, trend_db_id: str, weeks: int = 4) -> List[Dict]:
    """
    노션 트렌드 DB에서 과거 데이터를 조회해 예측.

    Args:
        client:       notion_client.Client 인스턴스.
        trend_db_id:  노션 트렌드 DB ID.
        weeks:        분석할 주 수.

    Returns:
        예측 키워드 목록 (전망 점수 내림차순).
    """
    start = (date.today() - timedelta(weeks=weeks)).isoformat()
    try:
        resp = client.databases.query(
            database_id=trend_db_id,
            filter={
                "and": [
                    {"property": "날짜", "date": {"on_or_after": start}},
                    {"property": "플랫폼", "select": {"does_not_equal": "무신사_검색어"}},
                ]
            },
        )
        pages = resp.get("results", [])
    except Exception as exc:
        logger.error("트렌드 예측 노션 조회 실패: %s", exc)
        return []

    # 키워드별 날짜순 점수 수집
    kw_scores: Dict[str, Dict[str, float]] = defaultdict(dict)
    for page in pages:
        props = page.get("properties", {})
        kw    = (props.get("키워드",{}).get("title") or [{}])[0].get("text",{}).get("content","")
        score = props.get("점수/수치",{}).get("number") or 0
        dt    = (props.get("날짜",{}).get("date") or {}).get("start","")
        if kw and dt:
            kw_scores[kw][dt] = max(kw_scores[kw].get(dt, 0), score)

    return _compute_forecast(kw_scores)


def forecast_from_trend_data(trend_history: List[List[Dict]]) -> List[Dict]:
    """
    수집된 트렌드 데이터 목록(여러 날)으로 예측.
    [[오늘 트렌드], [어제 트렌드], ...]  — 최신순 입력.

    Args:
        trend_history: 날짜별 트렌드 데이터 목록.
    """
    # 날짜별 키워드 점수 집계
    kw_scores: Dict[str, Dict[str, float]] = defaultdict(dict)
    for i, day_data in enumerate(trend_history):
        dt = (date.today() - timedelta(days=i)).isoformat()
        for item in day_data:
            kw    = item.get("keyword","")
            score = item.get("score", 0)
            pf    = item.get("platform","")
            if kw and pf not in ("무신사_검색어", "구글_트렌딩"):
                kw_scores[kw][dt] = max(kw_scores[kw].get(dt, 0), float(score))

    return _compute_forecast(kw_scores)


def _compute_forecast(kw_scores: Dict[str, Dict[str, float]]) -> List[Dict]:
    """이동평균 + 성장률로 예측 점수 계산."""
    forecasts: List[Dict] = []

    for kw, date_scores in kw_scores.items():
        if not date_scores:
            continue
        sorted_dates = sorted(date_scores.keys())
        values = [date_scores[d] for d in sorted_dates]

        avg    = _moving_avg(values)
        growth = _growth_rate(values)
        # 예측 점수 = 이동평균 × (1 + 성장률/100) — 성장 추세 반영
        forecast_score = round(avg * (1 + max(growth, 0) / 100), 1)

        trend_dir = "↑상승" if growth > 10 else ("↓하락" if growth < -10 else "→유지")

        forecasts.append({
            "keyword":        kw,
            "data_points":    len(values),
            "current_score":  values[-1] if values else 0,
            "moving_avg":     avg,
            "growth_rate":    growth,
            "forecast_score": forecast_score,
            "trend_direction": trend_dir,
            "confidence":     "높음" if len(values) >= 7 else ("보통" if len(values) >= 3 else "낮음"),
        })

    forecasts.sort(key=lambda x: x["forecast_score"], reverse=True)

    if forecasts:
        logger.info("트렌드 예측 완료: TOP3 = %s",
                    [f["keyword"] for f in forecasts[:3]])
    return forecasts
