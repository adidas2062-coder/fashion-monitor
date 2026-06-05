"""무신사 기획전/세일 섹션 모니터링."""
import json, logging, time, urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, List
import config

logger = logging.getLogger(__name__)

_API_URL = "https://api.musinsa.com/api2/hm/web/v3/pans/sale/modules?storeCode=musinsa"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.musinsa.com/main/musinsa/sale",
}

def _kst_today() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")

def collect() -> List[Dict]:
    """무신사 현재 진행 중인 기획전/세일 섹션 수집."""
    collected_at = _kst_today()
    try:
        req = urllib.request.Request(_API_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error("무신사 기획전 수집 실패: %s", e)
        return []

    modules = data.get("data", {}).get("modules", [])
    results = []
    for idx, m in enumerate(modules):
        # 섹션 타이틀 추출 — title.title.text 또는 section_title(eventLog)
        title_raw = m.get("title", {})
        if isinstance(title_raw, dict):
            inner = title_raw.get("title", {})
            title = inner.get("text", "") if isinstance(inner, dict) else str(inner)
        else:
            title = str(title_raw or "")
        title = title.replace("\n", " ").strip()

        # 폴백: 첫 아이템 eventLog에서 section_title 추출
        if not title:
            items_tmp = m.get("items", [])
            if items_tmp:
                payload = items_tmp[0].get("onClick",{}).get("eventLog",{}).get("ga4",{}).get("payload",{})
                title = payload.get("section_title","")

        if not title:
            continue

        items = m.get("items", [])
        item_count = len(items)

        # 대표 상품 TOP 3
        top_items = []
        for item in items[:3]:
            info = item.get("info", {})
            brand = info.get("brandName", "")
            name  = info.get("productName", "")
            price = info.get("finalPrice", 0)
            disc  = info.get("discountRatio", 0)
            url_val = item.get("onClick", {}).get("url", "")
            if brand or name:
                top_items.append({
                    "brand": brand,
                    "product_name": name,
                    "price": price,
                    "discount_rate": disc,
                    "url": url_val,
                })

        results.append({
            "index":       idx + 1,
            "title":       title,
            "item_count":  item_count,
            "top_items":   top_items,
            "platform":    "무신사",
            "collected_at": collected_at,
        })

    logger.info("무신사 기획전 수집 완료: %d개 섹션", len(results))
    return results
