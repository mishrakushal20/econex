import unittest

from app.core.money import clamp_paise, paise_to_rupees_str, require_paise, to_paise


class TestMoney(unittest.TestCase):
    def test_to_paise_basic(self):
        self.assertEqual(to_paise(72.0), 7200)
        self.assertEqual(to_paise(72.5), 7250)

    def test_require_paise_rejects_float(self):
        with self.assertRaises(TypeError):
            require_paise(72.0)

    def test_require_paise_rejects_bool(self):
        with self.assertRaises(TypeError):
            require_paise(True)

    def test_require_paise_accepts_int(self):
        self.assertEqual(require_paise(7200), 7200)

    def test_paise_to_rupees_str(self):
        self.assertEqual(paise_to_rupees_str(720000), "\u20b97,200.00")
        self.assertEqual(paise_to_rupees_str(-50), "-\u20b90.50")

    def test_clamp_paise(self):
        self.assertEqual(clamp_paise(100, 0, 50), 50)
        self.assertEqual(clamp_paise(-10, 0, 50), 0)
        self.assertEqual(clamp_paise(20, 0, 50), 20)


if __name__ == "__main__":
    unittest.main()
