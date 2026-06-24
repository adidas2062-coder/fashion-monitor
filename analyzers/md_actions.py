"""공개 시장 신호를 MD가 실행할 수 있는 액션으로 요약한다.

각 액션 카드는 다음 실무 디테일 필드를 포함한다:
  - checklist:        오늘 바로 확인할 구체적 항목 리스트.
  - where_to_look:     어떤 페이지/지표를 봐야 하는지.
  - decision_criteria: 진행/보류를 가르는 구체적 판단 기준.
  - priority_reason:   이 카드가 왜 이 우선순위(confidence)를 받았는지 설명.

backtest_stats(signal_backtest.aggregate_stats() 반환)가 주어지면 동일 카테고리/
점수대의 과거 적중률을 근거로 활용해 카드 디테일을 더 구체화한다.
"""

from typing import Dict, List, Optional


def _score_bucket_label(score: float) -> str:
    if score >= 80:
        return "80+"
    if score >= 50:
        return "50~79"
    return "30~49"


def _backtest_note(
    backtest_stats: Optional[Dict], category: str, score: float
) -> Optional[str]:
    """카테고리/점수대별 과거 적중률을 한 줄 근거 문구로 변환.

    절대 적중률(status 기준)만 보여주면 겨울철처럼 시장 전체(시즌효과)가 같은
    방향으로 움직이는 시기의 동반 상승을 "이 카테고리/점수대 자체의 성과"로
    MD가 오인할 수 있다. 따라서 시장효과를 차감한 상대성과 적중률
    (by_category_relative/by_score_bucket_relative)을 우선 표기하고, 절대
    적중률은 참고용으로 병기해 둘을 명확히 구분한다.
    """
    if not backtest_stats:
        return None
    by_cat = backtest_stats.get("by_category", {})
    by_cat_rel = backtest_stats.get("by_category_relative", {})
    by_bucket = backtest_stats.get("by_score_bucket", {})
    by_bucket_rel = backtest_stats.get("by_score_bucket_relative", {})
    notes = []

    cat_stat = by_cat.get(category) if category else None
    cat_stat_rel = by_cat_rel.get(category) if category else None
    if cat_stat and cat_stat.get("hit_rate") is not None:
        rel_txt = (
            f", 시장효과 차감 {cat_stat_rel['hit_rate']:.0f}%"
            if cat_stat_rel and cat_stat_rel.get("hit_rate") is not None
            else ""
        )
        notes.append(
            f"'{category}' 카테고리 과거 적중률(절대) {cat_stat['hit_rate']:.0f}%{rel_txt}"
            f"(표본 {cat_stat['count']}건)"
        )

    bucket = _score_bucket_label(score)
    bucket_stat = by_bucket.get(bucket)
    bucket_stat_rel = by_bucket_rel.get(bucket)
    if bucket_stat and bucket_stat.get("hit_rate") is not None:
        rel_txt = (
            f", 시장효과 차감 {bucket_stat_rel['hit_rate']:.0f}%"
            if bucket_stat_rel and bucket_stat_rel.get("hit_rate") is not None
            else ""
        )
        notes.append(
            f"점수대 {bucket}점 과거 적중률(절대) {bucket_stat['hit_rate']:.0f}%{rel_txt}"
            f"(표본 {bucket_stat['count']}건)"
        )
    return " · ".join(notes) if notes else None


def build(
    signals: List[Dict],
    weather: Dict,
    cross_platform: List[Dict],
    reviewed_entries: List[Dict],
    limit: int = 3,
    backtest_stats: Optional[Dict] = None,
) -> List[Dict]:
    candidates: List[Dict] = []
    temp_max = weather.get("temp_max")
    weather_label = weather.get("weather_label", "")
    category_signal = weather.get("category_signal", {})

    for signal in signals:
        keyword = signal.get("keyword", "")
        category = signal.get("category", "")
        main_cat = category.split("_")[0] if category else (keyword or "해당 카테고리")
        score = signal.get("score", 0)

        evidence = [f"트렌드 {signal.get('trend_pct', 0):+.0f}%"]
        if signal.get("rank_change"):
            evidence.append(f"랭킹 {signal['rank_change']:+d}")
        if temp_max is not None:
            evidence.append(f"최고 {temp_max:.0f}도 {weather_label}")
        evidence.extend(signal.get("issues", [])[:1])

        breakdown = signal.get("score_breakdown") or {}
        next_checks = signal.get("next_checks") or []
        backtest_note = _backtest_note(backtest_stats, category, score)

        checklist = [
            f"무신사/29CM '{main_cat}' 카테고리 랭킹 TOP30에서 '{keyword}' 포함 상품 직접 검색·정렬 확인",
            "구글 트렌드/네이버 데이터랩에서 해당 키워드 검색량 추세가 일시 스파이크인지 지속 상승인지 7일 그래프로 재확인",
            "경쟁사(동일 카테고리 상위 브랜드) 할인율·재고 상태 확인",
        ]
        checklist.extend(next_checks[:3])

        where_to_look = [
            f"무신사 랭킹 페이지 — {main_cat} 카테고리 1일/주간 탭",
            "대시보드 '기획전 시그널' 섹션의 score_breakdown(지표별 기여 점수)",
            "대시보드 '백테스트' 섹션 — 동일 카테고리/점수대 과거 적중 사례",
        ]

        score_range = signal.get("score_range") or signal.get("confidence_band") or {}
        decision_criteria = (
            f"점수 {score}점"
            + (f" (범위 {score_range.get('low','-')}~{score_range.get('high','-')}, 보강 지표 개수 기반 휴리스틱)" if score_range else "")
            + " — 80점 이상이면 3~5일 내 즉시 기획전 오픈 검토, 50~79점이면 1주일 내 추가 데이터 확인 후 결정, "
            "50점 미만이면 트렌드 단독 신호이므로 1~2일 더 관찰 후 재평가"
        )

        priority_reason_parts = [f"신뢰도 점수 {score}점"]
        if breakdown:
            top_factor = max(breakdown.items(), key=lambda kv: kv[1])
            if top_factor[1] > 0:
                priority_reason_parts.append(f"주요 기여 지표: {top_factor[0]}({top_factor[1]:+.0f}점)")
        if backtest_note:
            priority_reason_parts.append(f"백테스트 근거: {backtest_note}")
        priority_reason = " / ".join(priority_reason_parts)

        candidates.append({
            "title": signal.get("theme") or f"{keyword} 기획전 검토",
            "action": "관련 상품 구성과 경쟁 할인율을 확인해 기획전 오픈 여부 검토",
            "deadline": signal.get("open_label", "이번 주 검토"),
            "confidence": score,
            "evidence": evidence[:3],
            "source": "기획전 시그널",
            "checklist": checklist,
            "where_to_look": where_to_look,
            "decision_criteria": decision_criteria,
            "priority_reason": priority_reason,
        })

    for row in cross_platform[:2]:
        brand = row.get("brand", "")
        candidates.append({
            "title": f"{brand} 양 플랫폼 반응 점검",
            "action": "동시 노출 상품과 가격대를 비교해 우선 노출 후보 선정",
            "deadline": "3일 내 검토",
            "confidence": row.get("score", 0),
            "evidence": [
                f"무신사 {row['musinsa_count']}개",
                f"29CM {row['cm29_count']}개",
                f"최고 {min(row['musinsa_best_rank'], row['cm29_best_rank'])}위",
            ],
            "source": "플랫폼 교차",
            "checklist": [
                f"무신사에서 '{brand}' 브랜드관/검색 결과 상위 {row.get('musinsa_count',0)}개 상품 가격·할인 확인",
                f"29CM에서 동일 브랜드 상위 {row.get('cm29_count',0)}개 상품과 무신사 상품 가격대 비교",
                "두 플랫폼에서 겹치는 상품이 있는지, 있다면 노출 우선순위·프로모션 차이 확인",
            ],
            "where_to_look": [
                "무신사 브랜드 랭킹/검색 페이지",
                "29CM 브랜드 랭킹/검색 페이지",
                "대시보드 '플랫폼 교차' 섹션 표",
            ],
            "decision_criteria": (
                f"교차 점수 {row.get('score', 0)}점 — 양 플랫폼 동시 상위 노출이면 우선 노출 후보로 즉시 등록, "
                "한쪽 플랫폼에서만 강세면 약세 플랫폼 노출 전략(가격/프로모션) 점검"
            ),
            "priority_reason": f"양 플랫폼 동시 반응 점수 {row.get('score', 0)}점 — 무신사 {row.get('musinsa_count',0)}개 · 29CM {row.get('cm29_count',0)}개 노출",
        })

    if category_signal and temp_max is not None:
        demand = " · ".join(
            f"{category} {signal}"
            for category, signal in category_signal.items()
        )
        candidates.append({
            "title": f"{temp_max:.0f}도 날씨 대응 상품 점검",
            "action": "날씨 수요 신호와 맞는 상품의 노출·재고·기획전 구성을 우선 확인",
            "deadline": "오늘",
            "confidence": 68,
            "evidence": [
                f"최고 {temp_max:.0f}도 {weather_label}",
                demand,
                "3일 예보 기준",
            ],
            "source": "날씨 수요",
            "checklist": [
                f"오늘 최고 {temp_max:.0f}도 기준, 날씨 수요 카테고리({demand})의 무신사 메인 노출 상품 확인",
                "해당 카테고리 재고/품절 현황 확인 — 품절이면 노출 확대 보류",
                "3일 예보 추이 확인 — 기온 변화 방향이 같은 카테고리에 유지/반대되는지 점검",
            ],
            "where_to_look": [
                "대시보드 '날씨' 섹션 — 카테고리별 수요 신호",
                "무신사/29CM 메인 노출 배너 및 카테고리 랭킹",
                "Open-Meteo 3일 예보(기온 추이)",
            ],
            "decision_criteria": (
                "예보상 기온 추세가 동일 방향으로 2일 이상 유지되면 노출 확대, "
                "기온이 반대로 꺾일 예정이면 노출 확대를 보류하고 관찰"
            ),
            "priority_reason": "날씨 기반 규칙 점수 68점 — 계절 적합 카테고리에 대한 정형화된 우선순위 신호",
        })

    for item in reviewed_entries:
        review = item.get("review_analysis", {})
        if not review or review.get("sentiment_score", 100) >= 55:
            continue
        product_name = item.get("product_name", "")
        candidates.append({
            "title": f"{product_name} 리뷰 주의",
            "action": "사이즈와 품질 불만을 확인한 뒤 노출 확대 여부 판단",
            "deadline": "노출 확대 전",
            "confidence": 70,
            "evidence": [
                review.get("summary", "부정 의견 확인"),
                f"부정 키워드 {', '.join(review.get('top_negative', [])[:2]) or '-'}",
                f"분석 리뷰 {review.get('review_count', 0)}개",
            ],
            "source": "리뷰 인사이트",
            "checklist": [
                f"'{product_name}' 상품 상세페이지 리뷰 탭에서 부정 키워드({', '.join(review.get('top_negative', [])[:2]) or '-'}) 원문 확인",
                "사이즈 표기와 실측 정보가 일치하는지, 사이즈 가이드 보완이 필요한지 확인",
                "동일 부정 키워드가 반복되는 유사 상품이 있는지 카테고리 내 확인",
            ],
            "where_to_look": [
                f"무신사 상품 상세페이지 — {product_name} 리뷰 탭",
                "대시보드 '리뷰 인사이트' 섹션",
            ],
            "decision_criteria": (
                f"감성 점수 {review.get('sentiment_score', 0):.0f}점 — 50점 미만이면 노출 확대 중단 및 상세페이지 보완, "
                "50~55점이면 사이즈 가이드만 보완 후 유지"
            ),
            "priority_reason": f"부정 리뷰 비중이 높아 감성 점수 {review.get('sentiment_score', 0):.0f}점 — 노출 확대 전 리스크 점검 필요",
        })

    candidates.sort(key=lambda row: row.get("confidence", 0), reverse=True)

    # source 중복 제거: 같은 source(예: "기획전 시그널")의 후보가 여러 개 있어도
    # confidence가 가장 높은 1개만 채택한다. 동일 source 후보가 limit을 채우고도
    # 남을 만큼 많을 때, 두 번째(채움용) 루프에서 다시 추가되어 결과에
    # ["기획전 시그널", "기획전 시그널", ...]처럼 중복이 생기는 회귀를 방지하기
    # 위해, 채움 루프도 동일하게 used_sources를 검사해 끝까지 source당 1건만
    # 허용한다(고유 source 수가 limit보다 적을 때만 자연히 limit 미만으로 반환).
    selected: List[Dict] = []
    used_sources = set()
    for candidate in candidates:
        if candidate["source"] in used_sources:
            continue
        selected.append(candidate)
        used_sources.add(candidate["source"])
        if len(selected) == limit:
            break
    return selected
