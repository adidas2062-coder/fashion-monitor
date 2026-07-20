"""무신사 브랜드 랭킹 수집기 (subPan=brand)."""
import json, logging, time, urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import config

logger = logging.getLogger(__name__)

_API_URL = "https://api.musinsa.com/api2/hm/web/v5/pans/ranking?storeCode=musinsa&subPan=brand"
# 컨템포러리포멀 스타일 브랜드 랭킹 (브랜드 랭킹 상단 스타일 탭 sectionId=1060)
_FORMAL_API_URL = "https://api.musinsa.com/api2/hm/web/v5/pans/ranking/sections/1060?storeCode=musinsa&categoryCode="
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.musinsa.com/",
}

def _kst_today() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")

def collect(top_n: int = 30, api_url: str = _API_URL, label: str = "브랜드 랭킹") -> List[Dict]:
    """무신사 브랜드 랭킹 수집. api_url로 스타일(컨템포러리포멀 등) 랭킹도 수집 가능."""
    collected_at = _kst_today()
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(api_url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as e:
            logger.warning("%s 수집 실패 (시도 %d/3): %s", label, attempt, e)
            if attempt < 3: time.sleep(3)
            else: return []

    modules = data.get("data", {}).get("modules", [])
    results = []
    for m in modules:
        if m.get("type") != "RANKING_BRAND":
            continue
        rank = int(m.get("title", {}).get("rank", 0) or 0)
        if rank > top_n:
            continue
        fluct = m.get("title", {}).get("fluctuation", {})
        fluct_type = fluct.get("type", "NONE")
        raw_amt = str(fluct.get("amount", 0) or 0)
        if "천" in raw_amt:
            fluct_amt = int(float(raw_amt.replace("천", "").strip()) * 1000)
        elif "만" in raw_amt:
            fluct_amt = int(float(raw_amt.replace("만", "").strip()) * 10000)
        else:
            try:
                fluct_amt = int(float(raw_amt))
            except (ValueError, TypeError):
                fluct_amt = 0
        brand_name = m.get("title", {}).get("title", {}).get("text", "")
        labels = m.get("title", {}).get("labels", [])
        label_text = labels[0].get("text", "") if labels else ""
        url_val = m.get("title", {}).get("onClick", {}).get("url", "")
        results.append({
            "rank":             rank,
            "brand":            brand_name,
            "fluctuation_type": fluct_type,
            "fluctuation_amt":  fluct_amt,
            "label":            label_text,
            "url":              url_val,
            "collected_at":     collected_at,
        })

    results.sort(key=lambda x: x["rank"])
    logger.info("무신사 %s 수집 완료: %d건", label, len(results))
    return results


def collect_formal(top_n: int = 30) -> List[Dict]:
    """무신사 컨템포러리포멀 스타일 브랜드 랭킹 수집."""
    return collect(top_n=top_n, api_url=_FORMAL_API_URL, label="컨템포러리포멀 브랜드 랭킹")
