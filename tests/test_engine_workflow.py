import tempfile
import unittest
from pathlib import Path

import sys
import types

try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    fake_openai = types.ModuleType("openai")

    class _Responses:
        def create(self, **kwargs):  # pragma: no cover - replaced in tests
            raise AssertionError("unexpected live call")

    class _OpenAI:
        def __init__(self, api_key=None):
            self.responses = _Responses()

    fake_openai.OpenAI = _OpenAI
    sys.modules["openai"] = fake_openai

from techmedic import database
from techmedic.models import normalize_diagnostic_state
from techmedic.diagnostic_engine import DiagnosticEngine


class _FakeLLM:
    def __init__(self, state):
        self.state = state
        self.last_update_state_time_ms = 100.0
        self.last_integrate_research_time_ms = None
        self.last_compose_response_time_ms = 200.0
        self.seen_jev = None
        self.seen_research = None

    def update_state(self, **kwargs):
        return dict(self.state)

    def integrate_research(self, *, diagnostic_state, research_result):
        self.last_integrate_research_time_ms = 150.0
        state = dict(diagnostic_state)
        state["research_evidence"] = {
            "summary": research_result.get("brief", ""),
            "source_ids": [s.get("id", "") for s in research_result.get("sources", [])],
            "category": research_result.get("category", ""),
            "query": research_result.get("query", ""),
        }
        return normalize_diagnostic_state(state)

    def compose_response(self, *, diagnostic_state, jev_result, safety, research_result=None):
        self.seen_jev = jev_result
        self.seen_research = research_result
        return "Synthetic response"


class _FakeResearch:
    def __init__(self, result=None):
        self.result = result or {
            "performed": False,
            "brief": "",
            "sources": [],
            "error": "",
            "_techmedic": {"research_response_time_ms": 0.0},
        }

    def research(self, *, request, diagnostic_state):
        return dict(self.result)


class _FakeJev:
    def __init__(self, result):
        self.result = result

    def evaluate(self, state):
        return self.result


class EngineWorkflowTests(unittest.TestCase):
    def _engine(self, db_path, state, jev_result):
        engine = object.__new__(DiagnosticEngine)
        engine.db_path = db_path
        engine.llm = _FakeLLM(state)
        engine.research = _FakeResearch()
        engine.jev = _FakeJev(jev_result)
        return engine

    @staticmethod
    def _safety():
        return {"blocked": False, "risk_level": "low", "warnings": [], "blocked_reasons": []}

    def test_previous_remediation_status_is_preserved_on_confidence_dip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            database.init_db(db_path)
            case_id = database.create_case(db_path, "DNS case")
            database.add_turn(
                db_path,
                case_id,
                "prior",
                {
                    "case_summary": "DNS case",
                    "status": "remediation_identified",
                    "diagnosis": {"summary": "DNS path failed", "basis": ["evidence"]},
                    "remediation": {"summary": "Use 1.1.1.1", "requirements": []},
                    "resolution_verification": {"verified": False, "evidence": []},
                },
                {"answers": {}},
                self._safety(),
                "prior response",
            )

            state = {
                "case_summary": "DNS changed; verification pending",
                "status": "possible_diagnosis",
                "diagnosis": {"summary": "DNS path failed", "basis": ["evidence"]},
                "remediation": {"summary": "DNS changed to 1.1.1.1", "requirements": ["verify"]},
                "resolution_verification": {"verified": False, "evidence": []},
                "lifecycle_control": {"reopen": False, "reason": ""},
                "candidate_next_tests": [],
            }
            jev = {
                "answers": {
                    "diagnosis_established": {"type": "noul", "noul": 0.80},
                    "remediation_identified": {"type": "noul", "noul": 0.82},
                    "resolution_verified": {"type": "noul", "noul": 0.03},
                    "next_action": {"type": "choice", "choice": "verify_resolution", "confidence": 0.99},
                },
                "_techmedic": {"jev_response_time_ms": 50.0},
            }
            engine = self._engine(db_path, state, jev)
            result = engine.run_cycle(case_id, "I changed DNS")

            self.assertEqual(result["diagnostic_state"]["status"], "remediation_identified")
            self.assertEqual(result["jev_result"]["_techmedic"]["effective_next_action"], "verify_resolution")
            self.assertFalse(result["jev_result"]["_techmedic"]["next_action_overridden"])

    def test_resolution_verified_overrides_raw_followup_but_preserves_raw_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            database.init_db(db_path)
            case_id = database.create_case(db_path, "DNS case")

            state = {
                "case_summary": "DNS fixed and websites load",
                "status": "resolution_verified",
                "diagnosis": {"summary": "Old DNS path failed", "basis": ["evidence"]},
                "remediation": {"summary": "Changed DNS to 1.1.1.1", "requirements": []},
                "resolution_verification": {"verified": True, "evidence": ["websites load"]},
                "lifecycle_control": {"reopen": False, "reason": ""},
                "candidate_next_tests": [],
            }
            jev = {
                "answers": {
                    "diagnosis_established": {"type": "noul", "noul": 0.92},
                    "remediation_identified": {"type": "noul", "noul": 0.87},
                    "resolution_verified": {"type": "noul", "noul": 0.95},
                    "next_action": {"type": "choice", "choice": "ask_for_information", "confidence": 0.58},
                },
                "_techmedic": {"jev_response_time_ms": 50.0},
            }
            engine = self._engine(db_path, state, jev)
            result = engine.run_cycle(case_id, "Everything works now")

            self.assertEqual(result["diagnostic_state"]["status"], "resolution_verified")
            self.assertEqual(result["jev_result"]["answers"]["next_action"]["choice"], "ask_for_information")
            self.assertEqual(result["jev_result"]["_techmedic"]["raw_next_action"], "ask_for_information")
            self.assertEqual(result["jev_result"]["_techmedic"]["effective_next_action"], "finish_diagnosis")
            self.assertTrue(result["jev_result"]["_techmedic"]["next_action_overridden"])
            self.assertEqual(engine.llm.seen_jev["answers"]["next_action"]["choice"], "ask_for_information")
            self.assertEqual(engine.llm.seen_jev["_techmedic"]["effective_next_action"], "finish_diagnosis")

    def test_tv_escalation_keeps_diagnosis_established_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            database.init_db(db_path)
            case_id = database.create_case(db_path, "TV dark screen")

            state = {
                "case_summary": "LCD/LED TV has faint image during dark-screen fault",
                # Reproduce the v1.4.2 analyst mistake directly; the engine must
                # still keep escalation separate from the lifecycle.
                "status": "escalate",
                "diagnosis": {
                    "summary": "Intermittent backlight or illumination-path failure",
                    "basis": [
                        "Flashlight test shows a faint moving image during the fault.",
                        "Audio and controls continue while the TV's own menus are not visible.",
                    ],
                },
                "remediation": {
                    "summary": "Arrange qualified television service",
                    "requirements": ["Exact failed component not identified"],
                },
                "resolution_verification": {"verified": False, "evidence": []},
                "lifecycle_control": {"reopen": False, "reason": ""},
                "candidate_next_tests": [],
            }
            jev = {
                "answers": {
                    "diagnosis_established": {"type": "noul", "noul": 0.92},
                    "remediation_identified": {"type": "noul", "noul": 0.37},
                    "resolution_verified": {"type": "noul", "noul": 0.02},
                    "next_action": {"type": "choice", "choice": "escalate", "confidence": 0.81},
                },
                "_techmedic": {"jev_response_time_ms": 50.0},
            }
            engine = self._engine(db_path, state, jev)
            result = engine.run_cycle(case_id, "I saw a faint image with a flashlight")

            self.assertEqual(result["diagnostic_state"]["status"], "diagnosis_established")
            self.assertEqual(result["jev_result"]["_techmedic"]["raw_next_action"], "escalate")
            self.assertEqual(result["jev_result"]["_techmedic"]["effective_next_action"], "escalate")
            self.assertFalse(result["jev_result"]["_techmedic"]["next_action_overridden"])
            saved = database.get_case(db_path, case_id)
            self.assertEqual(saved["status"], "diagnosis_established")


    def test_controlled_research_is_integrated_before_jev(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            database.init_db(db_path)
            case_id = database.create_case(db_path, "Compatibility case")
            state = {
                "case_summary": "Compatibility case",
                "status": "diagnosis_established",
                "diagnosis": {"summary": "CPU-only package installed", "basis": ["+cpu suffix", "GPU exists"]},
                "remediation": {"summary": "", "requirements": ["Verify supported versions"]},
                "resolution_verification": {"verified": False, "evidence": []},
                "lifecycle_control": {"reopen": False, "reason": ""},
                "research_request": {
                    "needed": True,
                    "category": "compatibility",
                    "query": "current supported package matrix",
                    "reason": "Need a current compatibility check",
                },
                "candidate_next_tests": [],
            }
            jev = {
                "answers": {
                    "diagnosis_established": {"type": "noul", "noul": 0.9},
                    "remediation_identified": {"type": "noul", "noul": 0.4},
                    "resolution_verified": {"type": "noul", "noul": 0.02},
                    "next_action": {"type": "choice", "choice": "verify_compatibility", "confidence": 0.8},
                },
                "_techmedic": {"jev_response_time_ms": 50.0},
            }
            engine = self._engine(db_path, state, jev)
            engine.research = _FakeResearch({
                "performed": True,
                "category": "compatibility",
                "query": "current supported package matrix",
                "reason": "Need a current compatibility check",
                "brief": "Official documentation confirms supported versions.",
                "sources": [{"id": "R1", "title": "Official PyTorch docs", "url": "https://docs.pytorch.org/get-started/locally/", "domain": "docs.pytorch.org", "primary_source": True, "cited_in_research": True}],
                "citations": [],
                "error": "",
                "_techmedic": {"research_response_time_ms": 300.0},
            })
            result = engine.run_cycle(case_id, "check compatibility")
            self.assertTrue(result["research"]["performed"])
            self.assertEqual(result["diagnostic_state"]["research_evidence"]["source_ids"], ["R1"])
            self.assertTrue(result["jev_result"]["_techmedic"]["research_performed"])
            self.assertEqual(result["jev_result"]["_techmedic"]["research_source_count"], 1)
            saved = database.get_turns(db_path, case_id)[-1]
            self.assertTrue(saved["research"]["performed"])


if __name__ == "__main__":
    unittest.main()
