import unittest

from app.redteam import ALL_SCENARIOS, run_all


class TestRedTeamSuite(unittest.TestCase):
    def test_seventeen_scenarios_present(self):
        self.assertEqual(len(ALL_SCENARIOS), 17)

    def test_all_scenarios_blocked(self):
        results = run_all()
        for r in results:
            with self.subTest(scenario=r["name"]):
                self.assertTrue(r["blocked"], f"{r['name']} was NOT blocked: {r}")

    def test_reproducible(self):
        self.assertEqual(run_all(), run_all())


if __name__ == "__main__":
    unittest.main()
