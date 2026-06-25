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
    forecasts: Optional[List[Dict]] = None,
    steady_dropouts: Optional[List[Dict]] = None,
    price_result: Optional[Dict] = None,
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

        weather_conflict = bool(signal.get("weather_conflict"))
        seasonal_adj = signal.get("seasonal_adjustment", 0) or 0

        evidence = [f"트렌드 {signal.get('trend_pct', 0):+.0f}%"]
        if signal.get("rank_change"):
            evidence.append(f"랭킹 {signal['rank_change']:+d}")
        if temp_max is not None:
            evidence.append(f"최고 {temp_max:.0f}도 {weather_label}")
        if weather_conflict:
            evidence.append(f"⚠️ 계절 보정 {seasonal_adj:+.1f}점")
        evidence.extend(signal.get("issues", [])[:1])

        breakdown = signal.get("score_breakdown") or {}
        next_checks = signal.get("next_checks") or []
        backtest_note = _backtest_note(backtest_stats, category, score)

        checklist = [
            f"무신사/29CM '{main_cat}' 카테고리 랭킹 TOP30에서 '{keyword}' 포함 상품 직접 검색·정렬 확인",
            "구글 트렌드/네이버 데이터랩에서 해당 키워드 검색량 추세가 일시 스파이크인지 지속 상승인지 7일 그래프로 재확인",
            "경쟁사(동일 카테고리 상위 브랜드) 할인율·재고 상태 확인",
        ]
        if weather_conflict:
            checklist.append(
                f"⚠️ 현재 최고 {temp_max:.0f}도 기준 계절 보정 {seasonal_adj:+.1f}점 — "
                f"'{keyword}' 같은 계절성 상품이 지금 날씨와 맞는지, 선행수요(다음 시즌 대비)인지 직접 판단 필요"
            )
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
        if weather_conflict:
            priority_reason_parts.append(f"⚠️ 계절 역행 가능성(보정 {seasonal_adj:+.1f}점) — 날씨 대비 시즌 적합성 재확인 필요")
        priority_reason = " / ".join(priority_reason_parts)

        links = []
        if signal.get("url"):
            links.append({"label": f"{signal.get('product_name') or keyword} 상품 페이지", "url": signal["url"]})

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
            "links": links,
        })

    for row in cross_platform[:2]:
        brand = row.get("brand", "")
        category = row.get("category", "")
        links = []
        if row.get("musinsa_url"):
            links.append({"label": f"무신사 {brand} {category} 최고순위 상품", "url": row["musinsa_url"]})
        if row.get("cm29_url"):
            links.append({"label": f"29CM {brand} {category} 최고순위 상품", "url": row["cm29_url"]})
        candidates.append({
            "title": f"{brand} '{category}' 양 플랫폼 반응 점검",
            "action": f"'{category}' 카테고리에서 동시 노출 상품과 가격대를 비교해 우선 노출 후보 선정",
            "deadline": "3일 내 검토",
            "confidence": row.get("score", 0),
            "evidence": [
                f"무신사 {category} {row['musinsa_count']}개",
                f"29CM {category} {row['cm29_count']}개",
                f"최고 {min(row['musinsa_best_rank'], row['cm29_best_rank'])}위",
            ],
            "source": "플랫폼 교차",
            "checklist": [
                f"무신사에서 '{brand}' 브랜드의 '{category}' 카테고리 상위 {row.get('musinsa_count',0)}개 상품 가격·할인 확인",
                f"29CM에서 동일 브랜드 '{category}' 상위 {row.get('cm29_count',0)}개 상품과 무신사 상품 가격대 비교",
                "두 플랫폼에서 겹치는 상품이 있는지, 있다면 노출 우선순위·프로모션 차이 확인",
            ],
            "where_to_look": [
                f"무신사 브랜드 랭킹/검색 페이지 — '{category}' 카테고리",
                f"29CM 브랜드 랭킹/검색 페이지 — '{category}' 카테고리",
                "대시보드 '플랫폼 교차' 섹션 표",
            ],
            "decision_criteria": (
                f"교차 점수 {row.get('score', 0)}점 — 같은 '{category}' 카테고리에서 양 플랫폼 동시 상위 노출이면 우선 노출 후보로 즉시 등록, "
                "한쪽 플랫폼에서만 강세면 약세 플랫폼 노출 전략(가격/프로모션) 점검"
            ),
            "priority_reason": f"'{category}' 카테고리 양 플랫폼 동시 반응 점수 {row.get('score', 0)}점 — 무신사 {row.get('musinsa_count',0)}개 · 29CM {row.get('cm29_count',0)}개 노출",
            "links": links,
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
            "links": [{"label": "대시보드 무신사 랭킹 섹션 바로가기", "url": "#musinsa-ranking"}],
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
            "links": [{"label": f"{product_name} 상품 페이지", "url": item["url"]}] if item.get("url") else [],
        })

    # 트렌드 예측 — 시그널화되기 전에 선제적으로 포착한 급등 예상 키워드.
    for forecast in (forecasts or [])[:2]:
        if forecast.get("trend_direction") != "↑상승" or forecast.get("data_points", 0) < 3:
            continue
        keyword = forecast.get("keyword", "")
        forecast_score = forecast.get("forecast_score", 0)
        growth_rate = forecast.get("growth_rate", 0)
        confidence_label = forecast.get("confidence", "낮음")
        candidates.append({
            "title": f"{keyword} 다음 주 급등 예상",
            "action": "선제적으로 관련 상품 재고·노출을 준비해 트렌드가 시그널화되기 전에 대응",
            "deadline": "1주일 내 준비",
            "confidence": min(100, int(forecast_score)),
            "evidence": [
                f"예측 점수 {forecast_score:.1f}",
                f"성장률 {growth_rate:+.0f}%",
                f"신뢰도 {confidence_label}",
            ],
            "source": "트렌드 예측",
            "checklist": [
                f"무신사/29CM에서 '{keyword}' 관련 상품 현재 재고·노출 현황 확인",
                f"'{keyword}' 검색량이 실제로 최근 며칠 지속 상승 중인지 트렌드 차트로 재확인",
                "경쟁사가 이미 관련 상품을 선점했는지 카테고리 랭킹에서 확인",
            ],
            "where_to_look": [
                "대시보드 '무신사 실시간 검색어 & 트렌드 예측' 섹션",
                "구글 트렌드/네이버 데이터랩 검색량 추이",
            ],
            "decision_criteria": (
                f"신뢰도 {confidence_label} — 데이터 포인트 {forecast.get('data_points',0)}개 기준. "
                "'높음'이면 1주일 내 상품 준비 시작, '보통'이면 2~3일 더 관찰 후 결정, '낮음'이면 참고만"
            ),
            "priority_reason": f"이동평균 기반 예측 점수 {forecast_score:.1f}, 성장률 {growth_rate:+.0f}% — 아직 시그널화 전 선제 포착",
            "links": [],
        })

    # 스테디셀러 이탈 — 검증된(연속 3회 이상 TOP10) 인기 상품이 오늘 갑자기 빠진 경우.
    for dropout in (steady_dropouts or [])[:2]:
        name = dropout.get("product_name", "")
        appearances = dropout.get("appearances", 0)
        candidates.append({
            "title": f"{name} 스테디셀러 이탈 경고",
            "action": "품절·재고 여부를 확인하고 필요 시 재노출 또는 재입고 일정 점검",
            "deadline": "오늘",
            "confidence": min(100, 60 + appearances * 2),
            "evidence": [
                f"연속 등장 {appearances}회",
                f"최고 {dropout.get('best_rank','-')}위",
                dropout.get("brand", ""),
            ],
            "source": "스테디셀러 이탈",
            "checklist": [
                f"무신사에서 '{name}' 상품 페이지 직접 접속 — 품절/판매중지 여부 확인",
                "품절이면 재입고 일정 확인, 정상 판매 중이면 노출 위치(메인/카테고리 정렬) 변경 여부 확인",
                "동일 브랜드의 유사 대체 상품이 랭킹에 새로 진입했는지 확인 (포지션 이전 가능성)",
            ],
            "where_to_look": [
                f"무신사 상품 상세페이지 — {name}",
                "대시보드 '스테디셀러' 섹션 — 과거 등장 이력",
            ],
            "decision_criteria": (
                f"{appearances}회 연속 등장하던 상품이 오늘 이탈 — 품절이면 재입고 후 즉시 재노출, "
                "정상 판매 중인데 이탈했다면 노출 로직(정렬/광고) 점검 필요"
            ),
            "priority_reason": f"{appearances}회 연속 TOP10 등장 상품의 갑작스런 이탈 — 검증된 수요 상품이므로 우선 확인 필요",
            "links": [{"label": f"{name} 상품 페이지", "url": dropout["url"]}] if dropout.get("url") else [],
        })

    # 카테고리 평균가 급변 — 신상품 진입/경쟁사 할인 시작·종료 등 가격 전략 신호.
    by_category = (price_result or {}).get("by_category", {})
    # 세분류(예: "상의_반소매티셔츠")는 상품 수가 적어 평균가 변동이 노이즈에
    # 가까울 수 있으므로, 표본이 안정적인 대분류 합계("_전체")만 본다.
    movers = [
        (cat.split("_")[0], data) for cat, data in by_category.items()
        if cat.endswith("_전체")
        and data.get("avg_change") is not None and abs(data["avg_change"]) >= 3000
    ]
    movers.sort(key=lambda kv: abs(kv[1]["avg_change"]), reverse=True)
    if movers:
        cat, data = movers[0]
        change = data["avg_change"]
        direction = "상승" if change > 0 else "하락"
        top_discounts = (price_result or {}).get("top_discounts", [])
        evidence = [
            f"평균가 {data['avg']:,}원 (전일비 {change:+,}원)",
            f"최빈 가격대 {data.get('mode_bracket','-')}",
        ]
        if top_discounts:
            evidence.append(f"할인율 최고 {top_discounts[0].get('discount_rate',0)}% ({top_discounts[0].get('brand','')})")
        candidates.append({
            "title": f"'{cat}' 평균가 {direction} 점검",
            "action": "평균가 변동 원인(신상품/할인 종료/구성 변화)을 확인해 가격 전략에 반영",
            "deadline": "2~3일 내 검토",
            "confidence": min(100, 50 + int(abs(change) / 1000)),
            "evidence": evidence,
            "source": "가격대 변동",
            "checklist": [
                f"'{cat}' 카테고리 TOP30 상품 구성이 어제와 달라졌는지(신상품 진입/이탈) 확인",
                "경쟁 브랜드 할인 시작/종료 여부 확인 — 할인 종료면 평균가 자연 상승, 할인 시작이면 하락",
                "동일 가격 변동이 다른 카테고리에서도 동시에 나타나는지 확인 (시즌 전체 가격 전략 변화 가능성)",
            ],
            "where_to_look": [
                "대시보드 '트렌드 & 가격 분포' 섹션",
                f"무신사 '{cat}' 카테고리 랭킹 — 가격 정렬",
            ],
            "decision_criteria": (
                f"전일 대비 {change:+,}원 — 변동폭이 평균가의 10% 이상이면 즉시 원인 파악, "
                "10% 미만이면 단순 변동으로 보고 1~2일 추가 관찰"
            ),
            "priority_reason": f"'{cat}' 카테고리 평균가가 전일 대비 {change:+,}원 {direction} — 가격대 변화는 보통 신상품 진입이나 경쟁사 프로모션과 연관",
            "links": [],
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
