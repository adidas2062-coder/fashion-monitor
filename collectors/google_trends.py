"""
구글 트렌드 수집기.

두 가지 데이터를 수집한다:
  1. 패션 키워드별 관심도 점수 (trendspy interest_over_time) — 주요 경로
  2. 한국 실시간 트렌딩 키워드 (Google Trends RSS) — 폴백 및 보완 데이터

관심도 수집은 `trendspy`를 사용한다. 기존 `pytrends`(4.9.2)는 구글의 내부
Trends API 변경으로 build_payload 단계에서 400을 반환해 동작하지 않으며,
urllib3 v2와도 비호환(method_whitelist)이라 폐기했다. trendspy 미설치·실패
시 해당 수집을 스킵하고 RSS 트렌딩 데이터만 반환한다.
"""

import logging
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

_RSS_URL = "https://trends.google.com/trending/rss?geo=KR"
_RSS_NS = {"ht": "https://trends.google.com/trending/rss"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

_CHUNK_SIZE = 5          # 구글 트렌드 정규화 비교 한도(요청당 최대 5개)
_RETRY_MAX = 3
_RETRY_DELAY = 5.0


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────


def _kst_today() -> str:
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")


def _make_client():
    """trendspy Trends 클라이언트 생성. 미설치 시 None."""
    try:
        from trendspy import Trends
    except ImportError:
        logger.warning("trendspy 미설치 — 구글 트렌드 키워드 관심도 수집 스킵")
        return None
    return Trends(language="ko", tzs=540, request_delay=config.REQUEST_DELAY)


def _fetch_interest_chunk(
    client,
    keywords: List[str],
    timeframe: str,
) -> Optional[Dict[str, float]]:
    """
    키워드 청크 하나의 관심도 점수를 반환.
    실패 시 None 반환(예외 전파 안 함).
    """
    for attempt in range(1, _RETRY_MAX + 1):
        try:
            df = client.interest_over_time(keywords, timeframe=timeframe, geo="KR")
            if df is None or df.empty:
                return {kw: 0.0 for kw in keywords}
            cols = [c for c in df.columns if c != "isPartial"]
            avg = df[cols].mean().to_dict()
            return {kw: round(float(avg.get(kw, 0)), 1) for kw in keywords}
        except Exception as exc:
            logger.warning(
                "구글 트렌드 요청 실패 (시도 %d/%d, 키워드=%s): %s",
                attempt, _RETRY_MAX, keywords, exc,
            )
            if attempt < _RETRY_MAX:
                time.sleep(_RETRY_DELAY * attempt)
    return None


def _weeks_ago_timeframe(weeks: int) -> str:
    """N주 전 7일 구간의 timeframe 문자열 반환."""
    today = datetime.now(timezone.utc)
    end = today - timedelta(weeks=weeks - 1)
    start = end - timedelta(days=6)
    return f"{start.strftime('%Y-%m-%d')} {end.strftime('%Y-%m-%d')}"


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def fetch_keyword_interest(keywords: Optional[List[str]] = None) -> List[Dict]:
    """
    패션 키워드별 이번 주 관심도 + 전주 대비 변화율 수집.

    Returns:
        키워드별 dict 목록. pytrends 실패 시 빈 리스트.
    """
    keywords = keywords or config.FASHION_KEYWORDS
    collected_at = _kst_today()
    client = _make_client()
    if client is None:
        return []

    timeframe_now = "today 7-d"
    timeframe_prev = _weeks_ago_timeframe(2)  # 전주 7일

    results: List[Dict] = []
    chunks = [keywords[i:i + _CHUNK_SIZE] for i in range(0, len(keywords), _CHUNK_SIZE)]

    for chunk in chunks:
        logger.info("Google Trends 수집 중: %s", chunk)

        scores_now = _fetch_interest_chunk(client, chunk, timeframe_now)
        if scores_now is None:
            logger.error("Google Trends 수집 실패 — 청크 스킵: %s", chunk)
            continue

        time.sleep(config.REQUEST_DELAY)

        scores_prev = _fetch_interest_chunk(client, chunk, timeframe_prev)

        for kw in chunk:
            score = scores_now.get(kw, 0.0)
            prev = (scores_prev or {}).get(kw, 0.0)
            change = round(score - prev, 1)
            change_pct = round((change / prev * 100) if prev > 0 else 0.0, 1)
            results.append({
                "platform": "구글",
                "keyword": kw,
                "score": score,
                "prev_score": prev,
                "change": change,
                "change_pct": change_pct,
                "collected_at": collected_at,
            })

        time.sleep(config.REQUEST_DELAY)

    logger.info("Google Trends 키워드 수집 완료: %d건", len(results))
    return results


def fetch_trending_rss() -> List[Dict]:
    """
    한국 Google Trends 실시간 트렌딩 키워드 수집 (RSS, 인증 불필요).

    Returns:
        트렌딩 키워드 dict 목록. 실패 시 빈 리스트.
    """
    collected_at = _kst_today()
    try:
        req = urllib.request.Request(_RSS_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()

        root = ET.fromstring(xml_data)
        results: List[Dict] = []
        for rank, item in enumerate(root.findall(".//item"), start=1):
            title_el = item.find("title")
            traffic_el = item.find("ht:approx_traffic", _RSS_NS)
            if title_el is None:
                continue
            results.append({
                "platform": "구글_트렌딩",
                "keyword": title_el.text or "",
                "score": rank,            # 순위를 점수 대용으로 사용
                "prev_score": 0.0,
                "change": 0.0,
                "change_pct": 0.0,
                "approx_traffic": (traffic_el.text if traffic_el is not None else ""),
                "collected_at": collected_at,
            })

        logger.info("Google Trends RSS 수집 완료: %d건", len(results))
        return results
    except Exception as exc:
        logger.error("Google Trends RSS 수집 실패: %s", exc)
        return []


def collect() -> List[Dict]:
    """
    Google Trends 전체 수집.
      - 패션 키워드 관심도 (pytrends, 실패 시 스킵)
      - 실시간 트렌딩 (RSS, 항상 시도)

    Returns:
        두 수집 결과를 합친 dict 목록.
    """
    keyword_data = fetch_keyword_interest()
    time.sleep(config.REQUEST_DELAY)
    trending_data = fetch_trending_rss()
    combined = keyword_data + trending_data
    logger.info("Google Trends 전체 수집 완료: 총 %d건", len(combined))
    return combined
