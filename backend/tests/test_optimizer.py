import unittest

from app.core.domain import EconomicEvaluation, Candidate, DeliveryOption
from app.core.optimizer import select_best, rank_all


def _cand(cid, price):
    return Candidate(cid, price, 0, 0, 1, DeliveryOption.STANDARD)


def _eval(cid, feasible, eov, contribution=1000):
    return EconomicEvaluation(cid, feasible, 0.5 if feasible else None, contribution, 0, eov)


class TestOptimizer(unittest.TestCase):
    def test_selects_highest_eov_among_feasible(self):
        candidates = (_cand("A", 100), _cand("B", 200), _cand("C", 300))
        evaluations = (
            _eval("A", True, 50.0),
            _eval("B", True, 90.0),
            _eval("C", False, 999.0),  # fabricated high EOV but infeasible
        )
        winner = select_best(candidates, evaluations)
        self.assertIsNotNone(winner)
        self.assertEqual(winner[0].candidate_id, "B")

    def test_infeasible_high_eov_never_wins(self):
        candidates = (_cand("A", 100), _cand("B", 200))
        evaluations = (_eval("A", False, 10_000_000.0), _eval("B", True, 1.0))
        winner = select_best(candidates, evaluations)
        self.assertEqual(winner[0].candidate_id, "B")

    def test_none_when_no_feasible(self):
        candidates = (_cand("A", 100),)
        evaluations = (_eval("A", False, 5.0),)
        self.assertIsNone(select_best(candidates, evaluations))

    def test_tie_break_by_contribution_then_price_then_id(self):
        candidates = (_cand("Z", 300), _cand("A", 100), _cand("M", 200))
        evaluations = (
            _eval("Z", True, 10.0, contribution=500),
            _eval("A", True, 10.0, contribution=500),
            _eval("M", True, 10.0, contribution=500),
        )
        winner = select_best(candidates, evaluations)
        # same EOV, same contribution -> lowest final price wins -> A(100)
        self.assertEqual(winner[0].candidate_id, "A")

    def test_rank_all_puts_infeasible_last(self):
        candidates = (_cand("A", 100), _cand("B", 200))
        evaluations = (_eval("A", False, 999.0), _eval("B", True, 1.0))
        ranked = rank_all(candidates, evaluations)
        self.assertEqual(ranked[0][0].candidate_id, "B")
        self.assertEqual(ranked[1][0].candidate_id, "A")

    def test_deterministic_reproducible(self):
        candidates = (_cand("A", 100), _cand("B", 200))
        evaluations = (_eval("A", True, 10.0), _eval("B", True, 10.0))
        self.assertEqual(select_best(candidates, evaluations), select_best(candidates, evaluations))


if __name__ == "__main__":
    unittest.main()
