import unittest

from techmedic.status import (
    derive_case_status,
    derive_effective_next_action,
    diagnostic_confidence,
    remediation_confidence,
    resolution_confidence,
)


class EngineStatusTests(unittest.TestCase):
    def _jev(self, diagnosis=0.0, remediation=0.0, resolution=0.0, action="run_diagnostic_test"):
        return {
            "answers": {
                "diagnosis_established": {"type": "noul", "noul": diagnosis},
                "remediation_identified": {"type": "noul", "noul": remediation},
                "resolution_verified": {"type": "noul", "noul": resolution},
                "next_action": {"type": "choice", "choice": action},
            }
        }

    def test_sparse_evidence_forces_investigating(self):
        state = {
            "status": "possible_diagnosis",
            "diagnosis": {"summary": "Maybe package mismatch", "basis": []},
            "remediation": {"summary": "", "requirements": []},
            "resolution_verification": {"verified": False, "evidence": []},
        }
        self.assertEqual(derive_case_status(state, self._jev(diagnosis=0.08)), "investigating")

    def test_escalation_action_does_not_replace_investigating_lifecycle(self):
        state = {"status": "investigating"}
        jev = self._jev(diagnosis=0.10, action="escalate")
        self.assertEqual(derive_case_status(state, jev), "investigating")
        self.assertEqual(derive_effective_next_action(state, jev, "investigating"), "escalate")

    def test_escalation_action_preserves_established_diagnosis_lifecycle(self):
        state = {
            "status": "diagnosis_established",
            "diagnosis": {
                "summary": "Intermittent TV backlight or illumination-path failure",
                "basis": [
                    "A faint moving image is visible with a flashlight during the dark-screen fault.",
                    "Audio and controls continue while the TV's own visible interface disappears.",
                ],
            },
            "remediation": {
                "summary": "Arrange qualified television service",
                "requirements": ["Exact failed component is not identified"],
            },
            "resolution_verification": {"verified": False, "evidence": []},
        }
        jev = self._jev(diagnosis=0.92, remediation=0.37, action="escalate")
        self.assertEqual(derive_case_status(state, jev), "diagnosis_established")
        self.assertEqual(derive_effective_next_action(state, jev, "diagnosis_established"), "escalate")

    def test_early_coherent_leading_cause_is_possible_diagnosis(self):
        # Mirrors the DNS regression turn where root-cause-established was only
        # 0.21 but the evidence already supported a coherent leading cause.
        state = {
            "status": "investigating",
            "diagnosis": {
                "summary": "DNS resolution through 192.168.1.1 is failing",
                "basis": ["default nslookup timed out"],
            },
        }
        self.assertEqual(derive_case_status(state, self._jev(diagnosis=0.21)), "possible_diagnosis")

    def test_moderate_diagnostic_confidence_is_possible_diagnosis(self):
        state = {
            "status": "possible_diagnosis",
            "diagnosis": {"summary": "Environment mismatch is leading", "basis": ["test"]},
        }
        self.assertEqual(derive_case_status(state, self._jev(diagnosis=0.70)), "possible_diagnosis")

    def test_strong_diagnosis_does_not_require_remediation(self):
        state = {
            "status": "diagnosis_established",
            "diagnosis": {"summary": "Installed PyTorch build is CPU-only", "basis": ["+cpu suffix"]},
            "remediation": {"summary": "", "requirements": ["Verify compatible GPU build"]},
        }
        self.assertEqual(
            derive_case_status(state, self._jev(diagnosis=0.92, remediation=0.35, action="verify_compatibility")),
            "diagnosis_established",
        )

    def test_supported_fix_advances_to_remediation_identified(self):
        state = {
            "diagnosis": {"summary": "DNS resolver is failing", "basis": ["IP ping works"]},
            "remediation": {"summary": "Use a verified working DNS resolver", "requirements": []},
            "resolution_verification": {"verified": False, "evidence": []},
        }
        self.assertEqual(
            derive_case_status(state, self._jev(diagnosis=0.93, remediation=0.82, action="verify_resolution")),
            "remediation_identified",
        )

    def test_lifecycle_does_not_regress_after_remediation_is_identified(self):
        # Reproduces the v1.4 DNS bug: after the user applied the DNS change,
        # Jev dropped just below the diagnosis threshold and the case moved
        # backwards to Possible Diagnosis.
        state = {
            "status": "possible_diagnosis",
            "diagnosis": {"summary": "Prior DNS path was failing", "basis": ["evidence"]},
            "remediation": {"summary": "DNS changed to 1.1.1.1", "requirements": ["verify"]},
            "resolution_verification": {"verified": False, "evidence": []},
            "lifecycle_control": {"reopen": False, "reason": ""},
        }
        self.assertEqual(
            derive_case_status(
                state,
                self._jev(diagnosis=0.80, remediation=0.82, resolution=0.03, action="verify_resolution"),
                previous_status="remediation_identified",
            ),
            "remediation_identified",
        )

    def test_explicit_contradictory_evidence_can_reopen_case(self):
        state = {
            "status": "investigating",
            "diagnosis": {"summary": "Old diagnosis contradicted", "basis": []},
            "remediation": {"summary": "", "requirements": []},
            "resolution_verification": {"verified": False, "evidence": []},
            "lifecycle_control": {
                "reopen": True,
                "reason": "New test directly contradicts the previous diagnosis.",
            },
        }
        self.assertEqual(
            derive_case_status(
                state,
                self._jev(diagnosis=0.08),
                previous_status="remediation_identified",
            ),
            "investigating",
        )

    def test_resolution_requires_post_fix_verification(self):
        state = {
            "diagnosis": {"summary": "DNS resolver failed", "basis": ["evidence"]},
            "remediation": {"summary": "DNS corrected", "requirements": []},
            "resolution_verification": {"verified": True, "evidence": ["websites now load"]},
        }
        self.assertEqual(
            derive_case_status(state, self._jev(diagnosis=0.98, remediation=0.95, resolution=0.91, action="finish_diagnosis")),
            "resolution_verified",
        )

    def test_attempted_fix_without_verified_result_is_not_resolution_verified(self):
        state = {
            "diagnosis": {"summary": "Cause", "basis": ["evidence"]},
            "remediation": {"summary": "Fix applied", "requirements": []},
            "resolution_verification": {"verified": False, "evidence": ["fix installed"]},
        }
        self.assertEqual(
            derive_case_status(state, self._jev(diagnosis=0.98, remediation=0.95, resolution=0.90, action="verify_resolution")),
            "remediation_identified",
        )

    def test_resolution_verified_forces_finish_diagnosis_action(self):
        state = {
            "resolution_verification": {"verified": True, "evidence": ["websites now load"]},
        }
        jev = self._jev(diagnosis=0.92, remediation=0.87, resolution=0.95, action="ask_for_information")
        self.assertEqual(derive_effective_next_action(state, jev, "resolution_verified"), "finish_diagnosis")
        # The raw Jev value remains available for Developer Trace/auditing.
        self.assertEqual(jev["answers"]["next_action"]["choice"], "ask_for_information")

    def test_non_terminal_action_is_not_overridden(self):
        state = {"resolution_verification": {"verified": False, "evidence": []}}
        jev = self._jev(diagnosis=0.87, remediation=0.89, resolution=0.03, action="run_diagnostic_test")
        self.assertEqual(derive_effective_next_action(state, jev, "remediation_identified"), "run_diagnostic_test")

    def test_confidence_helpers_use_v14_questions(self):
        jev = self._jev(diagnosis=0.88, remediation=0.66, resolution=0.22)
        self.assertEqual(diagnostic_confidence(jev), 0.88)
        self.assertEqual(remediation_confidence(jev), 0.66)
        self.assertEqual(resolution_confidence(jev), 0.22)

    def test_diagnostic_confidence_falls_back_to_v13_evidence(self):
        jev = {"answers": {"evidence_sufficient": {"type": "noul", "noul": 0.73}}}
        self.assertEqual(diagnostic_confidence(jev), 0.73)

    def test_dns_multi_device_semantic_consensus_establishes_diagnosis(self):
        # Reproduces the v1.4.1 calibration failure: two devices time out through
        # the configured resolver while direct queries to 8.8.8.8 succeed. The
        # failing DNS path is a sufficient diagnosis even though the deeper
        # router/upstream mechanism is unknown.
        state = {
            "status": "diagnosis_established",
            "diagnosis": {
                "summary": "DNS resolution through 192.168.1.1 is failing across multiple devices.",
                "basis": [
                    "Default lookups through 192.168.1.1 timed out on both devices.",
                    "Direct lookups through 8.8.8.8 succeeded on both devices.",
                    "Both devices experienced website-loading failures.",
                ],
            },
            "remediation": {"summary": "", "requirements": ["Select a corrective DNS path"]},
            "resolution_verification": {"verified": False, "evidence": []},
            "lifecycle_control": {"reopen": False, "reason": ""},
        }
        self.assertEqual(
            derive_case_status(state, self._jev(diagnosis=0.36, remediation=0.15)),
            "diagnosis_established",
        )

    def test_possible_diagnosis_is_not_promoted_by_probability_floor_alone(self):
        state = {
            "status": "possible_diagnosis",
            "diagnosis": {
                "summary": "DNS path may be failing",
                "basis": ["one clue", "second clue"],
            },
        }
        self.assertEqual(
            derive_case_status(state, self._jev(diagnosis=0.36)),
            "possible_diagnosis",
        )

    def test_semantic_consensus_requires_multiple_basis_items(self):
        state = {
            "status": "diagnosis_established",
            "diagnosis": {
                "summary": "Cause asserted too early",
                "basis": ["only one supporting observation"],
            },
        }
        self.assertEqual(
            derive_case_status(state, self._jev(diagnosis=0.36)),
            "possible_diagnosis",
        )

    def test_semantic_consensus_can_support_remediation_milestone(self):
        state = {
            "status": "remediation_identified",
            "diagnosis": {
                "summary": "Configured DNS resolver path is failing",
                "basis": ["default resolver fails", "alternate resolver succeeds"],
            },
            "remediation": {
                "summary": "Use an approved responsive resolver or restore router DNS forwarding",
                "requirements": [],
            },
            "resolution_verification": {"verified": False, "evidence": []},
        }
        self.assertEqual(
            derive_case_status(state, self._jev(diagnosis=0.40, remediation=0.82)),
            "remediation_identified",
        )

    def test_escalated_service_case_can_later_be_resolution_verified(self):
        state = {
            "status": "resolution_verified",
            "diagnosis": {
                "summary": "TV illumination path failed",
                "basis": ["flashlight test showed image content", "TV menus were not visible"],
            },
            "remediation": {
                "summary": "Qualified service repaired the illumination path",
                "requirements": [],
            },
            "resolution_verification": {
                "verified": True,
                "evidence": ["TV picture remains normal after repair during the previously failing use case"],
            },
        }
        jev = self._jev(diagnosis=0.95, remediation=0.90, resolution=0.93, action="finish_diagnosis")
        self.assertEqual(
            derive_case_status(state, jev, previous_status="diagnosis_established"),
            "resolution_verified",
        )
        self.assertEqual(derive_effective_next_action(state, jev, "resolution_verified"), "finish_diagnosis")


if __name__ == "__main__":
    unittest.main()
