import unittest

from techmedic.safety import assess_candidate_tests


class SafetyTests(unittest.TestCase):
    def test_low_risk_test_passes(self):
        state = {
            "candidate_next_tests": [
                {
                    "name": "Check version",
                    "instructions": "Run python --version and report the output.",
                    "purpose": "Confirm installed Python version.",
                }
            ]
        }
        result = assess_candidate_tests(state)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["risk_level"], "low")

    def test_power_supply_instruction_is_blocked(self):
        state = {
            "candidate_next_tests": [
                {
                    "name": "Unsafe",
                    "instructions": "Open the power supply and inspect internal components.",
                    "purpose": "Inspect power circuitry.",
                }
            ]
        }
        result = assess_candidate_tests(state)
        self.assertTrue(result["blocked"])
        self.assertEqual(result["risk_level"], "high")

    def test_destructive_action_warns(self):
        state = {
            "candidate_next_tests": [
                {
                    "name": "Disk action",
                    "instructions": "Format the disk.",
                    "purpose": "Reinitialize storage.",
                }
            ]
        }
        result = assess_candidate_tests(state)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["risk_level"], "moderate")
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
