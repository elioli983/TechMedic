import unittest

from techmedic.prompts import ANALYST_INSTRUCTIONS, RESEARCH_INTEGRATION_INSTRUCTIONS, RESPONDER_INSTRUCTIONS


class PromptTests(unittest.TestCase):
    def test_gpu_prompt_is_cuda_and_rocm_aware(self):
        self.assertIn("ROCm/HIP", ANALYST_INSTRUCTIONS)
        self.assertIn("torch.version.hip", ANALYST_INSTRUCTIONS)
        self.assertIn("torch.cuda.device_count()", ANALYST_INSTRUCTIONS)
        self.assertIn("AMD ROCm/HIP", RESPONDER_INSTRUCTIONS)

    def test_analyst_separates_diagnosis_remediation_and_verification(self):
        self.assertIn("Keep DIAGNOSIS separate from REMEDIATION", ANALYST_INSTRUCTIONS)
        self.assertIn('"diagnosis"', ANALYST_INSTRUCTIONS)
        self.assertIn('"remediation"', ANALYST_INSTRUCTIONS)
        self.assertIn('"resolution_verification"', ANALYST_INSTRUCTIONS)

    def test_responder_knows_v14_lifecycle(self):
        self.assertIn("diagnosis_established", RESPONDER_INSTRUCTIONS)
        self.assertIn("remediation_identified", RESPONDER_INSTRUCTIONS)
        self.assertIn("resolution_verified", RESPONDER_INSTRUCTIONS)

    def test_responder_must_follow_effective_next_action(self):
        self.assertIn("effective_next_action", RESPONDER_INSTRUCTIONS)
        self.assertIn("Do not silently substitute a different action category", RESPONDER_INSTRUCTIONS)
        self.assertIn("finish_diagnosis", RESPONDER_INSTRUCTIONS)

    def test_analyst_defines_established_diagnosis_at_useful_troubleshooting_level(self):
        self.assertIn("Do NOT require the deepest underlying mechanism", ANALYST_INSTRUCTIONS)
        self.assertIn("status=diagnosis_established", ANALYST_INSTRUCTIONS)
        self.assertIn("Do not keep drilling indefinitely", ANALYST_INSTRUCTIONS)

    def test_responder_does_not_downgrade_established_diagnosis_for_unknown_deeper_mechanism(self):
        self.assertIn("useful troubleshooting level", RESPONDER_INSTRUCTIONS)
        self.assertIn("deeper underlying mechanism", RESPONDER_INSTRUCTIONS)

    def test_escalation_is_action_not_lifecycle_status(self):
        self.assertIn("Escalation is NOT a lifecycle state", ANALYST_INSTRUCTIONS)
        self.assertNotIn("resolution_verified|escalate", ANALYST_INSTRUCTIONS)
        self.assertIn("escalation is a workflow action, not a case lifecycle state", RESPONDER_INSTRUCTIONS)

    def test_analyst_has_explicit_reopen_control(self):
        self.assertIn("lifecycle_control.reopen", ANALYST_INSTRUCTIONS)
        self.assertIn('"lifecycle_control"', ANALYST_INSTRUCTIONS)


    def test_v15_analyst_has_controlled_research_gate(self):
        self.assertIn("CONTROLLED WEB/DOCUMENTATION RESEARCH", ANALYST_INSTRUCTIONS)
        self.assertIn("research_request.needed=true", ANALYST_INSTRUCTIONS)
        self.assertIn("Do NOT request web research for ordinary local diagnostics", ANALYST_INSTRUCTIONS)
        self.assertIn('"research_request"', ANALYST_INSTRUCTIONS)
        self.assertIn('"research_evidence"', ANALYST_INSTRUCTIONS)

    def test_research_integration_preserves_external_evidence_provenance(self):
        self.assertIn("Documentation evidence is external evidence", RESEARCH_INTEGRATION_INSTRUCTIONS)
        self.assertIn("Do not let documentation alone prove a local condition", RESEARCH_INTEGRATION_INSTRUCTIONS)
        self.assertIn("research_evidence.source_ids", RESEARCH_INTEGRATION_INSTRUCTIONS)

    def test_responder_requires_research_source_ids(self):
        self.assertIn("Cite web-grounded claims", RESPONDER_INSTRUCTIONS)
        self.assertIn("[R1]", RESPONDER_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
