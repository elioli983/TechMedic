import unittest

from techmedic.models import normalize_diagnostic_state


class ModelNormalizationTests(unittest.TestCase):
    def test_missing_fields_are_filled(self):
        state = normalize_diagnostic_state({"case_summary": "Example"})
        self.assertEqual(state["case_summary"], "Example")
        self.assertEqual(state["status"], "investigating")
        self.assertEqual(state["candidate_next_tests"], [])
        self.assertEqual(state["diagnosis"], {"summary": "", "basis": []})
        self.assertEqual(state["remediation"], {
            "summary": "", "requirements": [], "selection_ready": None, "blocking_requirements": [],
            "install_command": "", "verification_commands": [], "confidence_note": ""
        })
        self.assertEqual(state["resolution_verification"], {"verified": False, "evidence": []})
        self.assertEqual(state["lifecycle_control"], {"reopen": False, "reason": ""})
        self.assertEqual(state["research_request"], {"needed": False, "category": "", "query": "", "reason": ""})
        self.assertEqual(state["research_evidence"], {"summary": "", "source_ids": [], "category": "", "query": ""})

    def test_invalid_status_falls_back(self):
        state = normalize_diagnostic_state({"status": "certainly_fixed"})
        self.assertEqual(state["status"], "investigating")

    def test_v13_diagnosed_status_maps_to_diagnosis_established(self):
        state = normalize_diagnostic_state({"status": "diagnosed"})
        self.assertEqual(state["status"], "diagnosis_established")

    def test_escalate_is_not_a_lifecycle_status(self):
        state = normalize_diagnostic_state({"status": "escalate"})
        self.assertEqual(state["status"], "investigating")

    def test_candidate_tests_are_limited_to_three(self):
        tests = [
            {"name": str(i), "instructions": "x", "purpose": "x", "risk": "low"}
            for i in range(5)
        ]
        state = normalize_diagnostic_state({"candidate_next_tests": tests})
        self.assertEqual(len(state["candidate_next_tests"]), 3)

    def test_resolution_verified_string_is_normalized_to_bool(self):
        state = normalize_diagnostic_state({"resolution_verification": {"verified": "true", "evidence": ["works"]}})
        self.assertIs(state["resolution_verification"]["verified"], True)

    def test_lifecycle_reopen_is_normalized(self):
        state = normalize_diagnostic_state({"lifecycle_control": {"reopen": "true", "reason": "contradiction"}})
        self.assertIs(state["lifecycle_control"]["reopen"], True)
        self.assertEqual(state["lifecycle_control"]["reason"], "contradiction")


    def test_research_request_is_normalized(self):
        state = normalize_diagnostic_state({
            "research_request": {
                "needed": "true",
                "category": "compatibility",
                "query": "PyTorch Python compatibility",
                "reason": "current support matrix",
            },
            "research_evidence": {
                "summary": "Official docs checked",
                "source_ids": ["R1", "R2"],
                "category": "documentation",
                "query": "docs",
            },
        })
        self.assertTrue(state["research_request"]["needed"])
        self.assertEqual(state["research_request"]["category"], "compatibility")
        self.assertEqual(state["research_evidence"]["source_ids"], ["R1", "R2"])

    def test_unknown_research_category_becomes_other(self):
        state = normalize_diagnostic_state({"research_request": {"category": "mystery"}})
        self.assertEqual(state["research_request"]["category"], "other")


if __name__ == "__main__":
    unittest.main()
