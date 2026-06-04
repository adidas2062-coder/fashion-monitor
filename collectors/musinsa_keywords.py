"""
무신사 실시간 검색어 랭킹 수집기.

무신사 랭킹 페이지의 검색어 탭(subPan=keyword)에서
순위·변동폭·키워드를 수집한다.
"""

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

_API_URL = "https://api.musinsa.com/api2/hm/web/v5/pans/ranking?storeCode=musinsa&subPan=keyword"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.musinsa.com/",
}
_RETRY_MAX = 3
_RETRY_DELAY = 3.0

_FLUCTUATION_LABEL = {
    "UP":   "▲",
    "DOWN": "▼",
    "NEW":  "NEW",
    "NONE": "→",
}



def _kst_today() -> str:
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")

def collect(top_n: int = 30) -> List[Dict]:
    """
    무신사 실시간 검색어 랭킹 수집.

    Returns:
        순위 오름차순 검색어 dict 목록.
        각 항목: rank / keyword / fluctuation_type / fluctuation_amount /
                 fluctuation_label / url / collected_at
    """
    collected_at = _kst_today()

    for attempt in range(1, _RETRY_MAX + 1):
        try:
            req = urllib.request.Request(_API_URL, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as exc:
            logger.warning("검색어 랭킹 수집 실패 (시도 %d/%d): %s", attempt, _RETRY_MAX, exc)
            if attempt < _RETRY_MAX:
                time.sleep(_RETRY_DELAY)
            else:
                return []

    modules = data.get("data", {}).get("modules", [])
    results: List[Dict] = []

    for m in modules:
        if m.get("type") != "RANKING_SEARCH":
            continue
        rank = int(m.get("rank", 0))
        if rank > top_n:
            continue

        fluct      = m.get("fluctuation", {})
        fluct_type = fluct.get("type", "NONE")
        fluct_amt  = int(fluct.get("amount", 0)) if fluct.get("amount") else 0
        keyword    = m.get("title", {}).get("text", "")
        url        = m.get("onClick", {}).get("url", "")

        results.append({
            "platform":          "무신사_검색어",
            "rank":              rank,
            "keyword":           keyword,
            "fluctuation_type":  fluct_type,
            "fluctuation_amount": fluct_amt,
            "fluctuation_label": _FLUCTUATION_LABEL.get(fluct_type, "→"),
            "url":               url,
            "collected_at":      collected_at,
        })

    results.sort(key=lambda x: x["rank"])
    logger.info("무신사 검색어 랭킹 수집 완료: %d건", len(results))
    return results
