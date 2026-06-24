"""과거 기획전 시그널을 이후 공개 랭킹으로 검증한다.

확장 사항:
  - 상대성과(relative_change): 같은 날 발생한 시그널들의 평균(시장 전체) 순위 변화를
    '시장효과(baseline)'로 보고, 개별 시그널의 변화에서 이를 차감해 시즌/전체 상승효과와
    분리한 순수 기여분을 계산한다.
  - aggregate_stats(): 카테고리별·점수대별 적중률 통계 집계.
  - keyword_hit_weights(): 키워드 패턴(예: "린넨", "후드")별 과거 적중률을 기반으로
    다음 시그널 스코어링에 가산/감산할 가중치 맵을 만든다.

기존 evaluate()의 반환 row 키(signal_date/keyword/theme/score/base_rank/
day3_change/day7_change/status/reason)는 절대 제거하지 않으며, 신규 필드만 추가한다.
"""

import re
from datetime import date, timedelta
from typing import Dict, List, Optional

import config


def _matching(
    items: List[Dict], signal: Dict, allow_category_fallback: bool = True
) -> List[Dict]:
    """시그널과 동일한 상품/키워드를 랭킹 아이템 목록에서 찾는다.

    allow_category_fallback=True(기본, 기준일 매칭용)이면 상품명/키워드 매칭이
    모두 실패했을 때 카테고리 전체로 대체한다 — 기준일 시점에는 "이 카테고리에서
    이런 시그널이 떴다"는 사실 자체가 의미 있는 추적 대상이기 때문이다.

    allow_category_fallback=False(후속일 매칭용)이면 상품명/키워드 매칭이 실패할 때
    카테고리 전체로 대체하지 않고 빈 리스트를 반환한다. 후속일에 카테고리 평균으로
    대체하면, 실제로는 랭킹에서 이탈(품절/순위 밖으로 탈락)한 상품이 카테고리
    평균 순위로 치환되어 "부분 적중"처럼 허위로 판정되는 문제(생존자 편향과 유사한
    오류)가 생긴다. 이탈을 정직하게 "매칭 실패"로 처리해야 status가 '보류'로
    빠지고, MD가 "이 상품이 랭킹에서 사라졌다"는 사실을 놓치지 않는다.
    """
    keyword = signal.get("keyword", "")
    product = signal.get("product_name", "")
    category = signal.get("category", "")
    daily = [item for item in items if item.get("period", "1일") == "1일"]

    # 카테고리가 명시된 시그널은 먼저 동일 카테고리로 풀(pool)을 좁힌다. 그렇지
    # 않으면 "상의_전체" 시그널의 키워드가 "바지_전체"의 동명/유사 상품과 우연히
    # 매칭되어(예: 둘 다 "린넨"을 포함) 다른 카테고리 상품의 순위 변동이 평균에
    # 섞여 들어가는 문제가 생긴다(실제 재현: 상의 시그널이 바지 카테고리의 린넨
    # 상품 상승까지 합산해 day7_change가 부풀려짐). 카테고리 풀에서 매칭이
    # 하나도 없으면(예: 수집 데이터에 카테고리 표기가 없는 구버전 스냅샷)
    # 안전하게 전체 daily로 폴백한다 — 하위호환 유지.
    pool = (
        [item for item in daily if item.get("category") == category]
        if category else daily
    )
    if category and not pool:
        pool = daily

    if product:
        exact = [item for item in pool if item.get("product_name") == product]
        if exact:
            return exact
    if keyword:
        keyword_matches = [
            item for item in pool if keyword in item.get("product_name", "")
        ]
        if keyword_matches:
            return keyword_matches
    if not allow_category_fallback:
        return []
    return [
        item for item in pool
        if category and item.get("category") == category
    ]


def _average_rank(items: List[Dict]):
    ranks = [item.get("rank") for item in items if item.get("rank")]
    return round(sum(ranks) / len(ranks), 1) if ranks else None


def _nearest_snapshot_date(
    rankings_by_date: Dict[str, List[Dict]], target_date: str, max_forward_days: int = 3
) -> Optional[str]:
    """목표 날짜의 스냅샷이 없으면(휴일/수집 실패) 그 이후 가장 가까운 실제 수집일을 찾는다.

    목표 날짜보다 과거 데이터로 대체하면 측정 구간이 짧아져 왜곡되므로, 항상
    "목표일 이후"의 가장 가까운 수집일만 허용한다. max_forward_days 내에 없으면
    None을 반환해 '보류' 처리되도록 한다.
    """
    if target_date in rankings_by_date and rankings_by_date[target_date]:
        return target_date
    target = date.fromisoformat(target_date)
    for offset in range(1, max_forward_days + 1):
        candidate = (target + timedelta(days=offset)).isoformat()
        if candidate in rankings_by_date and rankings_by_date[candidate]:
            return candidate
    return None


def _market_baseline_change(
    rankings_by_date: Dict[str, List[Dict]],
    base_date: str,
    target_date: str,
    category: str = "",
    exclude_products: Optional[set] = None,
) -> Optional[float]:
    """동일 카테고리(없으면 전체) 상품 '고정 코호트'의 시장 평균 순위 변화 — '시즌효과' 베이스라인.

    TOP N 랭킹은 매일 1~N위를 채우므로 날짜별 평균 순위는 항상 (N+1)/2로 동일해
    baseline이 항상 0이 되는 문제가 있었다. 이를 피하기 위해 base_date에 존재하던
    "동일 상품 집합(코호트)"을 고정하고, 그 상품들이 target_date에 각각 몇 위로
    이동했는지를 비교한다(코호트에 없는 신규/이탈 상품은 비교 대상에서 제외).
    이렇게 하면 순위표 전체가 항상 1~N을 채우더라도, 동일 상품군의 순위가
    실제로 오르내린 정도(=시즌/시장 전체 효과)를 포착할 수 있다.

    exclude_products로 시그널 자신이 매칭한 상품을 코호트에서 제외해, 시그널의
    개별 성과가 베이스라인에 다시 섞여 누수(leakage)되는 것을 막는다. 호출부
    (evaluate())는 같은 signal_date에 발생한 '모든' 시그널이 매칭한 상품까지
    exclude_products에 포함시켜 넘겨야 한다 — 그렇지 않으면 같은 날 발생한
    형제 시그널의 상승분이 시장효과로 잘못 흡수되어 상대성과가 과소평가된다.
    """
    exclude_products = exclude_products or set()
    base_items = [
        item for item in rankings_by_date.get(base_date, [])
        if item.get("period", "1일") == "1일"
        and (not category or item.get("category") == category)
        and item.get("product_name") not in exclude_products
    ]
    base_ranks = {
        item.get("product_name"): item.get("rank")
        for item in base_items
        if item.get("product_name") and item.get("rank")
    }
    if not base_ranks:
        return None

    target_items = [
        item for item in rankings_by_date.get(target_date, [])
        if item.get("period", "1일") == "1일"
        and (not category or item.get("category") == category)
    ]
    target_ranks = {
        item.get("product_name"): item.get("rank")
        for item in target_items
        if item.get("product_name") and item.get("rank")
    }

    # 코호트(base_date 상품 집합) 중 target_date에 남아있지 않은(랭킹 이탈) 상품을
    # 단순히 비교 대상에서 제외하면, "성과가 좋아 계속 살아남은 상품들"만 평균에
    # 남는 생존자 편향(survivorship bias)이 생긴다 — 시장 전체가 실제로는 하락했어도
    # 상승한 생존 상품만으로 market_day7_change가 양수로 왜곡될 수 있다.
    # 이를 막기 위해 이탈 상품은 "TOP N 바로 밖(N+1위)으로 떨어졌다"고 간주해
    # 순위 하한값으로 비교에 포함한다(가장 보수적인 가정: 완전히 순위 밖으로 밀려났다).
    rank_floor = getattr(config, "MUSINSA_TOP_N", 30) + 1
    diffs = [
        base_ranks[name] - target_ranks.get(name, rank_floor)
        for name in base_ranks
    ]
    if not diffs:
        return None
    # 순위는 낮을수록 상위이므로, base - target > 0 이면 그 상품의 순위가 상승.
    # 코호트 평균을 내면 "같은 상품들이 평균적으로 얼마나 움직였는지"가 되어
    # TOP N 전체 평균(항상 동일)과 달리 실제 시장 변동(이탈 포함)을 반영한다.
    return round(sum(diffs) / len(diffs), 1)


def evaluate(
    signals_by_date: Dict[str, List[Dict]],
    rankings_by_date: Dict[str, List[Dict]],
    today: date = None,
) -> List[Dict]:
    """과거 시그널을 이후 공개 랭킹으로 검증한다.

    기존 동작(시그널 발생일 기준 +3일/+7일 평균 순위 변화로 적중 여부 판정)은
    그대로 유지하면서, 시장 전체 효과(baseline)를 분리한 상대성과 필드를 추가한다.

    신규 필드:
        market_day7_change: 동일 카테고리 시장 전체(고정 코호트 기준)의 7일 평균
            순위 변화(시즌효과 베이스라인). 시그널이 매칭한 상품 자신은 코호트에서
            제외해 누수를 막는다.
        relative_day7_change: day7_change - market_day7_change. 시장효과를 제거한
            시그널 고유의 순수 기여분.
        relative_status: 상대성과(relative_day7_change) 기준의 별도 판정.
            기존 status(절대 변화 기준)는 그대로 유지되며 상호 보완적으로 사용한다.
        day3_snapshot_date / day7_snapshot_date: 실제로 비교에 사용된 수집일.
            정확히 +3일/+7일 데이터가 없으면(휴일·수집 실패) 그 이후 가장 가까운
            수집일(최대 3일 이내)을 사용한다. 못 찾으면 None — 계속 '보류' 처리.
    """
    today = today or date.today()
    results = []
    for signal_date, signals in signals_by_date.items():
        start_date = date.fromisoformat(signal_date)

        # 같은 signal_date에 시그널이 여러 개 발생하면, A 시그널의 시장 베이스라인
        # 코호트에 B 시그널이 추천한(역시 급등한) 상품이 그대로 남아있을 수 있다.
        # 이 경우 B의 상승분이 "시장 전체 효과"로 잘못 흡수되어 A의 relative_change가
        # 과소평가된다(반대도 마찬가지). 이를 막기 위해 해당 날짜에 발생한 '모든'
        # 시그널이 매칭한 상품 집합을 먼저 한 번 모아, 모든 시그널의 베이스라인
        # 계산에 공통으로 제외시킨다.
        day_items = rankings_by_date.get(signal_date, [])
        all_signal_products: set = set()
        for sig in signals:
            matched = _matching(day_items, sig)
            all_signal_products.update(
                item.get("product_name") for item in matched if item.get("product_name")
            )

        for signal in signals:
            base_items = _matching(day_items, signal)
            base_rank = _average_rank(base_items)
            # 베이스라인 제외 집합은 "이 시그널이 매칭한 상품"뿐 아니라 같은 날
            # 발생한 형제 시그널이 매칭한 상품도 포함한다(위 all_signal_products).
            exclude_products = set(all_signal_products)
            row = {
                "signal_date": signal_date,
                "keyword": signal.get("keyword", ""),
                "theme": signal.get("theme", ""),
                "score": signal.get("score", 0),
                "base_rank": base_rank,
                "day3_change": None,
                "day7_change": None,
                "status": "검증 대기",
                "reason": "추천 후 7일 데이터가 아직 없습니다.",
                # ── 신규: 상대성과(시장효과 차감) 관련 필드 ──
                "category": signal.get("category", ""),
                "market_day3_change": None,
                "market_day7_change": None,
                "relative_day3_change": None,
                "relative_day7_change": None,
                "relative_status": "검증 대기",
                "day3_snapshot_date": None,
                "day7_snapshot_date": None,
                "day3_change_dropout": False,
                "day7_change_dropout": False,
            }
            category = signal.get("category", "")
            for days, field, market_field, rel_field, snap_field in (
                (3, "day3_change", "market_day3_change", "relative_day3_change", "day3_snapshot_date"),
                (7, "day7_change", "market_day7_change", "relative_day7_change", "day7_snapshot_date"),
            ):
                target_exact = (start_date + timedelta(days=days)).isoformat()
                target = _nearest_snapshot_date(rankings_by_date, target_exact)
                row[snap_field] = target
                if target is None:
                    continue
                # 후속일은 카테고리 평균으로 대체하지 않는다(allow_category_fallback=False).
                # 키워드/상품명이 없는 시그널(카테고리 자체를 추적하는 경우)만 예외적으로
                # 카테고리 평균 추적을 허용한다.
                track_specific = bool(signal.get("keyword") or signal.get("product_name"))
                later_items = _matching(
                    rankings_by_date.get(target, []), signal,
                    allow_category_fallback=not track_specific,
                )
                later_rank = _average_rank(later_items)
                if track_specific and not later_items:
                    # 특정 상품/키워드를 추적 중인데 후속일에 전혀 매칭되지 않으면
                    # 랭킹 이탈(품절/순위 밖 탈락)로 보고, 카테고리 평균으로 얼버무리지
                    # 않은 채 정직하게 "매칭 없음"으로 둔다 — day*_change는 None 유지.
                    row[f"{field}_dropout"] = True
                elif base_rank is not None and later_rank is not None:
                    row[field] = round(base_rank - later_rank, 1)

                market_change = _market_baseline_change(
                    rankings_by_date, signal_date, target, category, exclude_products
                )
                row[market_field] = market_change
                if row[field] is not None and market_change is not None:
                    row[rel_field] = round(row[field] - market_change, 1)

            if row["day7_snapshot_date"] is not None or start_date + timedelta(days=10) <= today:
                day7 = row["day7_change"]
                day3 = row["day3_change"]
                if day7 is None:
                    row["status"] = "보류"
                    if row.get("day7_change_dropout"):
                        row["reason"] = "추천 상품이 7일 후 랭킹에서 이탈(품절/순위 밖 탈락)했습니다 — 카테고리 평균으로 대체하지 않고 보류 처리합니다."
                    else:
                        row["reason"] = "후속 랭킹에서 비교 대상을 찾지 못했습니다."
                elif day7 >= 3:
                    row["status"] = "적중"
                    row["reason"] = f"7일 후 평균 순위가 {day7:.1f}계단 상승했습니다."
                elif day7 > 0 or (day3 is not None and day3 >= 3):
                    row["status"] = "부분 적중"
                    row["reason"] = "단기 상승은 있었지만 7일 성과는 제한적입니다."
                else:
                    row["status"] = "실패"
                    row["reason"] = f"7일 후 평균 순위 변화가 {day7:.1f}계단입니다."

                # 상대성과 기준 판정 — 시장 전체(시즌효과)를 제거한 순수 기여분.
                rel7 = row["relative_day7_change"]
                rel3 = row["relative_day3_change"]
                if rel7 is None:
                    row["relative_status"] = "보류"
                elif rel7 >= 3:
                    row["relative_status"] = "적중"
                elif rel7 > 0 or (rel3 is not None and rel3 >= 3):
                    row["relative_status"] = "부분 적중"
                else:
                    row["relative_status"] = "실패"
            results.append(row)

    results.sort(key=lambda row: row["signal_date"], reverse=True)
    return results


# ── 카테고리별·점수대별 적중률 통계 ────────────────────────────────────────────

_SCORE_BUCKETS = (
    ("30~49", 30, 49),
    ("50~79", 50, 79),
    ("80+", 80, 10_000),
)


def _bucket_for(score: float) -> str:
    for label, low, high in _SCORE_BUCKETS:
        if low <= score <= high:
            return label
    return "기타"


def _is_dropout(row: Dict, status_field: str) -> bool:
    """해당 status_field 판정이 '이탈로 인한 보류'인지 판별한다.

    status_field가 "status"(절대 변화 기준)이면 day7_change_dropout 플래그를,
    "relative_status"(상대성과 기준)이면 동일한 day7_change_dropout 플래그를
    그대로 사용한다(이탈은 절대/상대 구분 없이 동일한 사실이다).
    """
    return bool(row.get("day7_change_dropout"))


def _hit_rate(
    rows: List[Dict], status_field: str = "status", treat_dropout_as_fail: bool = False
) -> Dict:
    """완료(적중/부분 적중/실패) 판정만으로 적중률을 계산한다.

    treat_dropout_as_fail=True이면, 랭킹에서 완전히 이탈한(day7_change_dropout=True,
    status="보류") row도 표본에 포함시켜 "실패"로 집계한다. 이탈은 실질적으로
    추천이 틀렸다는 신호(품절/순위 밖 탈락)이므로, 통계적 적중률 산출 시 이를
    분모에서 제외하면 적중률이 실제보다 과대평가된다(예: 이탈 1건 + 적중 2건을
    "이탈은 보류라 제외" 처리하면 적중률 100%로 집계되지만, 이탈을 실패로 보면
    66.7%다). aggregate_stats()/keyword_hit_weights()처럼 다음 의사결정에 쓰이는
    통계 함수는 반드시 treat_dropout_as_fail=True로 호출해야 한다. evaluate()가
    반환하는 원본 status/relative_status 필드 자체는 하위호환을 위해 그대로
    "보류"를 유지한다 — 여기서 변경하는 것은 통계 집계 시의 분류일 뿐이다.
    """
    completed = [r for r in rows if r.get(status_field) in ("적중", "부분 적중", "실패")]
    dropouts = []
    if treat_dropout_as_fail:
        dropouts = [
            r for r in rows
            if r.get(status_field) == "보류" and _is_dropout(r, status_field)
        ]
    pool = completed + dropouts
    if not pool:
        return {"count": 0, "hits": 0, "partial": 0, "fails": 0, "hit_rate": None}
    hits = sum(1 for r in completed if r.get(status_field) == "적중")
    partial = sum(1 for r in completed if r.get(status_field) == "부분 적중")
    fails = sum(1 for r in completed if r.get(status_field) == "실패") + len(dropouts)
    return {
        "count": len(pool),
        "hits": hits,
        "partial": partial,
        "fails": fails,
        "dropouts_counted_as_fail": len(dropouts),
        "hit_rate": round(hits / len(pool) * 100, 1),
        "hit_or_partial_rate": round((hits + partial) / len(pool) * 100, 1),
    }


def aggregate_stats(results: List[Dict]) -> Dict:
    """카테고리별·점수대별 적중률 통계를 집계한다.

    중요: by_category/by_score_bucket은 절대 변화 기준(status) 적중률뿐 아니라
    시장효과(시즌효과)를 차감한 상대성과 기준(relative_status) 적중률도 함께
    제공한다. 절대 적중률만 노출하면 겨울철처럼 시장 전체가 같은 방향으로
    움직이는 시기에 "카테고리/점수대 자체의 성과"로 오인할 수 있기 때문이다.
    MD 액션(md_actions.py)은 우선 상대성과(_relative 접미사) 값을 근거로
    사용하고, 절대값은 참고용으로만 함께 표기해야 한다.

    또한 모든 적중률은 treat_dropout_as_fail=True로 집계한다 — 랭킹 이탈
    (day7_change_dropout=True)은 "보류"로 표시되지만 실질적으로는 추천이
    틀린 결과이므로, 분모에서 제외하면 적중률이 과대평가된다. 통계 함수는
    이탈을 실패로 포함시켜야 MD가 실제 신뢰도를 정확히 판단할 수 있다.

    Args:
        results: evaluate()가 반환한 row 목록.

    Returns:
        {
          "overall": {...},                     # 전체 적중률 (절대, 이탈=실패 포함)
          "overall_relative": {...},             # 전체 적중률 (상대성과, 이탈=실패 포함)
          "by_category": {"상의_전체": {...}, ...},                # 절대
          "by_category_relative": {"상의_전체": {...}, ...},       # 상대성과
          "by_score_bucket": {"30~49": {...}, ...},                # 절대
          "by_score_bucket_relative": {"30~49": {...}, ...},       # 상대성과
        }
    """
    by_category: Dict[str, List[Dict]] = {}
    by_bucket: Dict[str, List[Dict]] = {}
    for row in results:
        cat = row.get("category") or "미분류"
        by_category.setdefault(cat, []).append(row)
        bucket = _bucket_for(row.get("score", 0))
        by_bucket.setdefault(bucket, []).append(row)

    return {
        "overall": _hit_rate(results, treat_dropout_as_fail=True),
        "overall_relative": _hit_rate(
            results, status_field="relative_status", treat_dropout_as_fail=True
        ),
        "by_category": {
            cat: _hit_rate(rows, treat_dropout_as_fail=True)
            for cat, rows in by_category.items()
        },
        "by_category_relative": {
            cat: _hit_rate(rows, status_field="relative_status", treat_dropout_as_fail=True)
            for cat, rows in by_category.items()
        },
        "by_score_bucket": {
            bucket: _hit_rate(rows, treat_dropout_as_fail=True)
            for bucket, rows in by_bucket.items()
        },
        "by_score_bucket_relative": {
            bucket: _hit_rate(rows, status_field="relative_status", treat_dropout_as_fail=True)
            for bucket, rows in by_bucket.items()
        },
    }


# ── 키워드 패턴별 적중 가중치 ──────────────────────────────────────────────────

def _normalize_keyword(keyword: str) -> str:
    """키워드에서 공통 패턴(어근)을 추출 — 단순 부분 일치를 위한 정규화."""
    return re.sub(r"[^\w가-힣]", "", keyword or "").strip()


def keyword_hit_weights(
    results: List[Dict],
    min_samples: int = 2,
    max_weight: float = 10.0,
) -> Dict[str, float]:
    """키워드 패턴별 과거 적중률을 다음 스코어링 가중치로 변환한다.

    중요: 적중률은 절대 변화 기준(status)이 아니라 시장효과(시즌효과)를 차감한
    상대성과 기준(relative_status)으로 계산한다. status 기준으로 가중치를 만들면
    제거하려던 시즌효과가 다음 시그널 점수에 다시 섞여 들어가기 때문이다
    (예: 겨울철에는 모든 키워드의 시장 평균 순위가 함께 오르므로 status 기준
    적중률은 항상 높게 나와 실제 키워드 효과를 왜곡한다).

    적중률 50%를 기준점(가중치 0)으로 보고, 그보다 높으면 양의 가중치(가산),
    낮으면 음의 가중치(감산)를 부여한다. 표본이 min_samples 미만이면 무시한다
    (과거 데이터가 부족한 키워드에 과도한 확신을 주지 않기 위함).

    적중률은 treat_dropout_as_fail=True로 계산한다 — 랭킹 이탈(품절/순위 밖
    탈락)을 "보류"로 빼고 적중/부분/실패만으로 적중률을 내면, 이탈이 많은
    키워드도 표본만 줄어들 뿐 적중률 자체는 깨끗하게(과대평가되어) 나온다.
    이탈을 실패로 포함시켜야 실제로 신뢰할 수 없는 키워드 패턴에 음의 가중치가
    정확히 반영된다.

    Args:
        results: evaluate()가 반환한 row 목록.
        min_samples: 가중치를 산출하기 위한 최소 완료(적중/부분/실패) 표본 수.
        max_weight: 가중치 절댓값 상한 (점수 폭주 방지).

    Returns:
        {keyword: weight} — timing_signal._score()에서 가산/감산용으로 사용.
        예: {"린넨": 6.0, "후드": -4.0}
    """
    by_keyword: Dict[str, List[Dict]] = {}
    for row in results:
        kw = _normalize_keyword(row.get("keyword", ""))
        if not kw:
            continue
        by_keyword.setdefault(kw, []).append(row)

    weights: Dict[str, float] = {}
    for kw, rows in by_keyword.items():
        # relative_status(시장효과 차감 상대성과)를 우선 사용 — status는 시즌효과가
        # 섞여 있어 다음 스코어링 가중치로 쓰면 누수가 발생한다.
        stats = _hit_rate(rows, status_field="relative_status", treat_dropout_as_fail=True)
        if stats["count"] < min_samples or stats["hit_rate"] is None:
            continue
        # 50%를 기준으로 -50%p ~ +50%p 편차를 가중치로 선형 변환.
        deviation = stats["hit_rate"] - 50.0
        weight = round(deviation / 50.0 * max_weight, 1)
        weight = max(-max_weight, min(max_weight, weight))
        if weight != 0:
            weights[kw] = weight
    return weights
