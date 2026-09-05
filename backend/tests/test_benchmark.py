import unittest

from app.benchmark import run_benchmark


class TestBenchmark(unittest.TestCase):
    def test_reproducible_with_same_seed(self):
        a = run_benchmark(100, seed=42)
        b = run_benchmark(100, seed=42)
        self.assertEqual(a, b)

    def test_different_seed_can_differ(self):
        a = run_benchmark(100, seed=42)
        b = run_benchmark(100, seed=7)
        self.assertNotEqual(a, b)

    def test_econex_has_zero_policy_violations(self):
        result = run_benchmark(200, seed=42)
        self.assertEqual(result["econex"]["policy_violations"], 0)

    def test_econex_beats_baseline_a_on_contribution(self):
        """Doc section 17: must demonstrate a meaningful advantage, not fabricate one."""
        result = run_benchmark(300, seed=42)
        self.assertGreater(
            result["econex"]["contribution_paise"], result["baseline_a"]["contribution_paise"]
        )

    def test_econex_beats_baseline_b_on_contribution_per_incentive_rupee(self):
        result = run_benchmark(300, seed=42)
        self.assertGreater(
            result["econex"]["contribution_per_incentive_rupee"],
            result["baseline_b"]["contribution_per_incentive_rupee"],
        )

    def test_baseline_b_has_policy_violations_by_design(self):
        """Confirms Baseline B is genuinely naive (doc: 'naive aggressive incentive strategy'),
        not secretly policy-safe, which would make the Econex comparison meaningless."""
        result = run_benchmark(300, seed=42)
        self.assertGreater(result["baseline_b"]["policy_violations"], 0)

    def test_baseline_c_present_and_plausible(self):
        """doc upgrade section 16: Baseline C must be a plausible simple rule,
        not deliberately stupid — it should convert some fraction of the time
        and mostly respect policy (unlike Baseline B)."""
        result = run_benchmark(300, seed=42)
        self.assertIn("baseline_c", result)
        self.assertGreater(result["baseline_c"]["conversion_rate"], 0.0)

    def test_econex_beats_baseline_c_on_contribution(self):
        result = run_benchmark(300, seed=42)
        self.assertGreater(
            result["econex"]["contribution_paise"], result["baseline_c"]["contribution_paise"]
        )

    def test_econex_vs_best_baseline_summary_computed_dynamically(self):
        result = run_benchmark(300, seed=42)
        summary = result["econex_vs_best_baseline"]
        self.assertIn(summary["best_baseline"], ("baseline_a", "baseline_b", "baseline_c"))
        self.assertGreater(summary["contribution_pct_improvement"], 0)

    def test_seed_is_42_by_default(self):
        from app.benchmark import SEED

        self.assertEqual(SEED, 42)


if __name__ == "__main__":
    unittest.main()
