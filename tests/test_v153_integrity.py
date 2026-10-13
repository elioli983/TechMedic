"""Offline v1.5.3 tests, including sanitized *real* v1.5.2 regression data."""
from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from techmedic import database
from techmedic.diagnostic_engine import DiagnosticEngine
from techmedic.export_bundle import build_diagnostic_bundle
from techmedic.models import normalize_diagnostic_state
from techmedic.research_integration import integrate_research_safely

FIXTURE = Path(__file__).parent / "fixtures" / "v152_pytorch_research_erosion.json"


def primary_research():
    return {
        "performed": True,
        "category": "compatibility", "query": "PyTorch compatibility Windows GTX 1080",
        "reason": "Verify official compatibility", "brief": "Official compatibility check.",
        "sources": [{
            "id": "R1", "url": "https://download.pytorch.org/whl/cu126/torch/",
            "title": "Official wheel listing", "primary_source": True,
            "cited_in_research": True,
        }],
        "citations": [{"source_id": "R1", "url": "https://download.pytorch.org/whl/cu126/torch/"}],
        "_techmedic": {"research_response_time_ms": 300.0},
    }


def before_state():
    state = json.loads(FIXTURE.read_text(encoding="utf8"))["before_research"]
    state["research_request"] = {"needed": True, "category": "compatibility", "query": "PyTorch GTX 1080", "reason": "Requires official documentation"}
    return state


def good_candidate():
    state = copy.deepcopy(before_state())
    state["research_evidence"] = {
        "summary": "Official package index lists compatible build.",
        "source_ids": ["R1"], "category": "compatibility", "query": "PyTorch GTX 1080",
    }
    state["remediation"] = {
        "summary": "Install the documented CUDA-enabled wheel after checking environment.",
        "requirements": ["Verify after the install"], "selection_ready": True, "blocking_requirements": [],
    }
    state["status"] = "remediation_identified"
    state["research_request"]["needed"] = False
    return state


class IntegrityIntegrationTests(unittest.TestCase):
    def test_real_v152_eraser_is_rejected_and_preserves_evidence(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf8"))
        before, candidate = fixture["before_research"], fixture["broken_v152_integration"]
        fixed, audit = integrate_research_safely(before, candidate, primary_research())
        self.assertEqual(audit["status"], "rejected")
        self.assertTrue(audit["fallback_used"])
        self.assertEqual(fixed["diagnosis"], before["diagnosis"])
        self.assertEqual(fixed["tests_performed"], before["tests_performed"])
        self.assertEqual(fixed["observations"], before["observations"])
        self.assertEqual(fixed["device"]["operating_system"], "Windows 11")
        self.assertTrue(any("established diagnosis" in x for x in audit["validation_errors"]))

    def test_sparse_raw_candidate_rejected_before_normalization(self):
        result, audit = integrate_research_safely(before_state(), {"status": "diagnosis_established", "research_evidence": {}}, primary_research())
        self.assertEqual(audit["status"], "rejected")
        self.assertIn("missing or invalid device (dict)", audit["validation_errors"])
        self.assertEqual(result["tests_performed"], before_state()["tests_performed"])

    def test_successful_research_preserves_all_original_local_evidence(self):
        before = before_state()
        candidate = good_candidate()
        candidate["observations"] = ["Documentation was consulted."]
        candidate["tests_performed"] = []
        candidate["symptoms"] = []
        candidate["diagnosis"]["basis"] = ["Additional research evidence."]
        candidate["device"]["model"] = "NVIDIA GeForce GTX 1080"
        after, audit = integrate_research_safely(before, candidate, primary_research())
        self.assertEqual(audit["status"], "accepted", audit)
        self.assertEqual(after["device"]["model"], "GTX 1080")
        for k in ("symptoms", "observations", "tests_performed"):
            for item in before[k]:
                self.assertIn(item, after[k])
        for item in before["diagnosis"]["basis"]:
            self.assertIn(item, after["diagnosis"]["basis"])
        self.assertTrue(after["remediation"]["selection_ready"])
        self.assertEqual(after["research_evidence"]["source_ids"], ["R1"])
        self.assertGreater(audit["preserved_evidence"].get("tests_performed", 0), 0)

    def test_unknown_source_id_rejects_instead_of_silently_dropping(self):
        c = good_candidate()
        c["research_evidence"]["source_ids"] = ["R9"]
        _, audit = integrate_research_safely(before_state(), c, primary_research())
        self.assertEqual(audit["status"], "rejected")
        self.assertTrue(any("invalid" in x for x in audit["validation_errors"]))

    def test_uncited_sources_cannot_justify_remediation(self):
        r = primary_research()
        r["sources"][0]["cited_in_research"] = False
        _, audit = integrate_research_safely(before_state(), good_candidate(), r)
        self.assertEqual(audit["status"], "rejected")

    def test_research_cannot_mark_local_resolution_verified(self):
        c = good_candidate()
        c["resolution_verification"]["verified"] = True
        _, audit = integrate_research_safely(before_state(), c, primary_research())
        self.assertEqual(audit["status"], "rejected")
        self.assertTrue(any("resolution verification" in x for x in audit["validation_errors"]))

    def test_unresolved_repair_not_marked_ready_without_citation(self):
        c = good_candidate()
        c["research_evidence"]["source_ids"] = []
        _, audit = integrate_research_safely(before_state(), c, primary_research())
        self.assertEqual(audit["status"], "rejected")

    def test_prior_valid_metadata_updated_from_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "techmedic.sqlite3"
            database.init_db(db)
            cid = database.create_case(db, "PyTorch", manufacturer="NVIDIA", model="GTX 1080", operating_system="Unknown")
            database.update_case(db, cid, operating_system="Windows 11", manufacturer="Another Company")
            case = database.get_case(db, cid)
            self.assertEqual(case["operating_system"], "Windows 11")
            self.assertEqual(case["manufacturer"], "NVIDIA")


class _FakeLLM:
    def __init__(self, candidate=None, exc=None):
        self.candidate = candidate
        self.exc = exc
        self.last_update_state_time_ms = 100.0
        self.last_integrate_research_time_ms = 200.0
        self.last_compose_response_time_ms = 100.0
        self.seen_research = None
        self.seen_state = None

    def update_state(self, **kwargs):
        return copy.deepcopy(before_state())

    def integrate_research(self, **kwargs):
        if self.exc:
            raise self.exc
        return copy.deepcopy(self.candidate)

    def compose_response(self, *, diagnostic_state, jev_result, safety, research_result):
        self.seen_research = copy.deepcopy(research_result)
        self.seen_state = copy.deepcopy(diagnostic_state)
        return "Next diagnostic step"


class _FakeJev:
    def __init__(self):
        self.seen_state = None

    def evaluate(self, state):
        self.seen_state = copy.deepcopy(state)
        return {"answers": {
            "diagnosis_established": {"noul": 0.94},
            "remediation_identified": {"noul": 0.94},
            "resolution_verified": {"noul": 0.02},
            "next_action": {"choice": "recommend_software_repair", "confidence": .8},
        }, "_techmedic": {"jev_response_time_ms": 20.0}}


class _FakeResearch:
    def research(self, **kwargs):
        return primary_research()


class IntegrityWorkflowTests(unittest.TestCase):
    def _run(self, candidate=None, exc=None):
        context = tempfile.TemporaryDirectory()
        self.addCleanup(context.cleanup)
        db = Path(context.name) / "test.sqlite3"
        database.init_db(db)
        cid = database.create_case(db, "PyTorch issue", operating_system="Unknown")
        engine = object.__new__(DiagnosticEngine)
        engine.db_path = db
        engine.llm = _FakeLLM(candidate, exc)
        engine.jev = _FakeJev()
        engine.research = _FakeResearch()
        result = engine.run_cycle(cid, "Windows 11 + CPU build")
        return engine, result, db, cid

    def test_jev_receives_preserved_state_and_no_unvalidated_research(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf8"))
        engine, result, db, cid = self._run(candidate=fixture["broken_v152_integration"])
        state = engine.jev.seen_state
        self.assertEqual(state["device"]["operating_system"], "Windows 11")
        self.assertIn("2.14.0+cpu", " ".join(state["observations"]))
        self.assertFalse(state["controlled_research"]["performed"])
        self.assertEqual(state["controlled_research"]["brief"], "")
        self.assertFalse(result["diagnostic_state"]["remediation"]["selection_ready"])
        self.assertEqual(result["jev_result"]["_techmedic"]["effective_next_action"], "verify_compatibility")
        self.assertTrue(result["jev_result"]["_techmedic"]["research_integration_fallback_used"])
        self.assertFalse(engine.llm.seen_research["performed"])
        self.assertFalse(engine.llm.seen_research["sources"])
        turn = database.get_turns(db, cid)[-1]
        self.assertEqual(turn["research"]["_techmedic"]["integration_validation"]["status"], "rejected")
        self.assertEqual(database.get_case(db, cid)["operating_system"], "Windows 11")
        case = database.get_case(db, cid)
        with zipfile.ZipFile(io.BytesIO(build_diagnostic_bundle(case, [turn]))) as z:
            meta = json.loads(z.read("MANIFEST.json"))
            telemetry = json.loads(z.read("06_LATEST_TIMING_TELEMETRY.json"))
            self.assertEqual(meta["techmedic_version"], "1.5.6")
            self.assertEqual(telemetry["research_integration_status"], "rejected")
            self.assertTrue(telemetry["research_integration_validation_errors"])

    def test_integration_runtime_error_falls_back_without_abort(self):
        engine, result, _, _ = self._run(exc=ValueError("invalid model JSON"))
        self.assertEqual(result["research"]["_techmedic"]["integration_validation"]["status"], "error")
        self.assertTrue(result["diagnostic_state"]["diagnosis"]["summary"])
        self.assertEqual(result["jev_result"]["_techmedic"]["effective_next_action"], "verify_compatibility")

    def test_valid_full_integration_reaches_jev_with_provenance(self):
        engine, result, _, _ = self._run(candidate=good_candidate())
        self.assertEqual(result["research"]["_techmedic"]["integration_validation"]["status"], "accepted")
        self.assertTrue(engine.jev.seen_state["controlled_research"]["performed"])
        self.assertEqual(engine.jev.seen_state["research_evidence"]["source_ids"], ["R1"])
        self.assertTrue(result["diagnostic_state"]["tests_performed"])
        self.assertEqual(result["diagnostic_state"]["status"], "remediation_identified")


if __name__ == "__main__":
    unittest.main()
