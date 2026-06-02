"""
네이버 데이터랩 쇼핑 트렌드 수집기.

두 가지 데이터를 수집한다:
  1. 카테고리별 검색량 지수 — 상의 / 아우터 / 바지
     POST /v1/datalab/shopping/categories
  2. 패션 키워드별 쇼핑 검색량 지수
     POST /v1/datalab/shopping/category/keywords  (카테고리 = 전체)

config.py에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 비어 있으면
경고를 남기고 빈 리스트를 반환한다.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

_CATEGORY_URL = "https://openapi.naver.com/v1/datalab/shopping/categories"
_KEYWORD_URL  = "https://openapi.naver.com/v1/datalab/shopping/category/keywords"

_RETRY_MAX   = 3
_RETRY_DELAY = 3.0

# 네이버 데이터랩 키워드 API 한 번에 최대 5개
_KW_CHUNK_SIZE = 5


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _headers() -> Dict[str, str]:
    return {
        "X-Naver-Client-Id":     config.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": config.NAVER_CLIENT_SECRET,
        "Content-Type":          "application/json",
    }


def _date_range(days_back: int = 7) -> tuple:
    """오늘 기준으로 days_back 일 전~어제 날짜 범위 반환."""
    today     = datetime.now(timezone.utc).date()
    end_date  = today - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back - 1)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def _post(url: str, body: dict) -> Optional[dict]:
    """POST 요청 → JSON dict 반환. 실패 시 None."""
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    for attempt in range(1, _RETRY_MAX + 1):
        try:
            req = urllib.request.Request(url, data=payload, method="POST")
            for k, v in _headers().items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_txt = exc.read().decode("utf-8", errors="replace")
            logger.warning(
                "네이버 API HTTP 에러 (시도 %d/%d) %s: %s",
                attempt, _RETRY_MAX, exc.code, body_txt[:200],
            )
            if exc.code in (401, 403):   # 인증 실패는 재시도 무의미
                return None
        except Exception as exc:
            logger.warning("네이버 API 요청 실패 (시도 %d/%d): %s", attempt, _RETRY_MAX, exc)
        if attempt < _RETRY_MAX:
            time.sleep(_RETRY_DELAY)
    return None


def _avg_ratio(data_points: List[Dict]) -> float:
    """data 배열의 ratio 평균."""
    if not data_points:
        return 0.0
    return round(sum(d.get("ratio", 0) for d in data_points) / len(data_points), 2)


def _prev_week_start_end() -> tuple:
    """전주 7일 날짜 범위 반환."""
    today      = datetime.now(timezone.utc).date()
    end_date   = today - timedelta(days=8)
    start_date = end_date - timedelta(days=6)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def fetch_category_trends() -> List[Dict]:
    """
    상의 / 아우터 / 바지 카테고리 이번 주 쇼핑 검색량 지수 수집.

    Returns:
        카테고리별 dict 목록. API 키 미설정 또는 실패 시 빈 리스트.
    """
    if not config.NAVER_CLIENT_ID or not config.NAVER_CLIENT_SECRET:
        logger.warning("NAVER_CLIENT_ID/SECRET 미설정 — 네이버 카테고리 트렌드 스킵")
        return []

    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_now, end_now   = _date_range(7)
    start_prev, end_prev = _prev_week_start_end()

    categories = [
        {"name": "상의",  "param": ["50000000"]},
        {"name": "아우터", "param": ["50000001"]},
        {"name": "바지",  "param": ["50000003"]},
    ]

    body_now = {
        "startDate": start_now,
        "endDate":   end_now,
        "timeUnit":  "date",
        "category":  categories,
        "device": "",
        "gender": "",
        "ages":   [],
    }
    body_prev = {**body_now, "startDate": start_prev, "endDate": end_prev}

    raw_now  = _post(_CATEGORY_URL, body_now)
    time.sleep(config.REQUEST_DELAY)
    raw_prev = _post(_CATEGORY_URL, body_prev)

    if raw_now is None:
        logger.error("네이버 카테고리 트렌드 수집 실패")
        return []

    prev_map: Dict[str, float] = {}
    if raw_prev:
        for r in raw_prev.get("results", []):
            prev_map[r["title"]] = _avg_ratio(r.get("data", []))

    results: List[Dict] = []
    for r in raw_now.get("results", []):
        name  = r["title"]
        score = _avg_ratio(r.get("data", []))
        prev  = prev_map.get(name, 0.0)
        change_pct = round((score - prev) / prev * 100, 1) if prev > 0 else 0.0
        results.append({
            "platform":    "네이버",
            "type":        "category",
            "keyword":     name,
            "score":       score,
            "prev_score":  prev,
            "change_pct":  change_pct,
            "collected_at": collected_at,
        })

    logger.info("네이버 카테고리 트렌드 수집 완료: %d건", len(results))
    return results


def fetch_keyword_trends(keywords: Optional[List[str]] = None) -> List[Dict]:
    """
    패션 키워드별 쇼핑 검색량 지수 수집 (전체 카테고리 기준).

    Returns:
        키워드별 dict 목록. API 키 미설정 또는 실패 시 빈 리스트.
    """
    if not config.NAVER_CLIENT_ID or not config.NAVER_CLIENT_SECRET:
        logger.warning("NAVER_CLIENT_ID/SECRET 미설정 — 네이버 키워드 트렌드 스킵")
        return []

    keywords = keywords or config.FASHION_KEYWORDS
    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_now, end_now   = _date_range(7)
    start_prev, end_prev = _prev_week_start_end()

    results: List[Dict] = []
    chunks = [keywords[i:i + _KW_CHUNK_SIZE] for i in range(0, len(keywords), _KW_CHUNK_SIZE)]

    for chunk in chunks:
        kw_params = [{"name": kw, "param": [kw]} for kw in chunk]
        body_now = {
            "startDate": start_now,
            "endDate":   end_now,
            "timeUnit":  "date",
            "category":  "50000000",   # 패션의류 전체
            "keyword":   kw_params,
            "device": "",
            "gender": "",
            "ages":   [],
        }
        body_prev = {**body_now, "startDate": start_prev, "endDate": end_prev}

        logger.info("네이버 키워드 트렌드 수집 중: %s", chunk)
        raw_now  = _post(_KEYWORD_URL, body_now)
        time.sleep(config.REQUEST_DELAY)
        raw_prev = _post(_KEYWORD_URL, body_prev)
        time.sleep(config.REQUEST_DELAY)

        if raw_now is None:
            logger.error("네이버 키워드 트렌드 수집 실패 — 청크 스킵: %s", chunk)
            continue

        prev_map: Dict[str, float] = {}
        if raw_prev:
            for r in raw_prev.get("results", []):
                prev_map[r["title"]] = _avg_ratio(r.get("data", []))

        for r in raw_now.get("results", []):
            name  = r["title"]
            score = _avg_ratio(r.get("data", []))
            prev  = prev_map.get(name, 0.0)
            change_pct = round((score - prev) / prev * 100, 1) if prev > 0 else 0.0
            results.append({
                "platform":    "네이버",
                "type":        "keyword",
                "keyword":     name,
                "score":       score,
                "prev_score":  prev,
                "change_pct":  change_pct,
                "collected_at": collected_at,
            })

    logger.info("네이버 키워드 트렌드 수집 완료: %d건", len(results))
    return results


def collect() -> List[Dict]:
    """
    네이버 데이터랩 전체 수집 (카테고리 트렌드 + 키워드 트렌드).

    Returns:
        두 수집 결과를 합친 dict 목록.
    """
    cat_data = fetch_category_trends()
    time.sleep(config.REQUEST_DELAY)
    kw_data  = fetch_keyword_trends()
    combined = cat_data + kw_data
    logger.info("네이버 데이터랩 전체 수집 완료: 총 %d건", len(combined))
    return combined
