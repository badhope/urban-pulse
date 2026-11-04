import unittest
from unittest.mock import patch

from rules.checks import level_for, resolve_check


class ChecksRegressionTests(unittest.TestCase):
    def test_level_below_lowest_band_and_natural_adjustment(self):
        self.assertEqual(level_for(-1000)["key"], "failure")
        self.assertEqual(level_for(-1000, natural_max=True)["key"], "partial")
        bands = [{"min": 4, "key": "high"}, {"min": -2, "key": "low"}]
        self.assertEqual(level_for(-9999, bands)["key"], "low")
        self.assertEqual(level_for(-2, bands)["key"], "low")

    def test_pool_threshold_is_not_a_numeric_modifier(self):
        state = {"entities": {"a": {"attrs": {"skill": 1}}}}
        modifiers = [{"label": "success_on", "value": 4}, {"label": "bonus", "value": 2}]
        with patch("rules.checks.random.randint", side_effect=[3, 4, 5]):
            result = resolve_check(state, "a", "skill", 4, "pool", "pool", modifiers, pool_size=3)
        self.assertEqual(result["rolls"], [3, 4, 5])
        self.assertEqual(result["modifiers"], modifiers)
        self.assertEqual(result["mod_total"], 2)
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["margin"], 1)
        self.assertEqual(state["checks"], [result])

    def test_opposed_pool_uses_same_clamped_threshold(self):
        state = {"entities": {"a": {"attrs": {"skill": 1}}, "b": {"attrs": {"skill": 2}}}}
        with patch("rules.checks.random.randint", side_effect=[2, 3, 4, 2, 3, 4]):
            result = resolve_check(state, "a", "skill", dice="pool", mode="pool",
                                   modifiers=[{"label": "success_on", "value": 1}],
                                   opposed_by="b", pool_size=3, record=False)
        self.assertEqual(result["opposed"]["total"], 5)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["margin"], -1)
        self.assertEqual(result["level"], "partial")
        self.assertNotIn("checks", state)

    def test_non_pool_modifier_label_remains_numeric(self):
        with patch("rules.checks.random.randint", return_value=10):
            result = resolve_check({}, "", dice="d20", modifiers=[{"label": "success_on", "value": 4}], record=False)
        self.assertEqual(result["mod_total"], 4)
        self.assertEqual(result["total"], 14)


if __name__ == "__main__":
    unittest.main()
