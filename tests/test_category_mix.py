import unittest

from analyzers import category_mix


class CategoryMixTest(unittest.TestCase):
    def test_compute_category_weight_matches_by_url(self):
        categorized = (
            [{"category": "상의_전체", "url": f"https://m/{i}"} for i in range(20)]
            + [{"category": "아우터_전체", "url": f"https://m/o{i}"} for i in range(10)]
            + [{"category": "바지_전체", "url": f"https://m/p{i}"} for i in range(10)]
        )
        # 통합 베스트에서 상의가 절반(10/20)을 차지 — 평균(20/3≈6.7)보다 비중이 크다.
        overall = (
            [{"url": f"https://m/{i}"} for i in range(10)]
            + [{"url": f"https://m/o{i}"} for i in range(5)]
            + [{"url": f"https://m/p{i}"} for i in range(5)]
        )
        weights, counts = category_mix.compute_category_weight(overall, categorized)
        self.assertEqual({"상의": 10, "아우터": 5, "바지": 5}, counts)
        self.assertGreater(weights["상의"], 1.0)
        self.assertLess(weights["아우터"], 1.0)
        # 모든 가중치는 0.6~1.6 범위 안에 있어야 한다.
        for w in weights.values():
            self.assertGreaterEqual(w, 0.6)
            self.assertLessEqual(w, 1.6)

    def test_insufficient_matches_returns_empty_weights(self):
        categorized = [{"category": "상의_전체", "url": "https://m/1"}]
        overall = [{"url": "https://m/1"}]  # 매칭 1건뿐 — 표본 부족
        weights, counts = category_mix.compute_category_weight(overall, categorized)
        self.assertEqual({}, weights)
        self.assertEqual(1, counts["상의"])

    def test_unmatched_overall_items_are_ignored(self):
        categorized = [{"category": "상의_전체", "url": "https://m/1"}]
        overall = [{"url": "https://unknown/999"}] * 20
        weights, counts = category_mix.compute_category_weight(overall, categorized)
        self.assertEqual({}, weights)
        self.assertEqual(0, sum(counts.values()))


if __name__ == "__main__":
    unittest.main()
