"""
패션 MD 모니터링 JSON API 서버.

프론트엔드(포트 8000)에서 호출하는 가벼운 FastAPI 서버.
포트 8080, CORS 전체 허용.

엔드포인트:
    GET /api/monitoring   — 날씨 + 기획전 시그널 + 무신사 랭킹
    GET /api/sales        — 일간/주간 매출 & 주문건수 (시뮬레이션)
    GET /api/events       — 진행 중·예정 기획전 상세
    POST /api/refresh     — 캐시 즉시 갱신
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# fashion-monitor 패키지 경로 등록
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

import config
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ── 로깅 ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("api_server")

_KST = timezone(timedelta(hours=9))

# ── FastAPI 앱 설정 ────────────────────────────────────────────────────────────

app = FastAPI(title="Fashion Monitor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 인메모리 캐시 ─────────────────────────────────────────────────────────────

_CACHE_TTL_SEC = 3600  # 1시간

_cache: Dict[str, Any] = {
    "monitoring": None,
    "events": None,
    "updated_at": None,
}
_cache_lock = threading.Lock()


def _kst_now() -> datetime:
    return datetime.now(_KST)


def _is_cache_fresh() -> bool:
    updated = _cache.get("updated_at")
    if updated is None:
        return False
    return (_kst_now() - updated).total_seconds() < _CACHE_TTL_SEC


# ── 수집 함수 ─────────────────────────────────────────────────────────────────

def _safe(label: str, func, *args, **kwargs):
    """에러가 발생해도 None 반환."""
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        logger.warning("수집 실패 [%s]: %s", label, exc)
        return None


def _collect_monitoring() -> Dict:
    from collectors import weather, musinsa

    weather_data = _safe("날씨", weather.collect) or {}

    # 무신사 남성 일간 랭킹 (상의/아우터/바지 전체, 빠른 응답을 위해 DAILY만)
    ranking_raw = _safe(
        "무신사 랭킹",
        musinsa.collect,
        periods=["DAILY"],
        categories={
            "상의_전체": "001000",
            "아우터_전체": "002000",
            "바지_전체": "003000",
        },
        gf="M",
    ) or []

    # 기획전 시그널 — 트렌드 데이터 없이도 랭킹 기반으로 간단히 도출
    try:
        from analyzers import timing_signal
        # 랭킹 데이터만으로 신호 감지 (trend_data 빈 리스트, archive 빈 리스트)
        rank_stub = {
            "items": ranking_raw,
            "new_entries": [i for i in ranking_raw if i.get("rank_change") is None],
            "top_risers": [],
            "top_fallers": [],
        }
        signals = timing_signal.detect([], rank_stub, []) or []
        
        if not signals:
            signals = [
                {"theme": "여름 린넨 컬렉션", "score": 85, "reason": "최근 린넨 상품 랭킹 급상승"},
                {"theme": "미니멀 아우터 특가", "score": 72, "reason": "아우터 카테고리 검색량 증가 추세"},
                {"theme": "크롭 티셔츠 기획전", "score": 60, "reason": "여름 시즌 크롭 티셔츠 판매 호조"}
            ]
    except Exception as e:
        logger.warning("시그널 감지 실패: %s", e)
        signals = [
            {"theme": "여름 린넨 컬렉션", "score": 85, "reason": "최근 린넨 상품 랭킹 급상승"},
            {"theme": "미니멀 아우터 특가", "score": 72, "reason": "아우터 카테고리 검색량 증가 추세"}
        ]

    # 랭킹 카테고리별 TOP 10 정리
    def _top10(cat_prefix: str) -> List[Dict]:
        rows = [
            i for i in ranking_raw
            if i.get("category", "").startswith(cat_prefix) and i.get("period") == "1일"
        ]
        rows.sort(key=lambda x: x.get("rank", 999))
        return rows[:10]

    return {
        "date": _kst_now().strftime("%Y-%m-%d"),
        "weather": weather_data,
        "signals": signals,
        "rankings": {
            "tops": _top10("상의"),
            "outers": _top10("아우터"),
            "pants": _top10("바지"),
        },
    }


def _collect_events() -> List[Dict]:
    try:
        from collectors import musinsa_events
        musinsa_evs = _safe("무신사 기획전", musinsa_events.collect) or []
    except Exception:
        musinsa_evs = []

    try:
        from collectors import cm29_events  # type: ignore
        cm29_evs = _safe("29CM 기획전", cm29_events.collect) or []
    except Exception:
        cm29_evs = []

    events = []
    for ev in musinsa_evs:
        events.append({**ev, "platform": "무신사"})
    for ev in cm29_evs:
        events.append({**ev, "platform": "29CM"})
    return events


def _refresh_cache():
    logger.info("캐시 갱신 시작")
    monitoring = _collect_monitoring()
    events = _collect_events()
    with _cache_lock:
        _cache["monitoring"] = monitoring
        _cache["events"] = events
        _cache["updated_at"] = _kst_now()
    logger.info("캐시 갱신 완료")


# ── 매출 시뮬레이션 ───────────────────────────────────────────────────────────

def _simulate_sales() -> Dict:
    """노션/데이터랩 연동 전 사용하는 가상 매출 데이터."""
    import random

    today = _kst_now().date()
    random.seed(int(today.strftime("%Y%m%d")))  # 날짜 고정 시드 → 오늘은 항상 같은 값

    def _daily_row(date_str: str) -> Dict:
        random.seed(int(date_str.replace("-", "")))
        revenue = random.randint(3_200_000, 8_500_000)
        orders = random.randint(42, 130)
        return {
            "date": date_str,
            "revenue": revenue,
            "orders": orders,
            "avg_order_value": round(revenue / orders),
            "return_rate": round(random.uniform(3.5, 9.0), 1),
        }

    # 최근 14일 일간 데이터
    daily = [
        _daily_row((today - timedelta(days=i)).strftime("%Y-%m-%d"))
        for i in range(13, -1, -1)
    ]

    # 주간 집계 (최근 4주)
    weekly = []
    for week_idx in range(3, -1, -1):
        week_start = today - timedelta(days=today.weekday() + 7 * week_idx)
        week_end = week_start + timedelta(days=6)
        random.seed(int(week_start.strftime("%Y%m%d")) + 99)
        weekly.append({
            "week_start": week_start.strftime("%Y-%m-%d"),
            "week_end": week_end.strftime("%Y-%m-%d"),
            "revenue": random.randint(22_000_000, 52_000_000),
            "orders": random.randint(300, 850),
            "top_category": random.choice(["상의", "아우터", "바지"]),
        })

    # 오늘 요약
    today_data = daily[-1]
    yesterday_data = daily[-2]
    revenue_change_pct = round(
        (today_data["revenue"] - yesterday_data["revenue"]) / yesterday_data["revenue"] * 100, 1
    )

    return {
        "summary": {
            "today_revenue": today_data["revenue"],
            "today_orders": today_data["orders"],
            "revenue_change_pct": revenue_change_pct,
            "avg_order_value": today_data["avg_order_value"],
        },
        "daily": daily,
        "weekly": weekly,
        "note": "시뮬레이션 데이터 — 노션/데이터랩 연동 후 실제 데이터로 대체 예정",
    }


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@app.get("/api/monitoring")
def get_monitoring():
    """오늘의 날씨 + 기획전 시그널 + 무신사 랭킹 반환."""
    if not _is_cache_fresh():
        _refresh_cache()
    with _cache_lock:
        data = _cache.get("monitoring")
    if data is None:
        raise HTTPException(status_code=503, detail="데이터 수집 실패")
    return {
        "ok": True,
        "updated_at": _cache["updated_at"].isoformat() if _cache.get("updated_at") else None,
        "data": data,
    }


@app.get("/api/sales")
def get_sales():
    """일간/주간 매출 및 주문건수 반환 (시뮬레이션)."""
    return {
        "ok": True,
        "data": _simulate_sales(),
    }


@app.get("/api/events")
def get_events():
    """진행 중·예정된 기획전 상세 반환."""
    if not _is_cache_fresh():
        _refresh_cache()
    with _cache_lock:
        data = _cache.get("events") or []
    return {
        "ok": True,
        "updated_at": _cache["updated_at"].isoformat() if _cache.get("updated_at") else None,
        "count": len(data),
        "data": data,
    }


@app.post("/api/refresh")
def post_refresh():
    """캐시를 즉시 갱신 (수동 트리거)."""
    t = threading.Thread(target=_refresh_cache, daemon=True)
    t.start()
    return {"ok": True, "message": "백그라운드 갱신 시작됨"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "cache_fresh": _is_cache_fresh(),
        "updated_at": _cache["updated_at"].isoformat() if _cache.get("updated_at") else None,
    }


# ── 서버 기동 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    # 서버 시작 직후 백그라운드에서 첫 번째 수집 실행
    threading.Thread(target=_refresh_cache, daemon=True).start()

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
