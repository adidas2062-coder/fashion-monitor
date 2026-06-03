"""
날씨 수집기 — Open-Meteo API (무료, 키 불필요).

서울 기준 오늘 날씨를 수집하고
패션 카테고리 수요 예측용 날씨 신호를 생성한다.

WMO 날씨 코드 → 날씨 상태 변환 포함.
"""

import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List

logger = logging.getLogger(__name__)

# 서울 좌표
_LAT = 37.5665
_LON = 126.9780

_API_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,apparent_temperature,weather_code,precipitation"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
    "&timezone=Asia%2FSeoul&forecast_days=3"
)

# WMO 코드 → 날씨 레이블
_WMO_LABELS = {
    0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림",
    45: "안개", 48: "안개",
    51: "이슬비", 53: "이슬비", 55: "이슬비",
    61: "비", 63: "비", 65: "폭우",
    71: "눈", 73: "눈", 75: "폭설",
    80: "소나기", 81: "소나기", 82: "폭풍우",
    95: "뇌우", 96: "뇌우", 99: "뇌우",
}

# 기온 → 패션 카테고리 수요 신호
def _category_signal(temp_max: float) -> Dict[str, str]:
    if temp_max >= 28:
        return {"상의": "반소매↑", "아우터": "수요감소", "바지": "숏팬츠↑"}
    elif temp_max >= 20:
        return {"상의": "긴소매/반소매 혼합", "아우터": "가벼운아우터↑", "바지": "코튼팬츠↑"}
    elif temp_max >= 12:
        return {"상의": "긴소매↑", "아우터": "재킷↑", "바지": "슬랙스↑"}
    elif temp_max >= 5:
        return {"상의": "니트↑", "아우터": "코트↑", "바지": "울/두꺼운팬츠↑"}
    else:
        return {"상의": "기모↑", "아우터": "패딩↑", "바지": "기모팬츠↑"}


def collect() -> Dict:
    """
    오늘 날씨 수집.

    Returns:
        {
          current_temp, apparent_temp, weather_label, precipitation,
          temp_max, temp_min, category_signal, forecast_3d, collected_at
        }
    """
    url = _API_URL.format(lat=_LAT, lon=_LON)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "fashion-monitor/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.error("날씨 수집 실패: %s", exc)
        return {}

    cur   = data.get("current", {})
    daily = data.get("daily",   {})

    temp_max = daily.get("temperature_2m_max", [0])[0]
    temp_min = daily.get("temperature_2m_min", [0])[0]
    wcode    = cur.get("weather_code", 0)

    # 3일 예보
    forecast_3d = []
    for i in range(min(3, len(daily.get("temperature_2m_max", [])))):
        forecast_3d.append({
            "date":      daily["time"][i] if "time" in daily else "",
            "temp_max":  daily["temperature_2m_max"][i],
            "temp_min":  daily["temperature_2m_min"][i],
            "rain":      daily["precipitation_sum"][i],
            "weather":   _WMO_LABELS.get(daily["weather_code"][i], "알수없음"),
        })

    result = {
        "current_temp":    cur.get("temperature_2m"),
        "apparent_temp":   cur.get("apparent_temperature"),
        "weather_label":   _WMO_LABELS.get(wcode, "알수없음"),
        "precipitation":   cur.get("precipitation", 0),
        "temp_max":        temp_max,
        "temp_min":        temp_min,
        "category_signal": _category_signal(temp_max),
        "forecast_3d":     forecast_3d,
        "collected_at":    datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    logger.info("날씨 수집 완료: %s°C (%s) → %s",
                result["current_temp"], result["weather_label"],
                result["category_signal"])
    return result
