import sys
import types
import unittest
from unittest.mock import Mock, patch

try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    fake_openai = types.ModuleType("openai")

    class _Responses:
        def create(self, **kwargs):  # pragma: no cover
            raise AssertionError("unexpected live call")

    class _OpenAI:
        def __init__(self, api_key=None):
            self.responses = _Responses()

    fake_openai.OpenAI = _OpenAI
    sys.modules["openai"] = fake_openai

from techmedic.research import ResearchClient, append_research_sources, linkify_research_citations


class ResearchTests(unittest.TestCase):
    def test_no_request_skips_search(self):
        client = ResearchClient("test-key", "test-model")
        client.client.responses.create = Mock(side_effect=AssertionError("should not call"))
        result = client.research(request={"needed": False}, diagnostic_state={})
        self.assertFalse(result["performed"])
        self.assertIn("No research requested", result["skipped_reason"])

    @patch("techmedic.research.time.perf_counter", side_effect=[10.0, 11.2])
    def test_research_forces_web_search_and_extracts_sources(self, _clock):
        client = ResearchClient("test-key", "test-model", max_sources=5)
        response = Mock()
        response.output_text = "Official documentation confirms the support requirement."
        response.model_dump.return_value = {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "type": "search",
                        "query": "support matrix",
                        "sources": [
                            {"type": "url", "url": "https://docs.example.com/a", "title": "Official A"},
                            {"type": "url", "url": "https://docs.example.com/b", "title": "Official B"},
                        ],
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Official documentation confirms the support requirement.",
                            "annotations": [
                                {"type": "url_citation", "url": "https://docs.example.com/a", "title": "Official A"}
                            ],
                        }
                    ],
                },
            ]
        }
        client.client.responses.create = Mock(return_value=response)

        result = client.research(
            request={
                "needed": True,
                "category": "compatibility",
                "query": "support matrix",
                "reason": "verify current support",
            },
            diagnostic_state={"device": {}},
        )
        self.assertTrue(result["performed"])
        self.assertEqual([s["id"] for s in result["sources"]], ["R1", "R2"])
        self.assertEqual(result["sources"][0]["domain"], "docs.example.com")
        self.assertEqual(result["_techmedic"]["web_search_calls"], 1)
        self.assertAlmostEqual(result["_techmedic"]["research_response_time_ms"], 1200.0, places=1)

        kwargs = client.client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["tools"], [{"type": "web_search"}])
        self.assertEqual(kwargs["tool_choice"], "required")
        self.assertIn("web_search_call.action.sources", kwargs["include"])

    def test_citation_markers_become_clickable_and_sources_are_appended(self):
        research = {
            "performed": True,
            "sources": [
                {"id": "R1", "title": "Official docs", "url": "https://example.com/docs", "domain": "example.com"}
            ],
        }
        text = linkify_research_citations("Supported according to [R1].", research)
        self.assertIn("[R1](https://example.com/docs)", text)
        text = append_research_sources(text, research)
        self.assertIn("### Sources consulted", text)
        self.assertIn("R1 — Official docs", text)


if __name__ == "__main__":
    unittest.main()
