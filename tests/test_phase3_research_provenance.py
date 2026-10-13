"""TechMedic v1.5.4 Phase 3: research process-status truthfulness tests.

All inputs are SYNTHETIC. API access is replaced at the diagnostic engine
boundaries, and no physical repairs, browser actions, or external calls occur.
"""
from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys
import types

# Offline harness never makes real API calls; dependency stub for sandbox only.
try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType('openai')
    class DisallowedAPI:
        def __init__(self, *args, **kwargs):
            raise AssertionError('No live OpenAI call is permitted in Phase 3 offline tests')
    stub.OpenAI = DisallowedAPI
    sys.modules['openai'] = stub

from techmedic import database
from techmedic.consistency import research_provenance_issues, response_issues
from techmedic.diagnostic_engine import DiagnosticEngine
from techmedic.export_bundle import build_diagnostic_bundle
from techmedic.prompts import RESPONDER_INSTRUCTIONS
from test_fault_injection_controlled import (
    established, cited_research, valid_delta, FakeLLM, FakeJev, FakeResearch,
)

SKIPPED = dict(requested=False, retrieved=False, retrieval_failed=False, integration_status='skipped')
RETRIEVAL_FAILED = dict(requested=True, retrieved=False, retrieval_failed=True, integration_status='skipped')
REJECTED = dict(requested=True, retrieved=True, retrieval_failed=False, integration_status='rejected')
ACCEPTED = dict(requested=True, retrieved=True, retrieval_failed=False, integration_status='accepted')

BAD = 'The integrated documentation research step did not complete, so compatibility is still unknown.'
GOOD = 'No documentation search was performed for this turn. Confirm the remaining compatibility prerequisites.'


class Phase3ResearchProcessStatusTests(unittest.TestCase):
    def test_01_known_B1_false_failed_research_detected_when_skipped(self):
        issues = research_provenance_issues(BAD, SKIPPED)
        self.assertEqual(len(issues), 1)
        self.assertIn('not requested', issues[0])

    def test_02_skipped_truthful_text_is_not_flagged(self):
        self.assertEqual(research_provenance_issues(GOOD, SKIPPED), [])
        self.assertEqual(research_provenance_issues('The diagnosis is retained; verify prerequisites.', SKIPPED), [])

    def test_03_skipped_research_can_be_described_as_not_performed(self):
        self.assertEqual(research_provenance_issues('Web research was not performed.', SKIPPED), [])
        self.assertEqual(research_provenance_issues('No research was requested for this turn.', SKIPPED), [])

    def test_04_requested_but_disabled_is_not_mistaken_for_not_requested(self):
        x = dict(SKIPPED, requested=True)
        self.assertEqual(research_provenance_issues('The documentation research step did not complete.', x), [])
        self.assertTrue(research_provenance_issues('Research was never attempted.', x))

    def test_05_retrieval_failure_is_describable_as_failed(self):
        self.assertEqual(research_provenance_issues('The web search failed; do not infer compatibility.', RETRIEVAL_FAILED), [])

    def test_06_retrieval_attempt_cannot_be_denied(self):
        self.assertTrue(research_provenance_issues('Research was not requested.', RETRIEVAL_FAILED))

    def test_07_accepted_integration_not_falsely_described_as_failed(self):
        self.assertTrue(research_provenance_issues('Documentation research did not complete.', ACCEPTED))
        self.assertEqual(research_provenance_issues('Research findings were retrieved and integrated.', ACCEPTED), [])

    def test_08_rejected_integration_must_distinguish_retrieval(self):
        self.assertEqual(research_provenance_issues(
            'Research was retrieved but integration failed validation. No repair is authorized.', REJECTED), [])
        self.assertTrue(research_provenance_issues('No documentation was retrieved.', REJECTED))
        self.assertTrue(research_provenance_issues('Research was not performed.', REJECTED))

    def test_09_backward_compatible_without_context(self):
        state = established()
        self.assertEqual(response_issues(BAD, state, 'verify_compatibility'), [])
        self.assertTrue(response_issues(BAD, state, 'verify_compatibility', research_context=SKIPPED))

    def test_10_responder_prompt_describes_all_four_distinct_states(self):
        prompt = RESPONDER_INSTRUCTIONS
        for fragment in ('requested=false', 'retrieval_failed=true', 'integration_status=rejected',
                         'integration_status=accepted', 'DO NOT claim research failed'):
            self.assertIn(fragment, prompt)


class Phase3IntegratedEngineTests(unittest.TestCase):
    def exercise(self, *, response_texts, state=None, research_result=None,
                 integrations=(), action='verify_compatibility'):
        with tempfile.TemporaryDirectory(prefix='tm_p3_') as folder:
            db = Path(folder) / 'p3.sqlite'
            database.init_db(db)
            cid = database.create_case(db, 'SYNTHETIC Phase 3 response provenance')
            initial_state = copy.deepcopy(state or established())
            llm = FakeLLM(initial_state, integrations=integrations, replies=response_texts)
            engine = object.__new__(DiagnosticEngine)
            engine.db_path = db
            engine.llm = llm
            engine.research = FakeResearch(research_result if research_result is not None else
                                          {'performed': False, 'error': '', '_techmedic': {}})
            engine.jev = FakeJev(action=action)
            result = engine.run_cycle(cid, 'SYNTHETIC PROVENANCE VALIDATION (no user action)')
            turn = database.get_turns(db, cid)[0]
            self.assertEqual(result['assistant_text'], turn['assistant_text'])
            self.assertEqual(result['diagnostic_state'], turn['diagnostic_state'])
            self.assertEqual(result['jev_result'], turn['jev_result'])
            self.assertEqual(result['research'], turn['research'])
            with zipfile.ZipFile(io.BytesIO(build_diagnostic_bundle(database.get_case(db, cid), [turn]))) as z:
                self.assertEqual(len(z.namelist()), 12)
                archive_jev = json.loads(z.read('03_LATEST_JEV_DECISION_RESULT.json'))
                self.assertEqual(archive_jev['_techmedic']['response_correction_status'],
                                 result['jev_result']['_techmedic']['response_correction_status'])
                self.assertEqual(archive_jev['_techmedic']['research_response_provenance'],
                                 result['jev_result']['_techmedic']['research_response_provenance'])
            return result, llm

    @staticmethod
    def skipped_state():
        st = established()
        st['research_request'] = {'needed': False, 'category': 'other', 'query': '', 'reason': ''}
        return st

    def test_11_skipped_wrong_then_correct_one_retry_preserves_evidence(self):
        state = self.skipped_state()
        r, llm = self.exercise(response_texts=(BAD, GOOD), state=state)
        t = r['jev_result']['_techmedic']
        self.assertEqual(t['response_correction_status'], 'accepted')
        self.assertEqual(t['responder_retry_count'], 1)
        self.assertEqual(llm.c, 2)
        self.assertEqual(r['assistant_text'], GOOD)
        self.assertEqual(r['diagnostic_state']['observations'], state['observations'])
        self.assertEqual(r['diagnostic_state']['diagnosis'], state['diagnosis'])
        self.assertEqual(t['research_response_provenance'], SKIPPED)
        self.assertFalse(t['research_requested'])
        self.assertFalse(t['research_performed'])

    def test_12_skipped_two_wrong_falls_back_once_with_no_unsupported_fix(self):
        r, llm = self.exercise(response_texts=(BAD, BAD), state=self.skipped_state())
        t = r['jev_result']['_techmedic']
        self.assertEqual((llm.c, t['responder_retry_count'], t['response_correction_status']),
                         (2, 1, 'failed_safe'))
        self.assertFalse(research_provenance_issues(r['assistant_text'], SKIPPED))
        self.assertNotIn('pip install', r['assistant_text'].lower())
        self.assertNotIn('did not complete', r['assistant_text'].lower())

    def test_13_skipped_accurate_does_not_waste_correction(self):
        r, llm = self.exercise(response_texts=(GOOD,), state=self.skipped_state())
        t = r['jev_result']['_techmedic']
        self.assertEqual(llm.c, 1)
        self.assertEqual(t['response_correction_status'], 'not_needed')
        self.assertFalse(t.get('responder_retry_count'))

    def test_14_real_retrieval_failure_not_reported_as_skipped(self):
        text = 'The documentation research request failed; verify compatibility before making changes.'
        failed = {'performed': False, 'error': 'SYNTHETIC timeout', '_techmedic': {}}
        r, llm = self.exercise(response_texts=(text,), research_result=failed)
        t = r['jev_result']['_techmedic']
        self.assertEqual(t['research_response_provenance'], RETRIEVAL_FAILED)
        self.assertEqual(llm.c, 1)
        self.assertEqual(t['response_correction_status'], 'not_needed')

    def test_15_retrieved_rejected_distinguishes_integration_failure(self):
        bad_delta = {'format': 'research_delta_v1', 'research_evidence': 'malformed'}
        statement = 'Research was retrieved but integration failed validation; do not install anything.'
        r, llm = self.exercise(response_texts=(statement,), research_result=cited_research(),
                               integrations=(bad_delta, bad_delta))
        t = r['jev_result']['_techmedic']
        self.assertEqual(t['research_response_provenance'], REJECTED)
        self.assertEqual(t['research_integration_attempts'], 2)
        self.assertEqual(llm.c, 1)
        self.assertEqual(t['response_correction_status'], 'not_needed')
        self.assertTrue(t['research_integration_fallback_used'])
        self.assertFalse(t['current_remediation_ready'])

    def test_16_integrated_research_acceptance_stays_truthful(self):
        statement = 'Research was retrieved and integrated with source [R1]. Confirm local prerequisites.'
        r, llm = self.exercise(response_texts=(statement,), research_result=cited_research(),
                               integrations=(valid_delta(),))
        t = r['jev_result']['_techmedic']
        self.assertEqual(t['research_response_provenance'], ACCEPTED)
        self.assertEqual(t['research_integration_attempts'], 1)
        self.assertEqual(llm.c, 1)
        self.assertEqual(t['response_correction_status'], 'not_needed')
        self.assertEqual(r['diagnostic_state']['research_evidence']['source_ids'], ['R1'])


if __name__ == '__main__':
    unittest.main()
