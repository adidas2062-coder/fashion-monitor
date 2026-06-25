"""
기획전 타이밍 시그널 감지기 (강화판).

감지 지표:
  1. 트렌드 급등      — 구글/네이버 전주 대비 +TREND_SURGE_THRESHOLD% 이상
  2. 랭킹 급등        — RANK_SURGE_THRESHOLD 계단 이상 상승 OR 신규 진입
  3. 할인율 급등      — 카테고리 평균 할인율이 전날 대비 5%p 이상 상승 (경쟁사 프로모션 감지)
  4. 품절 비율 급증   — 카테고리 내 품절 상품 20% 이상 (수요 과잉)
  5. 복수 카테고리 교차 — 같은 키워드가 상의+아우터/바지 동시 급등
  6. YoY 비교         — 작년 동기 동일 키워드 랭킹 대비 순위 상승
  7. 할인 지속성      — snapshot_store 히스토리 기준 평균 할인율이 N일 연속 상승 중인지
  8. 가격대 경쟁력    — 매칭 상품 가격이 동일 카테고리 평균가 대비 ±30% 이상 벗어났는데도
                       랭킹이 급등(저가 회전 수요 또는 고가 프레스티지 수요로 추정)

신뢰도 점수 (0~100):
  트렌드(30점) + 랭킹(25점) + 할인율(15점) + 품절(10점) + 복수교차(10점) + YoY(10점)
  + 할인 지속성 보너스(최대 5점) + 가격대 경쟁력 보너스(최대 3점, 가산 한도 포함 100점 캡)
  - 계절 역행 페널티(기온/카테고리 기준 점진적, 최대 -20점)
  ± 백테스트 피드백 가중치(키워드 패턴별 과거 적중률 기반, 최대 ±10점)

레벨:
  🔴 긴급  80점 이상
  🟡 주의  50~79점
  🟢 참고  30~49점

각 시그널 dict에는 점수 산출 근거를 투명하게 보여주는 필드가 포함된다:
  - score_breakdown: 지표별 기여 점수 dict (예: {"trend": 30, "rank": 25, ...})
  - score_range: 보강 지표 개수 기반 점수 상/하한 휴리스틱 {"low": int, "high": int}
    (통계적 신뢰구간이 아님 — 표본/분산/백테스트 적중률을 사용하지 않는다.
    confidence_band는 동일 값을 가리키는 하위호환용 별칭이다)
  - evidence_detail: "왜 이 점수인지"를 설명하는 한국어 문장 목록
  - next_checks: MD가 기획전 오픈 전 추가로 확인해야 할 체크리스트
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)


def _normalize_keyword_for_matching(keyword: str) -> str:
    """공백/특수문자를 제거해 키워드를 정규화한다.

    signal_backtest.keyword_hit_weights()가 만드는 가중치 맵의 key와 동일한
    정규화 규칙(영문/숫자/한글만 남기고 공백·특수문자 제거)을 적용해야, "린넨 셔츠"
    처럼 공백이 들어간 키워드와 "린넨셔츠"가 서로 다른 키로 취급되어 가중치가
    매칭되지 않는 문제를 막을 수 있다.
    """
    return re.sub(r"[^\w가-힣]", "", keyword or "").strip()

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

_WINTER_KEYWORDS = ["후드", "스웨트", "기모", "니트", "패딩", "코트", "플리스", "맨투맨", "조끼"]
_SUMMER_KEYWORDS = ["반팔", "린넨", "숏팬츠", "민소매", "나시"]

# 카테고리별 계절 감도 — 동일 기온이라도 카테고리별 역행 페널티 강도가 다르다.
# (예: 패딩/코트는 여름에 더 강하게 역행으로 취급, 니트/조끼는 간절기 수요가 있어 약하게 취급)
_WINTER_SEASON_WEIGHT = {
    "패딩": 1.2, "코트": 1.2, "기모": 1.1, "플리스": 1.0,
    "맨투맨": 0.8, "후드": 0.8, "스웨트": 0.8, "니트": 0.7, "조끼": 0.6,
}
_SUMMER_SEASON_WEIGHT = {
    "린넨": 1.2, "반팔": 1.1, "숏팬츠": 1.0, "나시": 1.1, "민소매": 1.0,
}
# 키워드가 _WINTER_KEYWORDS/_SUMMER_KEYWORDS에 없을 때 적용할 기본 감도(완전히 무시되지 않도록).
_DEFAULT_WINTER_WEIGHT = 0.5
_DEFAULT_SUMMER_WEIGHT = 0.5

# 카테고리 대분류별 계절 민감도 배수 — 동일 키워드·기온이라도 카테고리에 따라
# 역행 신호의 강도가 다르다. 예: "니트"가 아우터(코트형)로 분류되면 상의보다
# 보온성 비중이 커서 더 강하게 역행 취급, 바지는 계절 영향이 상대적으로 약함.
_CATEGORY_SEASON_MULTIPLIER = {
    "아우터": 1.2,
    "상의": 1.0,
    "바지": 0.7,
}


def _category_multiplier(category: str) -> float:
    """카테고리 대분류 문자열에서 계절 민감도 배수를 찾는다.

    config.example.py의 MUSINSA_CATEGORIES 키 형식은 항상 "{대분류}_{세분류}"
    (예: "상의_전체", "상의_후드티셔츠", "아우터_무스탕퍼", "바지_데님팬츠")이므로,
    "상의"/"아우터"/"바지"로 시작하는 문자열 매칭이 실제 수집 데이터와 일치한다.
    세분류가 무엇이든(예: "아우터_무스탕퍼") 대분류 접두사만으로 항상 배수가
    정확히 매칭되며, "아우터"라는 대분류 자체가 존재하지 않아 배수가 항상
    1.0(중립)으로 빠지는 일은 없다.
    """
    if not category:
        return 1.0
    for main_cat, mult in _CATEGORY_SEASON_MULTIPLIER.items():
        if category.startswith(main_cat):
            return mult
    return 1.0


# ── 지표별 감지 함수 ──────────────────────────────────────────────────────────


def _kst_today() -> str:
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")

def _trend_surge(trend_data: List[Dict]) -> Dict[str, float]:
    """급등 키워드 → 변화율 맵."""
    threshold = config.TREND_SURGE_THRESHOLD
    excluded = set(getattr(config, "NON_PRODUCT_TREND_KEYWORDS", []))
    result: Dict[str, float] = {}
    for t in trend_data:
        kw  = t.get("keyword", "").replace("#", "")
        if kw in excluded:
            continue
        pct = t.get("change_pct", 0.0)
        if pct >= threshold:
            if kw not in result or pct > result[kw]:
                result[kw] = pct
    return result


def _rank_surge(rank_diff_result: Dict) -> Dict[str, Dict]:
    """급등/신규 진입 상품명 → 상품 정보 맵.

    각 상품 dict에는 실제 신규 진입(new_entries 출처) 여부를 구분하기 위한
    내부 플래그 "_is_true_new_entry"를 추가한다. 트렌드 키워드가 단순히
    rank_surging에 매칭되지 않는 경우(즉 랭킹 데이터가 전혀 없는 경우)와
    "실제 무신사/29CM 랭킹에 신규로 진입한 상품"을 혼동하지 않기 위함이다.
    """
    threshold = config.RANK_SURGE_THRESHOLD
    result: Dict[str, Dict] = {}
    for item in rank_diff_result.get("new_entries", []):
        merged = dict(item)
        merged["_is_true_new_entry"] = True
        result[item["product_name"]] = merged
    for item in rank_diff_result.get("items", []):
        change = item.get("rank_change")
        if change is not None and change >= threshold:
            merged = dict(item)
            merged["_is_true_new_entry"] = False
            result[item["product_name"]] = merged
    return result


def _avg_discount_by_category(items: List[Dict]) -> Dict[str, float]:
    """카테고리 대분류별 평균 할인율(%)을 계산한다."""
    cat_discounts: Dict[str, List[float]] = {}
    for item in items:
        cat  = item.get("category", "")
        disc = item.get("discount_rate", 0)
        for main in _MAIN_CATS:
            if cat.startswith(main):
                cat_discounts.setdefault(main, []).append(disc)
                break
    return {
        cat: round(sum(discounts) / len(discounts), 1)
        for cat, discounts in cat_discounts.items() if discounts
    }


def _discount_surge(
    rank_diff_result: Dict,
    ranking_history: Optional[List[List[Dict]]] = None,
) -> Tuple[Dict[str, float], bool]:
    """카테고리별 할인율 '급등'을 감지한다.

    ranking_history(최근 일자 오름차순 스냅샷)가 2일 이상 있으면 "오늘 평균
    할인율 - 어제 평균 할인율"이 +5%p 이상인 카테고리만 급등으로 판정한다(전날
    대비 비교라는 본래 정의와 일치). 히스토리가 부족하면(첫 실행/수집 누락 등
    2일 미만) "오늘 평균 할인율 자체가 5% 이상이면 급등"이라는 절대 임계값
    추정은 더 이상 사용하지 않는다 — 상시 할인 카테고리(예: 시즌 막바지 이월
    상품군)가 항상 급등으로 오인되는 문제가 있었기 때문이다. 이 경우 급등
    판정은 빈 dict(0점 처리)로 반환하고, 두 번째 반환값(insufficient_history)을
    True로 표시해 호출부가 "데이터 부족, 확인 필요"를 next_checks에 노출하게 한다.

    Returns:
        (surging, insufficient_history) — surging은 카테고리→증가폭(%p) dict,
        insufficient_history는 히스토리가 부족해 판정을 보수적으로(0점) 처리했는지 여부.
    """
    today_avg = _avg_discount_by_category(rank_diff_result.get("items", []))

    if ranking_history and len(ranking_history) >= 2:
        yesterday_avg = _avg_discount_by_category(ranking_history[-2])
        surging: Dict[str, float] = {}
        for cat, avg in today_avg.items():
            delta = avg - yesterday_avg.get(cat, avg)
            if delta >= 5.0:
                surging[cat] = round(delta, 1)
        return surging, False

    # 히스토리 부족(첫 실행/수집 누락) — 절대 임계값으로 추정하지 않고 보수적으로
    # "급등 없음"으로 처리한다. 상시 할인 카테고리를 급등으로 오인하는 것보다
    # 점수를 0으로 유지하고 MD에게 데이터 부족을 알리는 쪽이 안전하다.
    return {}, True


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


def _category_demand_weight(rank_diff_result: Dict) -> Dict[str, float]:
    """대분류(상의/아우터/바지)별 '오늘 얼마나 활발히 움직이는지'를 가중치로 환산한다.

    예: 더운 날 반팔티(상의)는 신규진입·순위상승이 활발한데 아우터는 거의
    안 움직인다면, 같은 "1위"라도 아우터 1위가 상의 1위보다 약한 신호다.
    무신사에 카테고리를 안 가린 진짜 통합 랭킹이 없어 정확한 비중을 직접
    구할 수는 없으므로, 이미 수집된 카테고리별 신규진입/순위상승 비율을
    근사 지표로 쓴다 — 평균보다 활발한 카테고리는 가중치를 올리고, 거의
    안 움직이는 카테고리는 낮춘다. 표본이 적은 초기에는 변동이 과장될 수
    있어 0.6~1.6 범위로 clip한다.
    """
    items = rank_diff_result.get("items", [])
    if not items:
        return {}

    moving: Dict[str, int] = defaultdict(int)
    total: Dict[str, int] = defaultdict(int)
    for item in items:
        cat = item.get("category", "") or ""
        main = next((m for m in _MAIN_CATS if cat.startswith(m)), "")
        if not main:
            continue
        total[main] += 1
        rank_change = item.get("rank_change")
        is_new_entry = item.get("comparison_available") and rank_change is None
        if is_new_entry or (rank_change or 0) > 0:
            moving[main] += 1

    shares = {cat: moving.get(cat, 0) / total[cat] for cat in total if total[cat]}
    if not shares:
        return {}
    avg_share = sum(shares.values()) / len(shares)
    if avg_share == 0:
        return {cat: 1.0 for cat in shares}
    return {cat: max(0.6, min(1.6, round(share / avg_share, 2))) for cat, share in shares.items()}


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


def _weather_conflict(keyword: str, temp_max: Optional[float]) -> Optional[str]:
    """현재 기온과 키워드 계절성이 반대 방향이면 경고 문구 반환 (하위호환용 on/off 판정)."""
    if temp_max is None:
        return None
    if temp_max >= 28 and any(w in keyword for w in _WINTER_KEYWORDS):
        return f"⚠️ 계절 역행 (최고 {temp_max:.0f}도) — 선행수요 여부 확인 필요"
    if temp_max <= 8 and any(w in keyword for w in _SUMMER_KEYWORDS):
        return f"⚠️ 계절 역행 (최고 {temp_max:.0f}도)"
    return None


def _seasonal_adjustment(
    keyword: str, temp_max: Optional[float], category: str = ""
) -> Tuple[float, Optional[str]]:
    """기온 구간 + 카테고리 감도에 따른 점진적 계절 보정값을 계산한다.

    단순 -20 on/off 대신, 기온이 기준선(겨울 24도/여름 14도)에서 얼마나 벗어났는지,
    키워드별 계절 감도 가중치(_WINTER_SEASON_WEIGHT/_SUMMER_SEASON_WEIGHT)와
    카테고리 대분류별 계절 민감도 배수(_CATEGORY_SEASON_MULTIPLIER, 예: 아우터는
    강하게·바지는 약하게)를 곱해 -20 ~ +5 사이의 연속값을 반환한다. 같은 키워드라도
    카테고리가 다르면(예: "니트"가 상의 vs 아우터) 보정값이 달라진다.
    키워드가 사전 목록에 없어도 부분 일치가 없으면 기본 감도(_DEFAULT_*_WEIGHT)를
    적용해 누락 없이 계절 역행 가능성을 검토한다. 기온이 계절과 맞아떨어지면
    소폭 보너스(+5)도 부여한다.

    Args:
        keyword: 트렌드 키워드.
        temp_max: 오늘 최고기온(섭씨). None이면 보정 없음(0.0).
        category: 상품 카테고리 대분류(예: "상의_전체", "아우터"). 빈 문자열이면
            배수 1.0(중립)을 적용한다.

    Returns:
        (adjustment, explanation) — adjustment는 점수에 그대로 가산(음수=페널티).
    """
    if temp_max is None:
        return 0.0, None

    cat_mult = _category_multiplier(category)

    # 겨울 키워드인데 기온이 높은 경우 — 역행 강도는 24도를 넘는 정도에 순수 비례.
    # (기준점 24도에서는 penalty가 정확히 0에서 시작해야 23.9도→0점, 24.0도→큰 음수로
    # 점프하는 불연속이 생기지 않는다. 과거에는 기준 통과 즉시 고정 베이스 페널티
    # (4.0*weight)가 더해져 23도에서 24도로 1도만 올라가도 -5.8점으로 급락했었다.)
    winter_hits = [w for w in _WINTER_KEYWORDS if w in keyword]
    if winter_hits and temp_max >= 24:
        # winter_hits는 이 분기에서 항상 비어있지 않으므로(if winter_hits 검사 통과),
        # max()는 항상 실제 키워드 가중치 중 하나를 반환한다(default는 도달 불가 안전장치).
        weight = max(_WINTER_SEASON_WEIGHT.get(w, 0.7) for w in winter_hits) * cat_mult
        over = temp_max - 24  # 24도부터 점진적으로 역행 신호 시작 (24도=0)
        penalty = -min(20.0, over * 1.3 * weight)
        penalty = round(penalty, 1)
        if penalty <= -2:
            return penalty, f"⚠️ 계절 역행 (최고 {temp_max:.0f}도, {category or '카테고리 미지정'}, 보정 {penalty:+.1f}점) — 선행수요 여부 확인 필요"
        return penalty, None

    # 여름 키워드인데 기온이 낮은 경우 — 14도 기준점에서 0으로 시작.
    summer_hits = [w for w in _SUMMER_KEYWORDS if w in keyword]
    if summer_hits and temp_max <= 14:
        # summer_hits도 동일하게 이 분기에서는 항상 비어있지 않다.
        weight = max(_SUMMER_SEASON_WEIGHT.get(w, 0.8) for w in summer_hits) * cat_mult
        under = 14 - temp_max
        penalty = -min(20.0, under * 1.3 * weight)
        penalty = round(penalty, 1)
        if penalty <= -2:
            return penalty, f"⚠️ 계절 역행 (최고 {temp_max:.0f}도, {category or '카테고리 미지정'}, 보정 {penalty:+.1f}점)"
        return penalty, None

    # 계절이 맞아떨어지는 경우 — 소폭 보너스 (제철 수요 확인 신호).
    if winter_hits and temp_max <= 12:
        return 5.0, f"✅ 계절 부합 (최고 {temp_max:.0f}도) — 제철 수요로 판단"
    if summer_hits and temp_max >= 26:
        return 5.0, f"✅ 계절 부합 (최고 {temp_max:.0f}도) — 제철 수요로 판단"

    # 사전 목록(겨울/여름 키워드)에 전혀 매칭되지 않는 키워드(예: "레이어드", "데님 팬츠")는
    # 보온성/계절성을 카테고리 대분류만으로 판단할 수 없다(예: 35도에 "데님 팬츠"는
    # 보온성과 무관하므로 감점 근거가 없다). 과거에는 극단 기온 구간에서 미분류 키워드도
    # 기본 감도로 일괄 감점했으나, 이는 실제로 계절 무관 상품까지 페널티를 주는 오류였다.
    # 따라서 미분류 키워드는 점수 보정을 0으로 유지하고, 대신 evidence_detail/next_checks
    # 쪽에서 "기온이 극단적이니 계절성을 직접 확인하라"는 경고만 노출한다
    # (penalty=0, note는 경고문이지만 _seasonal_adjustment 호출부에서 issues 목록에는
    # 추가하지 않고 next_checks 쪽으로만 전달되도록 None을 반환한다).
    if not winter_hits and not summer_hits:
        if temp_max >= 30 or temp_max <= 0:
            return 0.0, None

    return 0.0, None


def _discount_streak(keyword: str, ranking_history: Optional[List[List[Dict]]]) -> int:
    """snapshot_store 히스토리 기준, 키워드 매칭 상품의 평균 할인율이 연속 상승한 일수.

    Args:
        ranking_history: snapshot_store.load_history()가 반환하는 형태
            (날짜 오름차순 List[List[Dict]], 각 원소가 하루치 랭킹 아이템 리스트).
            없으면 0 반환 (정보 없음으로 처리, 신규 페널티 없음).

    Returns:
        연속 상승 일수 (0 이상). 데이터가 1일 분량 이하면 0.
    """
    if not ranking_history or len(ranking_history) < 2:
        return 0

    daily_avgs: List[float] = []
    for day_items in ranking_history:
        matched = [
            item.get("discount_rate", 0) for item in day_items
            if item.get("period", "1일") == "1일" and keyword in item.get("product_name", "")
        ]
        if matched:
            daily_avgs.append(sum(matched) / len(matched))

    if len(daily_avgs) < 2:
        return 0

    streak = 0
    for prev, curr in zip(daily_avgs, daily_avgs[1:]):
        if curr > prev:
            streak += 1
        else:
            streak = 0
    return streak


def _price_competitiveness(
    matched_item: Optional[Dict], rank_diff_result: Dict
) -> Tuple[float, Optional[str]]:
    """매칭 상품의 가격대가 동일 카테고리 평균가 대비 어디에 위치하는지 평가한다.

    가격 자체가 높다/낮다는 것만으로 좋다/나쁘다를 말할 수 없으므로(저가 회전형
    수요 vs 고가 프레스티지 수요 모두 기획전 근거가 될 수 있음), "평균가에서 크게
    벗어난 가격대인데도 랭킹이 급등했다"는 사실 자체를 가격 경쟁력 신호로 본다.
    평균가 대비 30% 이상 저렴하면 "가격 메리트로 인한 회전 수요" 보너스(+3),
    평균가 대비 30% 이상 비싸면 "고가에도 불구한 수요" 보너스(+3, 더 강한 시그널로
    해석), 평균가 ±15% 이내면 보정 없음(0)으로 둔다. matched_item이나 카테고리
    평균가 정보가 없으면 0과 None을 반환한다(보정 없음).

    Returns:
        (adjustment, note) — adjustment는 0~+3 사이(페널티 없음, 보너스만).
    """
    if not matched_item:
        return 0.0, None
    price = matched_item.get("price")
    category = matched_item.get("category", "")
    if not price or not category:
        return 0.0, None

    same_cat_prices = [
        item.get("price") for item in rank_diff_result.get("items", [])
        if item.get("category") == category and item.get("price")
        and item.get("product_name") != matched_item.get("product_name")
    ]
    if len(same_cat_prices) < 3:
        return 0.0, None
    avg_price = sum(same_cat_prices) / len(same_cat_prices)
    if avg_price <= 0:
        return 0.0, None

    deviation = (price - avg_price) / avg_price
    if deviation <= -0.3:
        return 3.0, f"카테고리 평균가({avg_price:,.0f}원) 대비 {abs(deviation)*100:.0f}% 저렴 — 가격 메리트형 회전 수요로 추정"
    if deviation >= 0.3:
        return 3.0, f"카테고리 평균가({avg_price:,.0f}원) 대비 {deviation*100:.0f}% 비쌈 — 고가에도 수요가 몰리는 강한 시그널"
    return 0.0, None


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
    weather_conflict: bool = False,
    seasonal_adjustment: float = 0.0,
    discount_streak_days: int = 0,
    keyword_weight: float = 0.0,
    has_rank_match: bool = True,
    price_adjustment: float = 0.0,
    category_demand_weight: float = 1.0,
) -> Tuple[int, Dict[str, float]]:
    """지표별 기여 점수를 계산하고 (최종 점수, 지표별 breakdown)을 반환한다.

    Args:
        is_new: 실제 무신사/29CM 랭킹에 "신규 진입"으로 잡힌 상품인 경우에만 True.
            트렌드 키워드가 랭킹 데이터와 전혀 매칭되지 않은 경우(has_rank_match=False)는
            신규 진입이 아니라 "랭킹 근거 없음"이므로 별도로 취급한다.
        has_rank_match: 트렌드 키워드가 rank_surging(급등/신규 상품 맵)에서
            매칭된 상품이 하나라도 있었는지. False면 랭킹 관련 근거가 전혀 없는
            "트렌드 단독 시그널"이므로 랭킹 점수를 최소치로 제한한다.
        weather_conflict: 하위호환용 — True이면 seasonal_adjustment가 0일 때만
            과거 방식(-20)으로 강제 적용한다. seasonal_adjustment가 전달되면
            그 값을 우선 사용한다 (점진적 보정).
        seasonal_adjustment: _seasonal_adjustment()가 산출한 연속값(-20~+5).
        discount_streak_days: 할인율 연속 상승 일수 — 지속성 보너스(최대 5점).
        keyword_weight: 백테스트 피드백 기반 키워드 가중치(-10~+10).
        price_adjustment: _price_competitiveness()가 산출한 가격대 경쟁력
            보너스(0~+3) — 카테고리 평균가 대비 크게 벗어난 가격대인데도
            랭킹이 급등했다는 신호.
        category_demand_weight: _category_demand_weight()가 산출한 대분류별
            momentum 가중치(0.6~1.6, 기본 1.0) — 랭킹(rank) 점수에 곱해진다.
    """
    breakdown: Dict[str, float] = {}

    # 트렌드 (30점)
    if trend_pct >= 50:   breakdown["trend"] = 30
    elif trend_pct >= 30: breakdown["trend"] = 20
    else:                 breakdown["trend"] = 10

    # 랭킹 (25점) — 랭킹 매칭이 전혀 없으면(트렌드 단독 시그널) 최소 점수만 부여한다.
    if not has_rank_match:                   breakdown["rank"] = 0
    elif is_new:                             breakdown["rank"] = 25
    elif rank_change and rank_change >= 10:  breakdown["rank"] = 25
    elif rank_change and rank_change >= 5:   breakdown["rank"] = 15
    else:                                    breakdown["rank"] = 5

    # 카테고리 momentum 가중치 — 같은 "1위"/"신규진입"이라도 오늘 그 카테고리가
    # 다른 카테고리 대비 얼마나 활발히 움직이는지에 따라 랭킹 점수를 조정한다.
    breakdown["rank"] = round(breakdown["rank"] * category_demand_weight, 1)

    # 할인율 급등 (15점)
    breakdown["discount_surge"] = 15 if discount_surge else 0

    # 품절 (10점)
    breakdown["soldout"] = 10 if soldout else 0

    # 복수 카테고리 교차 (10점)
    breakdown["cross_category"] = 10 if is_cross else 0

    # YoY (10점) — 올해 순위가 작년보다 좋을 때
    breakdown["yoy"] = 10 if (yoy_rank and current_rank and current_rank < yoy_rank) else 0

    # 할인 지속성 보너스 (최대 5점) — 연속 상승일이 길수록 프로모션 본격화로 판단
    breakdown["discount_streak"] = min(5, discount_streak_days) if discount_streak_days else 0

    # 계절 보정 — 점진적 값이 있으면 그것을 사용, 없으면 하위호환 on/off(-20) 적용
    if seasonal_adjustment:
        breakdown["seasonal_adjustment"] = seasonal_adjustment
    elif weather_conflict:
        breakdown["seasonal_adjustment"] = -20.0
    else:
        breakdown["seasonal_adjustment"] = 0.0

    # 백테스트 피드백 — 키워드 패턴별 과거 적중률 기반 가산/감산 (최대 ±10점)
    breakdown["backtest_feedback"] = round(keyword_weight, 1) if keyword_weight else 0.0

    # 가격대 경쟁력 보너스 — 카테고리 평균가에서 크게 벗어난 가격대(저가 회전형/
    # 고가 프레스티지형)인데도 랭킹이 급등한 경우의 가산점 (최대 +3점).
    breakdown["price_competitiveness"] = round(price_adjustment, 1) if price_adjustment else 0.0

    raw = sum(breakdown.values())
    s = max(0, min(int(round(raw)), 100))
    return s, breakdown


def _level(score: int) -> str:
    if score >= 80:   return "🔴 긴급"
    elif score >= 50: return "🟡 주의"
    else:             return "🟢 참고"


def _recommend_open_date(score: int) -> dict:
    """
    기획전 권장 오픈일 계산.

    Returns:
        {
          "earliest": "YYYY-MM-DD",  # 최빠른 오픈 가능일
          "latest":   "YYYY-MM-DD",  # 권장 마감일 (이 후에는 트렌드 하락 가능)
          "label":    "~6/11 (7일 내)",
        }
    """
    from datetime import datetime, timezone, timedelta
    today = (datetime.now(timezone.utc) + timedelta(hours=9)).date()

    if score >= 80:      # 🔴 긴급
        earliest = today + timedelta(days=1)
        latest   = today + timedelta(days=5)
        label    = f"{latest.strftime('%m/%d')}까지 (3~5일 내)"
    elif score >= 50:    # 🟡 주의
        earliest = today + timedelta(days=3)
        latest   = today + timedelta(days=14)
        label    = f"{latest.strftime('%m/%d')}까지 (7~14일 내)"
    else:                # 🟢 참고
        earliest = today + timedelta(days=7)
        latest   = today + timedelta(days=28)
        label    = f"{latest.strftime('%m/%d')}까지 (2~4주 내)"

    return {
        "earliest": earliest.strftime("%Y-%m-%d"),
        "latest":   latest.strftime("%Y-%m-%d"),
        "label":    label,
    }


def _suggest_theme(keyword: str) -> str:
    for kw, theme in _THEME_TEMPLATES.items():
        if kw in keyword:
            return theme
    return f"{keyword} 기획전"


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def _score_range(score: int, sample_strength: int) -> Dict[str, int]:
    """보강 지표 개수에 따라 점수 상/하한 범위(score_range)를 계산한다.

    주의: 이것은 표본 수·과거 분산·백테스트 적중률을 사용한 통계적 신뢰구간이
    아니다(따라서 필드명도 confidence_band가 아니라 score_range로 명확히 한다).
    단순히 "보강 지표(랭킹매칭/할인/품절/교차/YoY 등)가 몇 개나 함께 확인됐는지"에
    따라 점수 주변에 임의의 여유 범위를 두는 휴리스틱이다. 보강 지표가 적을수록
    (sample_strength 낮음) 범위를 넓게, 많을수록 좁게 잡아 "이 점수가 얼마나
    단일 근거에 의존하는지"를 MD에게 시각적으로 알리는 목적이며, 실제 분포나
    백테스트 표본 기반 구간을 대체하지 않는다. 통계적으로 검증된 신뢰도를
    원한다면 signal_backtest.aggregate_stats()의 카테고리/점수대별 표본 수와
    적중률을 함께 참고해야 한다.
    """
    spread = max(4, 14 - sample_strength * 2)
    return {
        "low": max(0, score - spread),
        "high": min(100, score + spread),
    }


def _build_evidence_detail(
    trend_pct: float,
    rank_change: Optional[int],
    is_new: bool,
    has_rank_match: bool,
    breakdown: Dict[str, float],
    seasonal_note: Optional[str],
    discount_streak_days: int,
    keyword_weight: float,
    price_note: Optional[str] = None,
    category_demand_weight: float = 1.0,
) -> List[str]:
    """'왜 이 점수인지'를 MD가 바로 이해할 수 있는 한국어 설명 목록으로 변환."""
    detail: List[str] = []
    detail.append(f"트렌드 검색량 전주 대비 +{trend_pct:.0f}% (기여 {breakdown['trend']:.0f}점)")
    if not has_rank_match:
        detail.append(
            f"랭킹 데이터에서 매칭되는 상품 없음 — 트렌드 단독 시그널이므로 랭킹 항목은 최소 점수 처리 (기여 {breakdown['rank']:.0f}점)"
        )
    elif is_new:
        detail.append(f"실제 랭킹 신규 진입 상품으로 확인 — 랭킹 항목 만점 (기여 {breakdown['rank']:.0f}점)")
    elif rank_change:
        detail.append(f"랭킹 {rank_change:+d}계단 변동 (기여 {breakdown['rank']:.0f}점)")
    else:
        detail.append(f"랭킹 변동 미미 (기여 {breakdown['rank']:.0f}점)")
    if abs(category_demand_weight - 1.0) >= 0.1:
        detail.append(
            f"카테고리 momentum 가중치 {category_demand_weight:.2f}x 적용 — 같은 순위라도 "
            f"오늘 이 카테고리가 다른 카테고리 대비 {'더 활발히' if category_demand_weight > 1.0 else '덜 활발하게'} "
            "움직이는 정도를 반영해 랭킹 점수를 조정함"
        )
    if breakdown.get("discount_surge"):
        detail.append(f"카테고리 평균 할인율 급등 감지 (기여 {breakdown['discount_surge']:.0f}점)")
    if breakdown.get("soldout"):
        detail.append(f"카테고리 품절 비율 20% 이상 — 수요 과잉 신호 (기여 {breakdown['soldout']:.0f}점)")
    if breakdown.get("cross_category"):
        detail.append(f"상의/아우터/바지 중 2개 이상 카테고리 동시 급등 (기여 {breakdown['cross_category']:.0f}점)")
    if breakdown.get("yoy"):
        detail.append(f"작년 동기 대비 순위 우위 확인 (기여 {breakdown['yoy']:.0f}점)")
    if discount_streak_days >= 2:
        detail.append(f"할인율 {discount_streak_days}일 연속 상승 — 프로모션 본격화 추정 (기여 {breakdown['discount_streak']:.0f}점)")
    if price_note and breakdown.get("price_competitiveness"):
        detail.append(f"{price_note} (기여 {breakdown['price_competitiveness']:.0f}점)")
    if seasonal_note:
        detail.append(seasonal_note)
    if keyword_weight:
        direction = "가산" if keyword_weight > 0 else "감산"
        detail.append(
            f"동일 키워드 패턴의 과거 백테스트 적중률 반영 — {direction} {abs(keyword_weight):.1f}점"
        )
    return detail


def _build_next_checks(
    main_cat: str,
    discount_surge: bool,
    soldout: bool,
    is_new: bool,
    has_rank_match: bool,
    score: int,
    season_unclassified_extreme: bool = False,
    temp_max: Optional[float] = None,
    discount_history_insufficient: bool = False,
) -> List[str]:
    """MD가 기획전 오픈 전 추가로 확인해야 할 체크리스트.

    season_unclassified_extreme=True이면 키워드가 계절 사전(겨울/여름 키워드)에
    없는 상태에서 기온이 극단적인 구간(30도 이상/0도 이하)이라는 뜻이다. 카테고리
    대분류만으로는 보온성을 판단할 수 없으므로(예: 35도의 "데님 팬츠") 점수에는
    페널티를 주지 않되, MD가 상품 소재/보온성을 직접 확인하라는 경고를 덧붙인다.
    """
    checks = [
        f"무신사/29CM {main_cat or '해당'} 카테고리 랭킹 페이지에서 경쟁 상품 구성·가격대 재확인",
        "최근 3~7일 검색량 추세가 일시 스파이크인지 지속 추세인지 트렌드 차트로 재확인",
    ]
    if not has_rank_match:
        checks.append("랭킹 데이터에서 해당 키워드를 포함한 상품을 직접 검색 — 트렌드만 있고 랭킹 근거가 없는 시그널이므로 실제 상품 존재 여부부터 확인")
    if discount_surge:
        checks.append("경쟁사 할인 종료 예정일 확인 — 할인 종료 후 자연 감소 가능성 점검")
    if soldout:
        checks.append("품절 상품의 재입고 일정 확인 — 공급 부족이면 기획전 타이밍을 재입고 시점에 맞출 것")
    if is_new:
        checks.append("신규 진입 상품의 리뷰/평점 데이터 축적 여부 확인 (데이터 부족 시 신뢰도 낮음)")
    if score < 50:
        checks.append("점수 50점 미만 — 추가 지표(할인/품절/교차) 없이 트렌드만으로 형성된 시그널일 수 있어 1~2일 더 관찰 권장")
    checks.append("동일 카테고리 평균가와 비교해 가격대가 적정한지, 경쟁 상품과 가격 격차가 기획전 구성(번들/할인폭)에 영향을 주는지 확인")
    if season_unclassified_extreme:
        temp_txt = f"{temp_max:.0f}도" if temp_max is not None else "극단 기온"
        checks.append(
            f"⚠️ 현재 {temp_txt} 구간이지만 이 키워드는 계절 사전(겨울/여름)에 없어 점수 보정을 적용하지 않았습니다 — "
            "상품 소재/보온성을 상세페이지에서 직접 확인해 계절 역행 여부를 판단하세요."
        )
    if discount_history_insufficient:
        checks.append(
            "⚠️ 할인율 히스토리가 2일 미만이라 '할인율 급등' 점수를 0으로 처리했습니다 — "
            "수집 데이터가 누적되기 전까지는 카테고리 페이지에서 할인율이 실제로 전날보다 올랐는지 직접 비교 확인하세요."
        )
    return checks


def detect(
    trend_data: List[Dict],
    rank_diff_result: Dict,
    archive_data: Optional[List[Dict]] = None,
    weather_data: Optional[Dict] = None,
    backtest_feedback: Optional[Dict[str, float]] = None,
    ranking_history: Optional[List[List[Dict]]] = None,
) -> List[Dict]:
    """
    기획전 타이밍 시그널 감지.

    Args:
        trend_data:       google_trends + naver_datalab 통합 데이터.
        rank_diff_result: rank_diff.analyze() 반환 dict.
        archive_data:     musinsa_archive.collect() 반환 (YoY용, 없으면 스킵).
        weather_data:     weather.collect() 반환 (계절 보정용, 없으면 스킵).
        backtest_feedback: signal_backtest.keyword_hit_weights() 반환 dict
            ({키워드: 가중치}). 주어지면 동일 패턴 키워드의 과거 적중률을
            점수에 가산/감산한다 (기본 None — 하위호환, 가중치 0).
        ranking_history:  snapshot_store.load_history("musinsa_rankings", ...) 반환
            (날짜 오름차순 List[List[Dict]]). 할인 지속성 신호 계산에 사용,
            없으면 해당 보너스는 0으로 처리한다.

    Returns:
        시그널 dict 목록 (신뢰도 점수 내림차순 정렬).
    """
    temp_max         = weather_data.get("temp_max") if weather_data else None
    backtest_feedback = backtest_feedback or {}
    trend_surging    = _trend_surge(trend_data)
    rank_surging     = _rank_surge(rank_diff_result)
    discount_cats, discount_history_insufficient = _discount_surge(rank_diff_result, ranking_history)
    soldout_cats     = _soldout_ratio(rank_diff_result)
    cross_keywords   = _cross_category(trend_surging, rank_surging)
    category_weights = _category_demand_weight(rank_diff_result)
    collected_at     = _kst_today()

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
        # 실제 신규 진입(new_entries 출처)인지 — 랭킹 매칭이 전혀 없는 경우와 구분한다.
        # (랭킹 데이터가 없을 뿐인데 "신규 진입"으로 오판해 랭킹 만점을 주지 않기 위함)
        is_true_new_entry = bool(matched_item and matched_item.get("_is_true_new_entry"))
        has_rank_match     = matched_item is not None
        current_rank  = matched_item.get("rank") if matched_item else None
        cat           = matched_item.get("category", "") if matched_item else ""

        # 카테고리 대분류 파악
        main_cat = next((m for m in _MAIN_CATS if cat.startswith(m)), "")

        discount_surge = main_cat in discount_cats
        soldout        = main_cat in soldout_cats
        is_cross       = trend_kw in cross_keywords
        category_weight = category_weights.get(main_cat, 1.0)
        yoy_rank       = _yoy_compare(trend_kw, archive_data)
        weather_warn   = _weather_conflict(trend_kw, temp_max)
        seasonal_adj, seasonal_note = _seasonal_adjustment(trend_kw, temp_max, cat)
        streak_days    = _discount_streak(trend_kw, ranking_history)
        price_adj, price_note = _price_competitiveness(matched_item, rank_diff_result)

        # signal_backtest.keyword_hit_weights()는 키워드를 공백/특수문자 제거
        # 형태로 정규화해 가중치 맵의 key를 만든다("린넨 셔츠" -> "린넨셔츠"). 여기서도
        # 동일한 정규화를 적용해야 "린넨 셔츠"(공백 포함) 같은 키워드의 가중치가
        # 실제로 매칭된다 — strip()만으로는 공백이 남아 매칭이 항상 실패했었다.
        normalized_kw = _normalize_keyword_for_matching(trend_kw)
        keyword_weight = 0.0
        for pattern, weight in backtest_feedback.items():
            normalized_pattern = _normalize_keyword_for_matching(pattern)
            if normalized_pattern and (
                normalized_pattern in normalized_kw or normalized_kw in normalized_pattern
            ):
                keyword_weight = weight
                break

        score, breakdown = _score(
            trend_pct, rank_change, is_true_new_entry,
            discount_surge, soldout, is_cross, yoy_rank, current_rank,
            weather_conflict=bool(weather_warn),
            seasonal_adjustment=seasonal_adj,
            discount_streak_days=streak_days,
            keyword_weight=keyword_weight,
            has_rank_match=has_rank_match,
            price_adjustment=price_adj,
            category_demand_weight=category_weight,
        )

        if score < 30:
            continue   # 30점 미만은 노이즈로 제외

        seen_keywords.add(trend_kw)

        # 추가 이슈 목록
        issues: List[str] = []
        if discount_surge:
            issues.append(f"할인율 급등 (전일 대비 +{discount_cats[main_cat]:.1f}%p)")
        if soldout:
            issues.append(f"품절 {soldout_cats[main_cat]:.0f}%")
        if is_cross:
            issues.append("복수 카테고리 동시 급등")
        if yoy_rank and current_rank:
            diff = yoy_rank - current_rank
            if diff > 0:
                issues.append(f"작년 동기 대비 ▲{diff}위 상승")
        if seasonal_note:
            issues.append(seasonal_note)
        elif weather_warn:
            issues.append(weather_warn)
        if streak_days >= 2:
            issues.append(f"할인율 {streak_days}일 연속 상승")
        if price_note:
            issues.append(price_note)
        if abs(category_weight - 1.0) >= 0.1:
            direction = "활발" if category_weight > 1.0 else "저조"
            issues.append(f"'{main_cat}' 카테고리 momentum {direction} (가중치 {category_weight:.2f}x)")

        # 신뢰구간 산출 — 보강 지표 개수가 많을수록 구간을 좁힌다.
        sample_strength = sum([
            has_rank_match,
            discount_surge,
            soldout,
            is_cross,
            yoy_rank is not None,
            streak_days >= 2,
        ])

        open_date = _recommend_open_date(score)
        signal = {
            "keyword":        trend_kw,
            "trend_pct":      trend_pct,
            "rank_change":    rank_change,
            "is_new_entry":   is_true_new_entry,
            "has_rank_match": has_rank_match,
            "product_name":   matched_product or "",
            "brand":          matched_item.get("brand", "") if matched_item else "",
            "url":            matched_item.get("url", "") if matched_item else "",
            "category":       cat,
            "theme":          _suggest_theme(trend_kw),
            "score":          score,
            "level":          _level(score),
            "issues":         issues,
            "discount_surge": discount_surge,
            "discount_history_insufficient": discount_history_insufficient,
            "soldout":        soldout,
            "is_cross_cat":   is_cross,
            "yoy_last_rank":  yoy_rank,
            # weather_conflict는 기존 on/off 판정(weather_warn)뿐 아니라 신규 점진적
            # 계절 보정(seasonal_adj)이 음수(=역행 페널티가 적용됨)인 경우도 True로
            # 잡아야 한다. 그렇지 않으면 예: 25도에서 후드 시그널처럼 seasonal_adjustment가
            # -3.9점으로 역행을 감지했는데도 weather_conflict=False로 표기되어, 이 필드를
            # 그대로 소비하는 호출부(main.py/dashboard.py)가 계절 충돌을 놓치게 된다.
            "weather_conflict": bool(weather_warn) or seasonal_adj < 0,
            "collected_at":   collected_at,
            "open_earliest":  open_date["earliest"],
            "open_latest":    open_date["latest"],
            "open_label":     open_date["label"],
            # ── 신규: 점수 근거/신뢰구간/추가 확인 사항 ──
            "score_breakdown":   breakdown,
            # score_range: 통계적 신뢰구간이 아니라 보강 지표 개수 기반 휴리스틱
            # 범위(자세한 한계는 _score_range() docstring 참고). confidence_band는
            # 과거 호출부(md_actions.py/dashboard.py/기존 테스트) 하위호환을 위해
            # 동일한 dict를 가리키는 별칭으로 함께 유지한다.
            "score_range":       _score_range(score, sample_strength),
            "confidence_band":   _score_range(score, sample_strength),
            "evidence_detail":   _build_evidence_detail(
                trend_pct, rank_change, is_true_new_entry, has_rank_match, breakdown,
                seasonal_note, streak_days, keyword_weight, price_note,
                category_demand_weight=category_weight,
            ),
            "category_demand_weight": category_weight,
            "next_checks":       _build_next_checks(
                main_cat, discount_surge, soldout, is_true_new_entry, has_rank_match, score,
                season_unclassified_extreme=(
                    seasonal_adj == 0.0
                    and temp_max is not None
                    and (temp_max >= 30 or temp_max <= 0)
                    and not any(w in trend_kw for w in _WINTER_KEYWORDS)
                    and not any(w in trend_kw for w in _SUMMER_KEYWORDS)
                ),
                temp_max=temp_max,
                discount_history_insufficient=discount_history_insufficient,
            ),
            "discount_streak_days": streak_days,
            "seasonal_adjustment":  seasonal_adj,
            "backtest_keyword_weight": keyword_weight,
            "price_competitiveness_bonus": price_adj,
            "price_note": price_note,
        }
        signals.append(signal)

        rank_txt = "NEW" if is_true_new_entry else (
            f"▲{rank_change}" if rank_change else ("미매칭" if not has_rank_match else "-")
        )
        logger.warning(
            "%s 기획전 시그널! [%s] 트렌드+%.0f%% | 랭킹%s | 점수:%d | 이슈:%s",
            _level(score), trend_kw, trend_pct, rank_txt, score, issues,
        )

    signals.sort(key=lambda x: x["score"], reverse=True)

    if not signals:
        logger.info("기획전 시그널 없음 (점수 30점 미만)")

    return signals
