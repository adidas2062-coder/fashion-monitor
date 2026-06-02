"""
기획전 타이밍 감지기.

트렌드 급등(구글/네이버) + 랭킹 상승이 동시에 발생하면
"기획전 골든타임" 시그널을 생성한다.

감지 조건 (동시 충족):
  - 구글 또는 네이버 트렌드 전주 대비 +TREND_SURGE_THRESHOLD% 이상 상승
  - 무신사 랭킹 RANK_SURGE_THRESHOLD 계단 이상 상승 OR 신규 진입
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List

import config

logger = logging.getLogger(__name__)

# 기획전 테마 자동 생성 템플릿
_THEME_TEMPLATES = {
    "린넨": "여름 린넨 컬렉션",
    "데님": "데님 스타일링 기획전",
    "후드": "후드 & 스웨트 기획전",
    "조끼": "니트 조끼 레이어링 기획전",
    "슬랙스": "트렌디 슬랙스 기획전",
    "아우터": "시즌 아우터 기획전",
    "반팔": "여름 반팔 베스트",
    "와이드": "와이드 실루엣 기획전",
    "오버핏": "오버핏 트렌드 기획전",
}


def _suggest_theme(keyword: str) -> str:
    """키워드에서 기획전 추천 테마 생성."""
    for kw, theme in _THEME_TEMPLATES.items():
        if kw in keyword:
            return theme
    return f"{keyword} 기획전"


def _trend_surge_keywords(trend_data: List[Dict]) -> Dict[str, float]:
    """
    트렌드 데이터에서 급등 키워드 추출.
    Returns: {keyword: change_pct} — 임계값 이상인 항목만.
    """
    threshold = config.TREND_SURGE_THRESHOLD
    surging: Dict[str, float] = {}
    for item in trend_data:
        kw = item.get("keyword", "")
        pct = item.get("change_pct", 0.0)
        if pct >= threshold:
            # 같은 키워드가 여러 플랫폼에 있으면 최대값 유지
            if kw not in surging or pct > surging[kw]:
                surging[kw] = pct
    return surging


def _rank_surge_keywords(rank_diff_result: Dict) -> Dict[str, Dict]:
    """
    순위 변동 데이터에서 급등 키워드(상품명 기반) 추출.
    신규 진입 상품도 포함.
    Returns: {product_name: item_dict}
    """
    threshold = config.RANK_SURGE_THRESHOLD
    surging: Dict[str, Dict] = {}

    for item in rank_diff_result.get("new_entries", []):
        surging[item["product_name"]] = item

    for item in rank_diff_result.get("items", []):
        change = item.get("rank_change")
        if change is not None and change >= threshold:
            surging[item["product_name"]] = item

    return surging


def _keyword_overlap(
    trend_surging: Dict[str, float],
    rank_surging: Dict[str, Dict],
) -> List[Dict]:
    """
    트렌드 급등 키워드 ↔ 랭킹 상승 상품명 교차 탐색.
    상품명에 트렌드 키워드가 포함되면 시그널 생성.
    """
    signals: List[str] = []  # 이미 처리한 트렌드 키워드 중복 방지
    result: List[Dict] = []

    for trend_kw, trend_pct in trend_surging.items():
        if trend_kw in signals:
            continue
        for product_name, product_item in rank_surging.items():
            if trend_kw.replace("#", "") in product_name:
                signals.append(trend_kw)
                rank_change = product_item.get("rank_change")
                result.append({
                    "keyword":       trend_kw,
                    "trend_pct":     trend_pct,
                    "rank_change":   rank_change,
                    "is_new_entry":  rank_change is None,
                    "product_name":  product_name,
                    "brand":         product_item.get("brand", ""),
                    "category":      product_item.get("category", ""),
                    "theme":         _suggest_theme(trend_kw),
                    "collected_at":  datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                })
                break  # 한 트렌드 키워드당 첫 번째 매칭만

    return result


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def detect(
    trend_data: List[Dict],
    rank_diff_result: Dict,
) -> List[Dict]:
    """
    기획전 타이밍 시그널 감지.

    Args:
        trend_data:       google_trends/naver_datalab collect() 결과 통합 목록.
        rank_diff_result: rank_diff.analyze() 반환 dict.

    Returns:
        시그널 dict 목록 (없으면 빈 리스트).
        각 항목: keyword / trend_pct / rank_change / is_new_entry /
                 product_name / brand / category / theme / collected_at
    """
    trend_surging = _trend_surge_keywords(trend_data)
    rank_surging  = _rank_surge_keywords(rank_diff_result)

    if not trend_surging:
        logger.info("기획전 시그널 없음 — 트렌드 급등 키워드 없음")
        return []
    if not rank_surging:
        logger.info("기획전 시그널 없음 — 랭킹 급등 상품 없음")
        return []

    signals = _keyword_overlap(trend_surging, rank_surging)

    if signals:
        for s in signals:
            rank_txt = "NEW" if s["is_new_entry"] else f"▲{s['rank_change']}"
            logger.warning(
                "🎯 기획전 시그널 감지! [%s] 트렌드+%s%% | 랭킹%s | 추천테마: %s",
                s["keyword"], s["trend_pct"], rank_txt, s["theme"],
            )
    else:
        logger.info("기획전 시그널 없음 — 트렌드↔랭킹 키워드 교차 매칭 없음")

    return signals
