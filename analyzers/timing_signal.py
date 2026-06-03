"""
기획전 타이밍 시그널 감지기 (강화판).

감지 지표:
  1. 트렌드 급등      — 구글/네이버 전주 대비 +TREND_SURGE_THRESHOLD% 이상
  2. 랭킹 급등        — RANK_SURGE_THRESHOLD 계단 이상 상승 OR 신규 진입
  3. 할인율 급등      — 카테고리 평균 할인율이 전날 대비 5%p 이상 상승 (경쟁사 프로모션 감지)
  4. 품절 비율 급증   — 카테고리 내 품절 상품 20% 이상 (수요 과잉)
  5. 복수 카테고리 교차 — 같은 키워드가 상의+아우터/바지 동시 급등
  6. YoY 비교         — 작년 동기 동일 키워드 랭킹 대비 순위 상승

신뢰도 점수 (0~100):
  트렌드(30점) + 랭킹(25점) + 할인율(15점) + 품절(10점) + 복수교차(10점) + YoY(10점)

레벨:
  🔴 긴급  80점 이상
  🟡 주의  50~79점
  🟢 참고  30~49점
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)

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
    "니트": "니트 컬렉션 기획전",
    "셔츠": "셔츠 스타일링 기획전",
    "재킷": "재킷 기획전",
}

_MAIN_CATS = ["상의", "아우터", "바지"]


# ── 지표별 감지 함수 ──────────────────────────────────────────────────────────

def _trend_surge(trend_data: List[Dict]) -> Dict[str, float]:
    """급등 키워드 → 변화율 맵."""
    threshold = config.TREND_SURGE_THRESHOLD
    result: Dict[str, float] = {}
    for t in trend_data:
        kw  = t.get("keyword", "").replace("#", "")
        pct = t.get("change_pct", 0.0)
        if pct >= threshold:
            if kw not in result or pct > result[kw]:
                result[kw] = pct
    return result


def _rank_surge(rank_diff_result: Dict) -> Dict[str, Dict]:
    """급등/신규 진입 상품명 → 상품 정보 맵."""
    threshold = config.RANK_SURGE_THRESHOLD
    result: Dict[str, Dict] = {}
    for item in rank_diff_result.get("new_entries", []):
        result[item["product_name"]] = item
    for item in rank_diff_result.get("items", []):
        change = item.get("rank_change")
        if change is not None and change >= threshold:
            result[item["product_name"]] = item
    return result


def _discount_surge(rank_diff_result: Dict) -> Dict[str, float]:
    """카테고리별 평균 할인율 — 5%p 이상 올라간 카테고리 반환."""
    items = rank_diff_result.get("items", [])
    cat_discounts: Dict[str, List[float]] = {}
    for item in items:
        cat  = item.get("category", "")
        disc = item.get("discount_rate", 0)
        for main in _MAIN_CATS:
            if cat.startswith(main):
                cat_discounts.setdefault(main, []).append(disc)
                break

    surging: Dict[str, float] = {}
    for cat, discounts in cat_discounts.items():
        if not discounts:
            continue
        avg = sum(discounts) / len(discounts)
        if avg >= 5.0:      # 평균 5% 이상 할인 → 프로모션 활성
            surging[cat] = round(avg, 1)
    return surging


def _soldout_ratio(rank_diff_result: Dict) -> Dict[str, float]:
    """카테고리별 품절 비율 — 20% 이상인 카테고리 반환."""
    items = rank_diff_result.get("items", [])
    cat_total: Dict[str, int]   = {}
    cat_sold:  Dict[str, int]   = {}
    for item in items:
        cat = item.get("category", "")
        for main in _MAIN_CATS:
            if cat.startswith(main):
                cat_total[main] = cat_total.get(main, 0) + 1
                if item.get("is_sold_out"):
                    cat_sold[main] = cat_sold.get(main, 0) + 1
                break

    result: Dict[str, float] = {}
    for cat, total in cat_total.items():
        ratio = (cat_sold.get(cat, 0) / total * 100) if total > 0 else 0
        if ratio >= 20.0:
            result[cat] = round(ratio, 1)
    return result


def _cross_category(trend_surging: Dict[str, float], rank_surging: Dict[str, Dict]) -> List[str]:
    """복수 카테고리에서 동시에 급등한 키워드 목록."""
    cross: List[str] = []
    for kw in trend_surging:
        matched_cats = set()
        for product_name, item in rank_surging.items():
            if kw in product_name:
                cat = item.get("category", "")
                for main in _MAIN_CATS:
                    if cat.startswith(main):
                        matched_cats.add(main)
                        break
        if len(matched_cats) >= 2:
            cross.append(kw)
    return cross


def _yoy_compare(keyword: str, archive_data: Optional[List[Dict]]) -> Optional[int]:
    """작년 동기 대비 해당 키워드 최고 순위 변화 (양수 = 올해가 더 높음)."""
    if not archive_data:
        return None
    last_year_ranks = [
        g["rank"] for g in archive_data
        if keyword in g.get("product_name", "")
    ]
    if not last_year_ranks:
        return None
    return min(last_year_ranks)   # 작년 최고 순위 반환 (낮을수록 좋음)


# ── 점수 계산 ─────────────────────────────────────────────────────────────────

def _score(
    trend_pct: float,
    rank_change: Optional[int],
    is_new: bool,
    discount_surge: bool,
    soldout: bool,
    is_cross: bool,
    yoy_rank: Optional[int],
    current_rank: Optional[int],
) -> int:
    s = 0

    # 트렌드 (30점)
    if trend_pct >= 50:   s += 30
    elif trend_pct >= 30: s += 20
    else:                 s += 10

    # 랭킹 (25점)
    if is_new:            s += 25
    elif rank_change and rank_change >= 10: s += 25
    elif rank_change and rank_change >= 5:  s += 15
    else:                 s += 5

    # 할인율 급등 (15점)
    if discount_surge:    s += 15

    # 품절 (10점)
    if soldout:           s += 10

    # 복수 카테고리 교차 (10점)
    if is_cross:          s += 10

    # YoY (10점) — 올해 순위가 작년보다 좋을 때
    if yoy_rank and current_rank and current_rank < yoy_rank:
        s += 10

    return min(s, 100)


def _level(score: int) -> str:
    if score >= 80:   return "🔴 긴급"
    elif score >= 50: return "🟡 주의"
    else:             return "🟢 참고"


def _suggest_theme(keyword: str) -> str:
    for kw, theme in _THEME_TEMPLATES.items():
        if kw in keyword:
            return theme
    return f"{keyword} 기획전"


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def detect(
    trend_data: List[Dict],
    rank_diff_result: Dict,
    archive_data: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    기획전 타이밍 시그널 감지.

    Args:
        trend_data:       google_trends + naver_datalab 통합 데이터.
        rank_diff_result: rank_diff.analyze() 반환 dict.
        archive_data:     musinsa_archive.collect() 반환 (YoY용, 없으면 스킵).

    Returns:
        시그널 dict 목록 (신뢰도 점수 내림차순 정렬).
    """
    trend_surging    = _trend_surge(trend_data)
    rank_surging     = _rank_surge(rank_diff_result)
    discount_cats    = _discount_surge(rank_diff_result)
    soldout_cats     = _soldout_ratio(rank_diff_result)
    cross_keywords   = _cross_category(trend_surging, rank_surging)
    collected_at     = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not trend_surging:
        logger.info("기획전 시그널 없음 — 트렌드 급등 키워드 없음")
        return []

    signals: List[Dict] = []
    seen_keywords: set = set()

    for trend_kw, trend_pct in trend_surging.items():
        if trend_kw in seen_keywords:
            continue

        # 랭킹 급등 상품 중 트렌드 키워드 포함 검색
        matched_product = None
        matched_item = None
        for product_name, item in rank_surging.items():
            if trend_kw in product_name:
                matched_product = product_name
                matched_item    = item
                break

        # 트렌드 급등만 있어도 낮은 점수로 시그널 생성
        rank_change   = matched_item.get("rank_change") if matched_item else None
        is_new        = matched_item is None or rank_change is None
        current_rank  = matched_item.get("rank") if matched_item else None
        cat           = matched_item.get("category", "") if matched_item else ""

        # 카테고리 대분류 파악
        main_cat = next((m for m in _MAIN_CATS if cat.startswith(m)), "")

        discount_surge = main_cat in discount_cats
        soldout        = main_cat in soldout_cats
        is_cross       = trend_kw in cross_keywords
        yoy_rank       = _yoy_compare(trend_kw, archive_data)

        score = _score(
            trend_pct, rank_change, matched_item is None,
            discount_surge, soldout, is_cross, yoy_rank, current_rank,
        )

        if score < 30:
            continue   # 30점 미만은 노이즈로 제외

        seen_keywords.add(trend_kw)

        # 추가 이슈 목록
        issues: List[str] = []
        if discount_surge:
            issues.append(f"할인율 급등 ({discount_cats[main_cat]:.1f}%)")
        if soldout:
            issues.append(f"품절 {soldout_cats[main_cat]:.0f}%")
        if is_cross:
            issues.append("복수 카테고리 동시 급등")
        if yoy_rank and current_rank:
            diff = yoy_rank - current_rank
            if diff > 0:
                issues.append(f"작년 동기 대비 ▲{diff}위 상승")

        signal = {
            "keyword":       trend_kw,
            "trend_pct":     trend_pct,
            "rank_change":   rank_change,
            "is_new_entry":  matched_item is None,
            "product_name":  matched_product or "",
            "brand":         matched_item.get("brand", "") if matched_item else "",
            "category":      cat,
            "theme":         _suggest_theme(trend_kw),
            "score":         score,
            "level":         _level(score),
            "issues":        issues,
            "discount_surge": discount_surge,
            "soldout":       soldout,
            "is_cross_cat":  is_cross,
            "yoy_last_rank": yoy_rank,
            "collected_at":  collected_at,
        }
        signals.append(signal)

        rank_txt = "NEW" if matched_item is None else (
            f"▲{rank_change}" if rank_change else "-"
        )
        logger.warning(
            "%s 기획전 시그널! [%s] 트렌드+%.0f%% | 랭킹%s | 점수:%d | 이슈:%s",
            _level(score), trend_kw, trend_pct, rank_txt, score, issues,
        )

    signals.sort(key=lambda x: x["score"], reverse=True)

    if not signals:
        logger.info("기획전 시그널 없음 (점수 30점 미만)")

    return signals
