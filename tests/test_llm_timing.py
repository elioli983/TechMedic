import sys
import types
import unittest
from unittest.mock import Mock, patch

try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    fake_openai = types.ModuleType("openai")

    class _Responses:
        def create(self, **kwargs):  # pragma: no cover - replaced by Mock in tests
            raise AssertionError("unexpected live call")

    class _OpenAI:
        def __init__(self, api_key=None):
            self.responses = _Responses()

    fake_openai.OpenAI = _OpenAI
    sys.modules["openai"] = fake_openai

from techmedic.llm import LLMClient


class LLMTimingTests(unittest.TestCase):
    def test_update_state_records_elapsed_time(self):
        client = LLMClient("test-key", "test-model")
        response = Mock()
        response.output_text = '{"case_summary":"Example","status":"investigating"}'
        client.client.responses.create = Mock(return_value=response)
        with patch("techmedic.llm.time.perf_counter", side_effect=[10.0, 11.25]):
            state = client.update_state(latest_user_text="problem", previous_state=None)
        self.assertEqual(state["case_summary"], "Example")
        self.assertAlmostEqual(client.last_update_state_time_ms, 1250.0, places=1)

    def test_compose_response_records_elapsed_time(self):
        client = LLMClient("test-key", "test-model")
        response = Mock()
        response.output_text = "Run the next test."
        client.client.responses.create = Mock(return_value=response)
        with patch("techmedic.llm.time.perf_counter", side_effect=[20.0, 20.75]):
            text = client.compose_response(diagnostic_state={}, jev_result={}, safety={})
        self.assertEqual(text, "Run the next test.")
        self.assertAlmostEqual(client.last_compose_response_time_ms, 750.0, places=1)


    def test_integrate_research_records_elapsed_time(self):
        client = LLMClient("test-key", "test-model")
        response = Mock()
        response.output_text = '{"case_summary":"Example","status":"diagnosis_established","research_evidence":{"summary":"docs","source_ids":["R1"],"category":"compatibility","query":"q"}}'
        client.client.responses.create = Mock(return_value=response)
        with patch("techmedic.llm.time.perf_counter", side_effect=[30.0, 31.5]):
            state = client.integrate_research(
                diagnostic_state={"case_summary": "Example"},
                research_result={"performed": True, "brief": "docs"},
            )
        self.assertEqual(state["research_evidence"]["source_ids"], ["R1"])
        self.assertAlmostEqual(client.last_integrate_research_time_ms, 1500.0, places=1)


if __name__ == "__main__":
    unittest.main()
