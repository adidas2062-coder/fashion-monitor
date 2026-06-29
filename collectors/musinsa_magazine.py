"""무신사 매거진/콘텐츠 수집 — 콘텐츠 탭 API."""
import json
import logging
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)

_API = (
    "https://api.musinsa.com/api2/hm/web/v2/pans/contents/modules"
    "?storeCode=musinsa&gf=M&size=10&index={index}&page=1"
)
_CONTENT_MODULES = {"CAROUSEL_ONEROW_STEP4", "CAROUSEL_ONEROW_SNAPPING"}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.musinsa.com/",
    "Accept": "application/json",
}


def collect(max_index: int = 5) -> List[Dict]:
    """무신사 매거진/콘텐츠 목록 수집.

    index 1~max_index 구간을 순회하며 STEP4·SNAPPING 모듈의
    콘텐츠(룩북·스페셜·에디션 등)를 수집한다.
    """
    collected_at = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")
    seen_ids: set = set()
    results: List[Dict] = []

    for idx in range(1, max_index + 1):
        url = _API.format(index=idx)
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("매거진 index=%d 수집 실패: %s", idx, e)
            continue

        for module in data.get("data", {}).get("modules", []):
            if module.get("type") not in _CONTENT_MODULES:
                continue
            for item in module.get("items", []):
                payload = (
                    item.get("impressionEventLog", {})
                        .get("ga4", {})
                        .get("payload", {})
                )
                content_id = payload.get("content_id", "")
                if not content_id or content_id in seen_ids:
                    continue
                seen_ids.add(content_id)

                info = item.get("info", {})
                results.append({
                    "content_id":   content_id,
                    "title":        info.get("title", {}).get("text", ""),
                    "sub_title":    info.get("subTitle", {}).get("text", ""),
                    "content_type": payload.get("content_type", ""),
                    "brand":        info.get("brandInfo", {}).get("brandName", {}).get("text", ""),
                    "view_count":   info.get("viewCount", {}).get("text", ""),
                    "date":         (info.get("releaseDateTime", {}).get("dateTime") or "")[:10],
                    "url":          item.get("onClick", {}).get("url", ""),
                    "collected_at": collected_at,
                })

    logger.info("무신사 매거진 수집 완료: %d건", len(results))
    return results
