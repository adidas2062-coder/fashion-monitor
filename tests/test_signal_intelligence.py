"""신규 고도화 로직(상대성과 백테스트/백테스트 피드백/점진적 날씨 보정/MD 액션 디테일) 테스트."""

import unittest
from datetime import date

from analyzers import md_actions, signal_backtest, timing_signal


class SignalBacktestRelativePerformanceTest(unittest.TestCase):
    """시장효과(시즌효과)를 분리한 상대성과 판정 및 통계 함수 검증."""

    def test_relative_change_subtracts_market_baseline(self):
        # 시장 전체가 같은 기간 동안 평균 5계단 상승(시즌효과)했고,
        # 시그널 상품은 6계단 상승했다면 순수 기여분(상대성과)은 1계단에 불과하다.
        signals = {
            "2026-06-01": [{
                "keyword": "린넨", "theme": "린넨 기획전", "score": 80,
                "product_name": "", "category": "상의_전체",
            }]
        }
        rankings = {
            "2026-06-01": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 10},
                {"period": "1일", "category": "상의_전체", "product_name": "기타1", "rank": 20},
                {"period": "1일", "category": "상의_전체", "product_name": "기타2", "rank": 30},
            ],
            "2026-06-08": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 4},
                {"period": "1일", "category": "상의_전체", "product_name": "기타1", "rank": 15},
                {"period": "1일", "category": "상의_전체", "product_name": "기타2", "rank": 25},
            ],
        }
        result = signal_backtest.evaluate(signals, rankings, date(2026, 6, 10))
        row = result[0]
        # 기존 절대 적중 판정은 그대로 유지된다.
        self.assertEqual("적중", row["status"])
        self.assertEqual(6.0, row["day7_change"])
        # 신규: 시그널 상품을 제외한 동일 코호트(기타1/기타2)는 둘 다 5계단씩 상승했으므로
        # 시장 평균(시즌효과)도 5.0계단 — 상대성과는 1계단에 불과하다.
        self.assertAlmostEqual(5.0, row["market_day7_change"], places=1)
        self.assertAlmostEqual(1.0, row["relative_day7_change"], places=1)
        # 상대성과 기준 판정은 절대 status와 달리 "부분 적중" 또는 "실패"에 가깝다.
        self.assertIn(row["relative_status"], ("부분 적중", "실패"))

    def test_market_baseline_excludes_signal_product_and_uses_fixed_cohort(self):
        """TOP N 랭킹이 매일 1~N을 유지해도(평균 항상 동일) 시장 기준선이 0이 되지 않아야
        하며, 시그널 상품 자신은 코호트에서 제외되어 누수가 없어야 한다."""
        signals = {
            "2026-06-01": [{
                "keyword": "린넨", "theme": "린넨 기획전", "score": 80,
                "product_name": "", "category": "상의_전체",
            }]
        }
        rankings = {
            "2026-06-01": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 1},
                {"period": "1일", "category": "상의_전체", "product_name": "A", "rank": 2},
                {"period": "1일", "category": "상의_전체", "product_name": "B", "rank": 3},
            ],
            # 7일 후에도 TOP3는 그대로 1~3위를 채우지만(평균은 항상 2.0으로 동일),
            # 코호트(A, B)의 실제 순위는 변하지 않았다 — 시장효과는 0이어야 한다.
            "2026-06-08": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 1},
                {"period": "1일", "category": "상의_전체", "product_name": "A", "rank": 2},
                {"period": "1일", "category": "상의_전체", "product_name": "B", "rank": 3},
            ],
        }
        result = signal_backtest.evaluate(signals, rankings, date(2026, 6, 10))
        row = result[0]
        self.assertEqual(0.0, row["market_day7_change"])
        self.assertEqual(0.0, row["day7_change"])
        self.assertEqual(0.0, row["relative_day7_change"])

    def test_nearest_snapshot_fallback_when_exact_date_missing(self):
        """+7일 정확한 날짜 스냅샷이 없어도(휴일 등) 그 이후 가장 가까운 수집일을
        사용해 계속 '보류' 상태에 머물지 않아야 한다."""
        signals = {
            "2026-06-01": [{
                "keyword": "린넨", "theme": "린넨 기획전", "score": 80,
                "product_name": "", "category": "상의_전체",
            }]
        }
        rankings = {
            "2026-06-01": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 10},
            ],
            # 정확히 2026-06-08(+7일)은 없지만 2026-06-09(+8일)에 데이터가 있다.
            "2026-06-09": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 4},
            ],
        }
        result = signal_backtest.evaluate(signals, rankings, date(2026, 6, 12))
        row = result[0]
        self.assertEqual("2026-06-09", row["day7_snapshot_date"])
        self.assertEqual(6.0, row["day7_change"])
        self.assertNotEqual("보류", row["status"])

    def test_existing_keys_preserved(self):
        signals = {"2026-06-01": [{"keyword": "린넨", "theme": "린넨 기획전", "score": 80,
                                    "product_name": "", "category": "상의_전체"}]}
        rankings = {"2026-06-01": [{"period": "1일", "category": "상의_전체",
                                     "product_name": "린넨 셔츠", "rank": 10}]}
        result = signal_backtest.evaluate(signals, rankings, date(2026, 6, 10))
        required_keys = {
            "signal_date", "keyword", "theme", "score", "base_rank",
            "day3_change", "day7_change", "status", "reason",
        }
        self.assertTrue(required_keys.issubset(result[0].keys()))


class SignalBacktestAggregateStatsTest(unittest.TestCase):
    def test_aggregate_stats_by_category_and_bucket(self):
        results = [
            {"category": "상의_전체", "score": 85, "status": "적중", "relative_status": "적중"},
            {"category": "상의_전체", "score": 40, "status": "실패", "relative_status": "실패"},
            {"category": "바지_전체", "score": 60, "status": "부분 적중", "relative_status": "부분 적중"},
        ]
        stats = signal_backtest.aggregate_stats(results)
        self.assertIn("overall", stats)
        self.assertIn("by_category", stats)
        self.assertIn("by_score_bucket", stats)
        self.assertEqual(3, stats["overall"]["count"])
        self.assertEqual(2, stats["by_category"]["상의_전체"]["count"])
        self.assertEqual(1, stats["by_category"]["바지_전체"]["count"])
        self.assertIn("80+", stats["by_score_bucket"])
        self.assertIn("30~49", stats["by_score_bucket"])
        self.assertIn("50~79", stats["by_score_bucket"])

    def test_keyword_hit_weights_direction(self):
        # '린넨'은 (상대성과 기준) 적중 2건/실패 0건 → 높은 적중률 → 양의 가중치.
        # '후드'는 적중 0건/실패 2건 → 낮은 적중률 → 음의 가중치.
        # 가중치는 절대 status가 아니라 시장효과를 제거한 relative_status로 계산되므로
        # status는 일부러 반대로 섞어 relative_status만 반영됨을 검증한다.
        results = [
            {"keyword": "린넨", "status": "실패", "relative_status": "적중"},
            {"keyword": "린넨", "status": "실패", "relative_status": "적중"},
            {"keyword": "후드", "status": "적중", "relative_status": "실패"},
            {"keyword": "후드", "status": "적중", "relative_status": "실패"},
        ]
        weights = signal_backtest.keyword_hit_weights(results)
        self.assertGreater(weights.get("린넨", 0), 0)
        self.assertLess(weights.get("후드", 0), 0)

    def test_keyword_hit_weights_ignores_low_sample(self):
        results = [{"keyword": "슬랙스", "status": "적중", "relative_status": "적중"}]
        weights = signal_backtest.keyword_hit_weights(results, min_samples=2)
        self.assertNotIn("슬랙스", weights)

    def test_aggregate_stats_provides_relative_breakdown_by_category_and_bucket(self):
        """카테고리/점수대별 통계도 절대(status) 기준뿐 아니라 시장효과를 차감한
        상대성과(relative_status) 기준을 함께 제공해야 한다 — 절대 적중률만 노출하면
        시즌 동반상승을 카테고리/점수대 자체의 성과로 오인할 수 있다."""
        results = [
            {"category": "상의_전체", "score": 85, "status": "적중", "relative_status": "실패"},
            {"category": "상의_전체", "score": 85, "status": "적중", "relative_status": "실패"},
        ]
        stats = signal_backtest.aggregate_stats(results)
        self.assertIn("by_category_relative", stats)
        self.assertIn("by_score_bucket_relative", stats)
        # 절대 기준으로는 100% 적중이지만, 상대성과 기준으로는 0%(전부 실패) — 시즌효과 분리.
        self.assertEqual(100.0, stats["by_category"]["상의_전체"]["hit_rate"])
        self.assertEqual(0.0, stats["by_category_relative"]["상의_전체"]["hit_rate"])
        self.assertEqual(0.0, stats["by_score_bucket_relative"]["80+"]["hit_rate"])


class TimingSignalBacktestFeedbackTest(unittest.TestCase):
    """timing_signal.detect()의 백테스트 피드백 반영 및 신규 필드 검증."""

    def _base_args(self):
        trend_data = [{"keyword": "#린넨", "change_pct": 60}]
        rank_result = {
            "items": [{"product_name": "린넨 셔츠", "category": "상의_전체",
                       "rank": 3, "rank_change": 8, "discount_rate": 10}],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        return trend_data, rank_result

    def test_existing_positional_calls_still_work(self):
        trend_data, rank_result = self._base_args()
        # main.py 스타일 4-위치인자 호출.
        signals = timing_signal.detect(trend_data, rank_result, [], {"temp_max": 20})
        self.assertTrue(signals)
        # api_server.py 스타일 3-위치인자 호출.
        signals2 = timing_signal.detect([], {"items": [], "new_entries": [], "top_risers": [], "top_fallers": []}, [])
        self.assertEqual([], signals2)

    def test_backtest_feedback_changes_score(self):
        trend_data, rank_result = self._base_args()
        base = timing_signal.detect(trend_data, rank_result, None, None)
        boosted = timing_signal.detect(trend_data, rank_result, None, None, {"린넨": 8.0})
        penalized = timing_signal.detect(trend_data, rank_result, None, None, {"린넨": -8.0})
        self.assertGreater(boosted[0]["score"], base[0]["score"])
        self.assertLess(penalized[0]["score"], base[0]["score"])

    def test_score_breakdown_and_next_checks_present(self):
        trend_data, rank_result = self._base_args()
        signals = timing_signal.detect(trend_data, rank_result, None, {"temp_max": 20})
        signal = signals[0]
        self.assertIn("score_breakdown", signal)
        self.assertIn("trend", signal["score_breakdown"])
        self.assertIn("confidence_band", signal)
        self.assertIn("low", signal["confidence_band"])
        self.assertIn("high", signal["confidence_band"])
        self.assertIn("evidence_detail", signal)
        self.assertTrue(len(signal["evidence_detail"]) > 0)
        self.assertIn("next_checks", signal)
        self.assertTrue(len(signal["next_checks"]) > 0)

    def test_graduated_weather_penalty_not_flat_onoff(self):
        trend_data = [{"keyword": "#후드", "change_pct": 60}]
        rank_result = {
            "items": [{"product_name": "후드 집업", "category": "상의_전체",
                       "rank": 3, "rank_change": 8, "discount_rate": 0}],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        mild = timing_signal.detect(trend_data, rank_result, None, {"temp_max": 25})
        hot = timing_signal.detect(trend_data, rank_result, None, {"temp_max": 33})
        # 둘 다 역행 페널티가 있지만, 더 더운 날씨가 더 큰 페널티(더 낮은 점수)를 받아야 한다 — 단순 on/off가 아님.
        self.assertNotEqual(mild[0]["score"], hot[0]["score"])
        self.assertLess(hot[0]["score"], mild[0]["score"])
        self.assertLess(hot[0]["seasonal_adjustment"], mild[0]["seasonal_adjustment"])

    def test_trend_only_signal_does_not_get_new_entry_rank_credit(self):
        """랭킹 매칭이 전혀 없는 트렌드 단독 시그널은 '신규 진입'으로 오판해
        랭킹 25점을 받으면 안 된다 (회귀 테스트)."""
        trend_data = [{"keyword": "레이어드", "change_pct": 60}]
        rank_result = {"items": [], "new_entries": [], "top_risers": [], "top_fallers": []}
        signals = timing_signal.detect(trend_data, rank_result)
        self.assertTrue(signals)
        signal = signals[0]
        self.assertFalse(signal["is_new_entry"])
        self.assertFalse(signal["has_rank_match"])
        self.assertEqual(0, signal["score_breakdown"]["rank"])
        self.assertEqual(30, signal["score"])  # 트렌드 30점만 인정.

    def test_true_new_entry_still_gets_full_rank_credit(self):
        """실제로 new_entries에 잡힌 신규 진입 상품은 여전히 랭킹 만점을 받아야 한다."""
        trend_data = [{"keyword": "레이어드", "change_pct": 60}]
        rank_result = {
            "items": [],
            "new_entries": [{"product_name": "레이어드 니트", "category": "상의_전체", "rank": 5}],
            "top_risers": [], "top_fallers": [],
        }
        signals = timing_signal.detect(trend_data, rank_result)
        signal = signals[0]
        self.assertTrue(signal["is_new_entry"])
        self.assertTrue(signal["has_rank_match"])
        self.assertEqual(25, signal["score_breakdown"]["rank"])

    def test_seasonal_adjustment_varies_by_category(self):
        """동일 키워드·기온이라도 매칭된 상품의 카테고리(아우터 vs 바지)에 따라
        계절 보정값이 달라야 한다 (회귀 테스트)."""
        trend_data = [{"keyword": "니트", "change_pct": 60}]
        outer_result = {
            "items": [{"product_name": "니트 가디건", "category": "아우터_전체",
                       "rank": 3, "rank_change": 8, "discount_rate": 0}],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        pants_result = {
            "items": [{"product_name": "니트 팬츠", "category": "바지_전체",
                       "rank": 3, "rank_change": 8, "discount_rate": 0}],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        outer_signals = timing_signal.detect(trend_data, outer_result, None, {"temp_max": 30})
        pants_signals = timing_signal.detect(trend_data, pants_result, None, {"temp_max": 30})
        # 아우터는 계절 민감도 배수가 더 커서(1.2배) 바지(0.7배)보다 페널티가 크다(더 낮은 점수).
        self.assertNotEqual(outer_signals[0]["seasonal_adjustment"], pants_signals[0]["seasonal_adjustment"])
        self.assertLess(outer_signals[0]["seasonal_adjustment"], pants_signals[0]["seasonal_adjustment"])

    def test_discount_surge_requires_day_over_day_increase(self):
        """할인율 급등은 '현재 평균 할인율이 5% 이상'이 아니라 전일 대비 +5%p 상승이어야 한다."""
        trend_data = [{"keyword": "린넨", "change_pct": 60}]
        rank_result = {
            "items": [{"product_name": "린넨 셔츠", "category": "상의_전체",
                       "rank": 3, "rank_change": 8, "discount_rate": 20}],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        # 어제도 이미 평균 20% 할인 중이었다면(상시 할인) 급등이 아니다.
        flat_history = [
            [{"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "discount_rate": 20}],
            [{"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "discount_rate": 20}],
        ]
        signals_flat = timing_signal.detect(trend_data, rank_result, None, None, None, flat_history)
        self.assertFalse(signals_flat[0]["discount_surge"])

        # 어제 5% → 오늘 20%로 급등했다면 진짜 급등이다.
        surge_history = [
            [{"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "discount_rate": 5}],
            [{"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "discount_rate": 5}],
        ]
        signals_surge = timing_signal.detect(trend_data, rank_result, None, None, None, surge_history)
        self.assertTrue(signals_surge[0]["discount_surge"])

    def test_discount_surge_no_history_does_not_use_absolute_threshold(self):
        """히스토리가 없거나 2일 미만이면 '오늘 평균 할인율 5% 이상'이라는 절대
        임계값으로 급등을 추정하지 않는다(상시 할인 카테고리 오인 방지). 점수는
        0으로 처리되고, discount_history_insufficient=True와 next_checks 경고가
        대신 노출되어야 한다."""
        trend_data = [{"keyword": "린넨", "change_pct": 60}]
        rank_result = {
            "items": [{"product_name": "린넨 셔츠", "category": "상의_전체",
                       "rank": 3, "rank_change": 8, "discount_rate": 20}],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        # 히스토리 자체가 없는 경우 (None)
        signals_no_history = timing_signal.detect(trend_data, rank_result, None, None, None, None)
        self.assertFalse(signals_no_history[0]["discount_surge"])
        self.assertTrue(signals_no_history[0]["discount_history_insufficient"])
        self.assertEqual(signals_no_history[0]["score_breakdown"]["discount_surge"], 0)
        self.assertTrue(
            any("할인율 히스토리" in c for c in signals_no_history[0]["next_checks"])
        )

        # 히스토리가 1일분만 있는 경우(2일 미만)도 동일하게 보수적으로 처리.
        single_day_history = [
            [{"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "discount_rate": 20}],
        ]
        signals_short = timing_signal.detect(trend_data, rank_result, None, None, None, single_day_history)
        self.assertFalse(signals_short[0]["discount_surge"])
        self.assertTrue(signals_short[0]["discount_history_insufficient"])

    def test_unclassified_keyword_extreme_temp_no_penalty(self):
        """계절 사전(겨울/여름 키워드)에 없는 키워드는 폭염/한파에서도 점수 페널티를
        받지 않아야 한다(예: 35도의 '데님 팬츠'). 대신 next_checks에 직접 확인하라는
        경고만 노출되어야 한다."""
        trend_data = [{"keyword": "데님 팬츠", "change_pct": 60}]
        rank_result = {
            "items": [{"product_name": "데님 팬츠 와이드", "category": "바지_데님팬츠",
                       "rank": 3, "rank_change": 8, "discount_rate": 0}],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        hot_signals = timing_signal.detect(trend_data, rank_result, None, {"temp_max": 35})
        signal = hot_signals[0]
        self.assertEqual(signal["seasonal_adjustment"], 0.0)
        self.assertTrue(
            any("계절 사전" in c for c in signal["next_checks"])
        )

        cold_signals = timing_signal.detect(trend_data, rank_result, None, {"temp_max": -3})
        self.assertEqual(cold_signals[0]["seasonal_adjustment"], 0.0)
        self.assertTrue(
            any("계절 사전" in c for c in cold_signals[0]["next_checks"])
        )

    def test_price_competitiveness_bonus_for_outlier_price(self):
        """동일 카테고리 평균가 대비 30% 이상 벗어난 가격대인데도 랭킹이 급등하면
        가격 경쟁력 보너스(최대 +3점)가 score_breakdown에 반영되어야 한다."""
        trend_data = [{"keyword": "린넨", "change_pct": 60}]
        rank_result = {
            "items": [
                {"product_name": "린넨 셔츠", "category": "상의_전체",
                 "rank": 3, "rank_change": 8, "discount_rate": 0, "price": 20000},
                {"product_name": "기타1", "category": "상의_전체", "price": 50000},
                {"product_name": "기타2", "category": "상의_전체", "price": 55000},
                {"product_name": "기타3", "category": "상의_전체", "price": 48000},
            ],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        signals = timing_signal.detect(trend_data, rank_result)
        signal = signals[0]
        self.assertGreater(signal["score_breakdown"]["price_competitiveness"], 0)
        self.assertIn("price_note", signal)
        self.assertIsNotNone(signal["price_note"])

    def test_price_competitiveness_no_bonus_for_typical_price(self):
        trend_data = [{"keyword": "린넨", "change_pct": 60}]
        rank_result = {
            "items": [
                {"product_name": "린넨 셔츠", "category": "상의_전체",
                 "rank": 3, "rank_change": 8, "discount_rate": 0, "price": 50000},
                {"product_name": "기타1", "category": "상의_전체", "price": 49000},
                {"product_name": "기타2", "category": "상의_전체", "price": 51000},
                {"product_name": "기타3", "category": "상의_전체", "price": 50000},
            ],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        signals = timing_signal.detect(trend_data, rank_result)
        signal = signals[0]
        self.assertEqual(0.0, signal["score_breakdown"]["price_competitiveness"])


class MdActionsDetailTest(unittest.TestCase):
    def test_action_cards_have_md_detail_fields(self):
        actions = md_actions.build(
            [{"theme": "린넨 기획전", "score": 85, "trend_pct": 40, "issues": [],
              "keyword": "린넨", "category": "상의_전체"}],
            {"temp_max": 31, "weather_label": "맑음"},
            [{"brand": "A", "score": 60, "musinsa_count": 1, "cm29_count": 1,
              "musinsa_best_rank": 3, "cm29_best_rank": 5}],
            [],
        )
        for action in actions:
            self.assertIn("checklist", action)
            self.assertIn("where_to_look", action)
            self.assertIn("decision_criteria", action)
            self.assertIn("priority_reason", action)
            self.assertTrue(isinstance(action["checklist"], list))
            self.assertTrue(isinstance(action["where_to_look"], list))

    def test_limit_and_priority_unchanged(self):
        actions = md_actions.build(
            [{"theme": "린넨 기획전", "score": 85, "trend_pct": 40, "issues": []}],
            {"temp_max": 31, "weather_label": "맑음"},
            [{"brand": "A", "score": 60, "musinsa_count": 1, "cm29_count": 1,
              "musinsa_best_rank": 3, "cm29_best_rank": 5}],
            [],
        )
        self.assertEqual("린넨 기획전", actions[0]["title"])
        self.assertLessEqual(len(actions), 3)
        self.assertEqual(len(actions), len({row["source"] for row in actions}))

    def test_backtest_stats_used_in_priority_reason(self):
        backtest_stats = {
            "by_category": {"상의_전체": {"hit_rate": 75.0, "count": 4}},
            "by_score_bucket": {"80+": {"hit_rate": 80.0, "count": 5}},
        }
        actions = md_actions.build(
            [{"theme": "린넨 기획전", "score": 85, "trend_pct": 40, "issues": [],
              "keyword": "린넨", "category": "상의_전체"}],
            {"temp_max": 31, "weather_label": "맑음"},
            [],
            [],
            3,
            backtest_stats,
        )
        signal_action = next(a for a in actions if a["source"] == "기획전 시그널")
        self.assertIn("백테스트", signal_action["priority_reason"])

    def test_duplicate_source_signals_dedup_strictly(self):
        """동일 source("기획전 시그널")의 후보가 limit보다 많아도, 채움(fallback)
        루프에서 중복 source가 다시 추가되는 회귀가 없어야 한다(이전 라운드 버그)."""
        signals = [
            {"theme": f"{kw} 기획전", "score": score, "trend_pct": 40, "issues": [],
             "keyword": kw, "category": "상의_전체"}
            for kw, score in (("A", 90), ("B", 85), ("C", 80))
        ]
        actions = md_actions.build(signals, {"temp_max": 20, "weather_label": "맑음"}, [], [], limit=3)
        sources = [a["source"] for a in actions]
        self.assertEqual(1, len(actions))  # 고유 source가 1개뿐이므로 1개만 반환되어야 함.
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual("A 기획전", actions[0]["title"])  # 가장 높은 점수만 채택.


class SignalBacktestDropoutTest(unittest.TestCase):
    """후속일에 랭킹 이탈한 추천 상품을 카테고리 평균으로 허위 대체하지 않는지 검증."""

    def test_delisted_product_is_held_not_falsely_partial_hit(self):
        signals = {
            "2026-06-01": [{
                "keyword": "린넨", "theme": "린넨 기획전", "score": 80,
                "product_name": "", "category": "상의_전체",
            }]
        }
        rankings = {
            "2026-06-01": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 10},
                {"period": "1일", "category": "상의_전체", "product_name": "기타1", "rank": 5},
                {"period": "1일", "category": "상의_전체", "product_name": "기타2", "rank": 15},
            ],
            # 7일 후 "린넨 셔츠"는 완전히 랭킹에서 이탈(품절/탈락) — 카테고리에는
            # 다른 상품만 남아있다. 이를 카테고리 평균으로 대체하면 허위로
            # "부분 적중"처럼 보일 수 있으므로 '보류'로 처리되어야 한다.
            "2026-06-08": [
                {"period": "1일", "category": "상의_전체", "product_name": "기타1", "rank": 3},
                {"period": "1일", "category": "상의_전체", "product_name": "기타2", "rank": 8},
            ],
        }
        result = signal_backtest.evaluate(signals, rankings, date(2026, 6, 10))
        row = result[0]
        self.assertIsNone(row["day7_change"])
        self.assertEqual("보류", row["status"])
        self.assertTrue(row.get("day7_change_dropout"))

    def test_market_baseline_accounts_for_dropout_with_rank_floor(self):
        """시장 코호트 중 일부가 후속일에 랭킹 밖으로 이탈하면, 생존자만으로 평균을
        내지 않고 이탈 상품을 순위 하한값(N+1위)으로 포함해야 한다."""
        signals = {
            "2026-06-01": [{
                "keyword": "린넨", "theme": "린넨 기획전", "score": 80,
                "product_name": "린넨 셔츠", "category": "상의_전체",
            }]
        }
        rankings = {
            "2026-06-01": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 10},
                {"period": "1일", "category": "상의_전체", "product_name": "기타1", "rank": 5},
                {"period": "1일", "category": "상의_전체", "product_name": "기타2", "rank": 6},
            ],
            "2026-06-08": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 4},
                {"period": "1일", "category": "상의_전체", "product_name": "기타1", "rank": 1},
                # "기타2"는 7일 후 완전히 랭킹에서 사라짐(이탈) — 생존자만 보면
                # 시장 성과가 좋게(기타1만 +4계단) 보이지만, 이탈을 N+1위로 보면
                # 평균은 더 낮아져야 한다(생존자 편향 방지).
            ],
        }
        result = signal_backtest.evaluate(signals, rankings, date(2026, 6, 10))
        row = result[0]
        # 코호트는 기타1(rank 5->1, +4)과 기타2(rank 6->31, -25)이며 평균은 음수여야 한다.
        # 생존자 편향이 있었다면(기타2 제외) market_day7_change는 +4.0이 된다.
        self.assertIsNotNone(row["market_day7_change"])
        self.assertLess(row["market_day7_change"], 0)


class TimingSignalWeatherConflictConsistencyTest(unittest.TestCase):
    """weather_conflict 필드가 신규 점진적 계절 보정 결과와 모순되지 않는지 검증."""

    def test_weather_conflict_true_when_seasonal_adjustment_negative(self):
        trend_data = [{"keyword": "#후드", "change_pct": 60}]
        rank_result = {
            "items": [{"product_name": "후드 집업", "category": "상의_전체",
                       "rank": 3, "rank_change": 8, "discount_rate": 0}],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        # 25도는 _weather_conflict()(기존 on/off, 28도 기준)에서는 False지만
        # seasonal_adjustment는 음수(역행 페널티)가 적용된다 — weather_conflict
        # 필드는 반드시 True여야 한다(과거 버전에서는 False로 모순되었음).
        signals = timing_signal.detect(trend_data, rank_result, None, {"temp_max": 25})
        signal = signals[0]
        self.assertLess(signal["seasonal_adjustment"], 0)
        self.assertTrue(signal["weather_conflict"])

    def test_seasonal_penalty_continuous_at_threshold(self):
        """23.9도→0점, 24.0도→큰 음수로 점프하는 불연속이 없어야 한다."""
        trend_data = [{"keyword": "#패딩", "change_pct": 60}]
        rank_result = {
            "items": [{"product_name": "패딩 자켓", "category": "아우터_전체",
                       "rank": 3, "rank_change": 8, "discount_rate": 0}],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        just_below = timing_signal.detect(trend_data, rank_result, None, {"temp_max": 23.9})
        at_threshold = timing_signal.detect(trend_data, rank_result, None, {"temp_max": 24.0})
        # 임계값 부근에서 점수 차이가 5점 이내(연속적)여야 한다 — 과거에는 5.8점 이상 급락했었다.
        self.assertLessEqual(
            abs(just_below[0]["score"] - at_threshold[0]["score"]), 2
        )
        self.assertAlmostEqual(at_threshold[0]["seasonal_adjustment"], 0.0, delta=0.5)


class SignalBacktestCategoryIsolationTest(unittest.TestCase):
    """_matching()이 카테고리를 무시하고 다른 카테고리 상품까지 합산하지 않는지 검증."""

    def test_matching_does_not_leak_into_other_category(self):
        signals = {
            "2026-06-01": [{
                "keyword": "린넨", "theme": "린넨 상의 기획전", "score": 80,
                "product_name": "", "category": "상의_전체",
            }]
        }
        rankings = {
            "2026-06-01": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 10},
                # 동일 키워드("린넨")를 포함하지만 다른 카테고리(바지)의 상품 —
                # 카테고리 필터가 없으면 이 상품의 변동까지 평균에 섞여 들어간다.
                {"period": "1일", "category": "바지_전체", "product_name": "린넨 팬츠", "rank": 20},
            ],
            "2026-06-08": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 9},
                # 바지 카테고리의 "린넨 팬츠"는 크게 상승(20 -> 2, +18) — 카테고리
                # 필터가 없으면 상의 시그널의 day7_change가 이 상승분까지 포함해
                # 부풀려진다.
                {"period": "1일", "category": "바지_전체", "product_name": "린넨 팬츠", "rank": 2},
            ],
        }
        result = signal_backtest.evaluate(signals, rankings, date(2026, 6, 10))
        row = result[0]
        # 카테고리 필터가 정상 동작하면 상의 카테고리의 "린넨 셔츠"만 매칭되어
        # day7_change는 +1.0이어야 한다(바지 카테고리의 +18 상승이 섞이지 않음).
        self.assertEqual(1.0, row["day7_change"])


class SignalBacktestSiblingLeakageTest(unittest.TestCase):
    """같은 날 발생한 형제 시그널의 상품이 시장 베이스라인에 누수되지 않는지 검증."""

    def test_sibling_signal_product_excluded_from_market_baseline(self):
        signals = {
            "2026-06-01": [
                {"keyword": "린넨 셔츠", "theme": "린넨 기획전", "score": 80,
                 "product_name": "", "category": "상의_전체"},
                {"keyword": "데님 팬츠", "theme": "데님 기획전", "score": 75,
                 "product_name": "", "category": "상의_전체"},
            ]
        }
        rankings = {
            "2026-06-01": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 10},
                {"period": "1일", "category": "상의_전체", "product_name": "데님 팬츠", "rank": 12},
                {"period": "1일", "category": "상의_전체", "product_name": "기타", "rank": 5},
            ],
            "2026-06-08": [
                {"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 4},
                {"period": "1일", "category": "상의_전체", "product_name": "데님 팬츠", "rank": 6},
                # "기타"는 7일 후에도 그대로 5위 고정 — 코호트에 형제 시그널 상품이
                # 누수되지 않는다면 시장 베이스라인은 0.0(기타만 남음)이어야 한다.
                {"period": "1일", "category": "상의_전체", "product_name": "기타", "rank": 5},
            ],
        }
        result = signal_backtest.evaluate(signals, rankings, date(2026, 6, 10))
        for row in result:
            # 두 시그널 모두 market_day7_change는 0.0이어야 한다(서로의 +6 상승이
            # 형제 시그널의 베이스라인에 섞여 들어가면 market7=3.0처럼 잘못 계산된다).
            self.assertEqual(0.0, row["market_day7_change"])
            self.assertEqual(row["day7_change"], row["relative_day7_change"])


class SignalBacktestDropoutCountedAsFailureTest(unittest.TestCase):
    """랭킹 이탈이 적중률 통계(aggregate_stats/keyword_hit_weights)에서
    분모 제외("보류")가 아니라 실패로 집계되는지 검증."""

    def test_dropout_lowers_hit_rate_in_aggregate_stats(self):
        results = [
            {"category": "상의_전체", "score": 60, "status": "적중", "relative_status": "적중",
             "day7_change_dropout": False},
            {"category": "상의_전체", "score": 60, "status": "적중", "relative_status": "적중",
             "day7_change_dropout": False},
            # 이탈 — status는 "보류"이지만 day7_change_dropout=True.
            {"category": "상의_전체", "score": 60, "status": "보류", "relative_status": "보류",
             "day7_change_dropout": True},
        ]
        stats = signal_backtest.aggregate_stats(results)
        cat_stats = stats["by_category"]["상의_전체"]
        # 이탈을 제외하면 적중률 100%(2/2)가 되지만, 실패로 포함시키면 2/3 ≈ 66.7%여야 한다.
        self.assertEqual(3, cat_stats["count"])
        self.assertAlmostEqual(66.7, cat_stats["hit_rate"], places=1)
        self.assertEqual(1, cat_stats["dropouts_counted_as_fail"])

    def test_keyword_hit_weights_penalizes_dropout(self):
        results = [
            {"keyword": "후드", "category": "상의_전체", "score": 60,
             "relative_status": "보류", "day7_change_dropout": True},
            {"keyword": "후드", "category": "상의_전체", "score": 60,
             "relative_status": "보류", "day7_change_dropout": True},
        ]
        weights = signal_backtest.keyword_hit_weights(results, min_samples=2)
        # 이탈 2건이 모두 실패로 집계되면 적중률 0% -> 최대 음의 가중치(-10.0)가 나와야 한다.
        self.assertEqual(-10.0, weights.get("후드"))


class TimingSignalScoreRangeNamingTest(unittest.TestCase):
    """score_range가 confidence_band의 신규 별칭으로 동일 값을 가리키는지 검증."""

    def test_score_range_present_and_matches_confidence_band_alias(self):
        trend_data = [{"keyword": "#린넨", "change_pct": 45}]
        rank_result = {
            "items": [{"product_name": "린넨 셔츠", "category": "상의_전체",
                       "rank": 3, "rank_change": 8, "discount_rate": 0}],
            "new_entries": [], "top_risers": [], "top_fallers": [],
        }
        signals = timing_signal.detect(trend_data, rank_result)
        signal = signals[0]
        self.assertIn("score_range", signal)
        self.assertIn("confidence_band", signal)
        self.assertEqual(signal["score_range"], signal["confidence_band"])
        self.assertIn("low", signal["score_range"])
        self.assertIn("high", signal["score_range"])


class DashboardScoreBreakdownRenderingTest(unittest.TestCase):
    """대시보드가 score_breakdown을 실제로 렌더링하는지 검증(문서/MD액션과의 불일치 방지)."""

    def test_signal_cards_render_score_breakdown_entries(self):
        from exporters import dashboard
        signal = {
            "keyword": "린넨", "trend_pct": 45, "rank_change": 8,
            "is_new_entry": False, "theme": "린넨 기획전", "score": 70,
            "level": "🟡 주의", "issues": [], "brand": "테스트브랜드",
            "category": "상의_전체",
            "score_breakdown": {"trend": 20, "rank": 15, "seasonal_adjustment": -3.0},
            "score_range": {"low": 60, "high": 80},
            "evidence_detail": [], "next_checks": [],
        }
        html = dashboard._signal_cards([signal])
        self.assertIn("score_breakdown", html)
        self.assertIn("트렌드", html)
        self.assertIn("-3", html)

    def test_signal_cards_safe_without_new_fields(self):
        from exporters import dashboard
        signal = {
            "keyword": "린넨", "trend_pct": 45, "rank_change": 8,
            "is_new_entry": False, "theme": "린넨 기획전", "score": 70,
            "level": "🟡 주의", "issues": [], "brand": "", "category": "",
        }
        html = dashboard._signal_cards([signal])
        self.assertIsInstance(html, str)


if __name__ == "__main__":
    unittest.main()
