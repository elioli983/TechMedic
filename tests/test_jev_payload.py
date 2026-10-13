import unittest
from unittest.mock import Mock, patch

from techmedic.jev import (
    HOSTED_ENDPOINT,
    OFFICIAL_ENDPOINT,
    JevClient,
    resolve_jev_endpoint,
)


class JevPayloadTests(unittest.TestCase):
    def test_payload_contains_all_question_types(self):
        payload = JevClient.build_payload({"case_summary": "test"}, "jev-latest")
        self.assertEqual(payload["model"], "jev-latest")
        types = {q["type"] for q in payload["questions"].values()}
        self.assertEqual(types, {"choice", "noul", "score"})
        self.assertIn("fault_domain", payload["questions"])
        self.assertIn("next_action", payload["questions"])
        self.assertIn("diagnosis_established", payload["questions"])
        self.assertIn("remediation_identified", payload["questions"])
        self.assertIn("resolution_verified", payload["questions"])

    def test_v14_next_actions_cover_diagnostic_lifecycle(self):
        criteria = JevClient.build_payload({"case_summary": "test"})["questions"]["next_action"]["criteria"]
        for expected in (
            "collect_system_information",
            "verify_compatibility",
            "run_diagnostic_test",
            "recommend_configuration_change",
            "recommend_software_repair",
            "verify_resolution",
            "finish_diagnosis",
            "escalate",
        ):
            self.assertIn(expected, criteria)

    def test_next_action_instructions_close_verified_cases(self):
        q = JevClient.build_payload({"case_summary": "test"})["questions"]["next_action"]
        self.assertIn("choose finish_diagnosis", q["instructions"])
        self.assertIn("choose verify_resolution", q["instructions"])
        self.assertIn("workflow action only", q["instructions"])

    def test_diagnosis_question_uses_useful_diagnostic_depth_not_deepest_root_cause(self):
        payload = JevClient.build_payload({"case_summary": "test"})
        q = payload["questions"]["diagnosis_established"]["instructions"]
        self.assertIn("useful troubleshooting level", q)
        self.assertIn("deepest underlying mechanism", q)
        self.assertIn("component, subsystem, configuration, service, or path", q)
        self.assertNotIn("primary root cause", q)

    def test_next_action_discourages_unnecessary_deeper_root_cause_excavation(self):
        q = JevClient.build_payload({"case_summary": "test"})["questions"]["next_action"]
        self.assertIn("Do not keep choosing diagnostic tests", q["instructions"])
        self.assertIn("deeper underlying mechanism", q["instructions"])

    def test_noul_questions_match_hosted_schema(self):
        payload = JevClient.build_payload({"case_summary": "test"})
        for question in payload["questions"].values():
            if question["type"] == "noul":
                self.assertEqual(set(question.keys()), {"type", "instructions"})

    def test_jv_live_key_routes_to_hosted_gateway(self):
        self.assertEqual(resolve_jev_endpoint("jv_live_example"), HOSTED_ENDPOINT)

    def test_other_key_routes_to_official_api(self):
        self.assertEqual(resolve_jev_endpoint("ts_example"), OFFICIAL_ENDPOINT)

    def test_explicit_endpoint_overrides_auto_routing(self):
        custom = "https://example.test/jev"
        self.assertEqual(resolve_jev_endpoint("jv_live_example", custom), custom)

    def test_sparse_evidence_fault_domain_is_conservative(self):
        payload = JevClient.build_payload({"case_summary": "PyTorch says GPU unavailable"})
        q = payload["questions"]["fault_domain"]
        self.assertIn("prefer 'unknown'", q["instructions"])
        self.assertIn("merely reporting", q["criteria"]["application"])

    @patch("techmedic.jev.time.perf_counter", side_effect=[100.0, 100.842])
    @patch("techmedic.jev.requests.post")
    def test_post_adds_response_time_telemetry(self, mock_post, _mock_clock):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"model": "jev-test", "answers": {"connected": {"type": "noul", "noul": 1.0}}}
        mock_post.return_value = response
        client = JevClient("jv_live_example")
        data = client.test_connection()
        self.assertAlmostEqual(data["_techmedic"]["jev_response_time_ms"], 842.0, places=1)
        self.assertEqual(data["_techmedic"]["route"], "Hosted Jev gateway")


    def test_jev_questions_understand_documentation_research_as_external_evidence(self):
        payload = JevClient.build_payload({"case_summary": "test"})
        diagnosis = payload["questions"]["diagnosis_established"]["instructions"]
        remediation = payload["questions"]["remediation_identified"]["instructions"]
        compatibility = payload["questions"]["next_action"]["criteria"]["verify_compatibility"]
        self.assertIn("official documentation research", diagnosis)
        self.assertIn("does not prove the user's local configuration", diagnosis)
        self.assertIn("official documentation research", remediation)
        self.assertIn("controlled documentation research", compatibility)


if __name__ == "__main__":
    unittest.main()
