import os
import tempfile
import unittest
from datetime import date

from analyzers import md_actions, platform_cross, rank_diff, signal_backtest
from exporters import dashboard, snapshot_store


class DashboardIntelligenceTest(unittest.TestCase):
    def test_rank_diff_separates_periods(self):
        previous = [
            {"period": "1일", "category": "상의_전체", "product_name": "A", "rank": 3},
            {"period": "주간", "category": "상의_전체", "product_name": "A", "rank": 8},
        ]
        current = [
            {"period": "1일", "category": "상의_전체", "product_name": "A", "rank": 1},
            {"period": "주간", "category": "상의_전체", "product_name": "A", "rank": 7},
        ]
        result = rank_diff.analyze(current, previous)
        self.assertEqual([2, 1], [item["rank_change"] for item in result["items"]])
        self.assertTrue(result["baseline_available"])

    def test_rank_diff_does_not_mark_first_snapshot_as_new(self):
        current = [
            {"period": "1일", "category": "상의_전체", "product_name": "A", "rank": 1},
        ]
        result = rank_diff.analyze(current, [])
        self.assertFalse(result["baseline_available"])
        self.assertEqual([], result["new_entries"])
        self.assertIn("판정 대기", dashboard._new_entry_cards(
            result["new_entries"], result["baseline_available"]
        ))
        self.assertIn("대기", dashboard._ranking_table(
            result["items"], "상의", baseline_available=False
        ))

    def test_rank_diff_only_marks_periods_with_baseline_as_new(self):
        previous = [
            {"period": "1일", "category": "상의_전체", "product_name": "A", "rank": 1},
        ]
        current = [
            {"period": "1일", "category": "상의_전체", "product_name": "B", "rank": 1},
            {"period": "주간", "category": "상의_전체", "product_name": "C", "rank": 1},
        ]
        result = rank_diff.analyze(current, previous)
        self.assertEqual(["B"], [row["product_name"] for row in result["new_entries"]])
        self.assertFalse(result["items"][1]["comparison_available"])

    def test_new_entries_are_unique_products_across_categories(self):
        previous = [
            {"period": "1일", "category": "상의_전체", "product_name": "A",
             "url": "https://example.com/a", "rank": 1},
        ]
        current = [
            {"period": "1일", "category": "상의_전체", "product_name": "B",
             "url": "https://example.com/b", "rank": 3},
            {"period": "1일", "category": "상의_반소매", "product_name": "B",
             "url": "https://example.com/b", "rank": 1},
        ]
        result = rank_diff.analyze(current, previous)
        self.assertEqual(1, len(result["new_entries"]))
        self.assertEqual(1, result["new_entries"][0]["rank"])

    def test_cm29_index_includes_rank_change(self):
        encoded = dashboard._cm29_index([{
            "period": "실시간", "category": "남성_전체", "rank": 1,
            "rank_change": 2, "comparison_available": True,
        }])
        self.assertIn('"rank_change": 2', encoded)
        self.assertIn('"comparison_available": true', encoded)

    def test_snapshot_round_trip_and_previous_lookup(self):
        original = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                snapshot_store.save("rankings", [{"rank": 1}], "2026-06-10")
                snapshot_store.save("rankings", [{"rank": 2}], "2026-06-12")
                snapshot_store.save("rankings", [{"rank": 3}], "2026-06-13")
                self.assertEqual(
                    [{"rank": 1}],
                    snapshot_store.load_latest_before("rankings", "2026-06-11"),
                )
                self.assertEqual(
                    [{"rank": 3}],
                    snapshot_store.load_latest_before("rankings", "2026-06-15"),
                )
                self.assertEqual(
                    [{"rank": 2}],
                    snapshot_store.load_latest_before(
                        "rankings", "2026-06-15", weekdays_only=True
                    ),
                )
                self.assertEqual(
                    ["2026-06-10", "2026-06-12", "2026-06-13"],
                    snapshot_store.available_dates("rankings"),
                )
            finally:
                os.chdir(original)

    def test_cross_platform_brand_detection(self):
        # 같은 대분류 카테고리(상의)에서 동시에 반응해야 교차로 잡힌다 — 카테고리가
        # 다르면(예: 아우터 vs 바지) 브랜드만 같다는 이유로 잘못 묶이지 않는다.
        musinsa = [{"brand": "브랜드A", "rank": 4, "product_name": "셔츠", "category": "상의_전체"}]
        cm29 = [{"brand": "브랜드A", "rank": 7, "product_name": "팬츠", "category": "남성_상의"}]
        result = platform_cross.analyze(musinsa, cm29)
        self.assertEqual("브랜드A", result[0]["brand"])
        self.assertEqual("상의", result[0]["category"])
        self.assertEqual(1, result[0]["musinsa_count"])
        self.assertEqual(1, result[0]["cm29_count"])

    def test_cross_platform_requires_matching_category(self):
        musinsa = [{"brand": "브랜드A", "rank": 4, "product_name": "재킷", "category": "아우터_전체"}]
        cm29 = [{"brand": "브랜드A", "rank": 7, "product_name": "반팔티", "category": "남성_상의"}]
        result = platform_cross.analyze(musinsa, cm29)
        self.assertEqual([], result)

    def test_md_actions_limit_and_priority(self):
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

    def test_backtest_hit(self):
        signals = {
            "2026-06-01": [{
                "keyword": "린넨", "theme": "린넨 기획전", "score": 80,
                "product_name": "", "category": "상의_전체",
            }]
        }
        rankings = {
            "2026-06-01": [{"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 10}],
            "2026-06-04": [{"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 7}],
            "2026-06-08": [{"period": "1일", "category": "상의_전체", "product_name": "린넨 셔츠", "rank": 4}],
        }
        result = signal_backtest.evaluate(signals, rankings, date(2026, 6, 10))
        self.assertEqual("적중", result[0]["status"])
        self.assertEqual(6.0, result[0]["day7_change"])


if __name__ == "__main__":
    unittest.main()
