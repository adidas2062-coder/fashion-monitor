"""29CM 에디션/기획전 모니터링."""
import json, logging, urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)

_API_URL = "https://cache.29cm.co.kr/edition/list/?limit=10&page=1"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.29cm.co.kr/",
}

def _kst_today() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")

def collect() -> List[Dict]:
    """29CM 최신 에디션/기획전 목록 수집."""
    collected_at = _kst_today()
    try:
        req = urllib.request.Request(_API_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error("29CM 에디션 수집 실패: %s", e)
        return []

    results_raw = data.get("results", [])
    results = []
    for item in results_raw[:10]:
        title     = item.get("list_title", "") or item.get("title", "")
        sub_title = item.get("list_sub_title", "") or item.get("sub_title", "")
        list_no   = item.get("list_no") or item.get("no")
        img_url   = item.get("list_img", "") or item.get("img_url", "")
        updated   = item.get("updated_timestamp", "")[:10] if item.get("updated_timestamp") else ""

        if not title:
            continue

        results.append({
            "list_no":     list_no,
            "title":       title,
            "sub_title":   sub_title,
            "url":         f"https://www.29cm.co.kr/store/edition/{list_no}" if list_no else "",
            "image_url":   img_url,
            "updated_at":  updated,
            "platform":    "29CM",
            "collected_at": collected_at,
        })

    logger.info("29CM 에디션 수집 완료: %d개", len(results))
    return results
