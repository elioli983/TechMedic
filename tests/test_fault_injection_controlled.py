"""Reproducible TechMedic v1.5.4 controlled fault injection. NO real API calls.

Deliberate contradictions probe currently *implemented* guards, not model quality.
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

# Only used by DiagnosticEngine imports; real API access is forbidden in these tests.
try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType('openai')
    class ForbiddenAPI:
        def __init__(self, *args, **kwargs):
            raise AssertionError('No live API calls allowed during offline fault injection')
    stub.OpenAI = ForbiddenAPI
    sys.modules['openai'] = stub

from techmedic import database
from techmedic.diagnostic_engine import DiagnosticEngine
from techmedic.export_bundle import build_diagnostic_bundle
from techmedic.models import normalize_diagnostic_state
from techmedic.research_delta import integrate_research_delta_safely
from techmedic.consistency import response_issues

# Synthetic evidence: these observations are fixture text, not local measurements.
PROTECTED = ('device', 'observations', 'tests_performed', 'diagnosis', 'resolution_verification')


def established(*, terminal=False, television=False):
    if television:
        return normalize_diagnostic_state({
            'case_summary': 'SYNTHETIC TV dark screen with sound',
            'device': {'type': 'television', 'manufacturer': 'Sony', 'model': 'BRAVIA XR Z9K'},
            'observations': ['audio continues', 'image faint under flashlight'],
            'tests_performed': [{'test': 'flashlight', 'result': 'faint image'}],
            'diagnosis': {'summary': 'illumination subsystem fault suspected',
                          'basis': ['sound continues', 'faint picture in flashlight']},
            'remediation': {'summary': '', 'selection_ready': False,
                            'blocking_requirements': ['internal service diagnosis required']},
            'status': 'diagnosis_established',
        })
    return normalize_diagnostic_state({
        'case_summary': 'SYNTHETIC PyTorch CUDA failure with CPU build',
        'device': {'type': 'computer', 'application': 'PyTorch', 'model': 'GTX 1080',
                   'operating_system': 'Windows 11'},
        'observations': ['torch version 2.14.0+cpu', 'CUDA unavailable'],
        'tests_performed': [{'test': 'torch runtime', 'result': '2.14.0+cpu'}],
        'diagnosis': {'summary': 'CPU-only runtime cannot use CUDA',
                      'basis': ['2.14.0+cpu', 'torch.version.cuda=None']},
        'resolution_verification': {'verified': terminal, 'evidence': ['SYNTHETIC GPU tensor succeeded'] if terminal else []},
        'remediation': {'summary': 'Use vetted CUDA wheel' if terminal else 'Find compatible replacement',
                        'selection_ready': terminal,
                        'blocking_requirements': [] if terminal else ['Confirm CUDA package compatibility'],
                        'install_command': 'python -m pip install --force-reinstall torch==2.14.0+cu126 --index-url https://download.pytorch.org/whl/cu126' if terminal else ''},
        'status': 'resolution_verified' if terminal else 'diagnosis_established',
        'research_request': {'needed': not terminal, 'category': 'compatibility', 'query': 'official supported wheel', 'reason': 'find distribution'},
    })


def cited_research():
    return {'performed': True, 'category': 'compatibility', 'query': 'official CUDA wheel',
            'brief': 'SYNTHETIC official wheel listing',
            'sources': [{'id': 'R1', 'url': 'https://download.pytorch.org/whl/cu126/torch/',
                         'primary_source': True, 'cited_in_research': True}],
            'citations': [{'source_id': 'R1'}], '_techmedic': {'research_response_time_ms': 4.0}}


def valid_delta():
    return {'format': 'research_delta_v1',
            'research_evidence': {'summary': 'SYNTHETIC cited CUDA distribution metadata',
                                  'source_ids': ['R1'], 'category': 'compatibility', 'query': 'official CUDA wheel'},
            'remediation': {'summary': 'Replace CPU build with specific CUDA wheel', 'requirements': [],
                            'selection_ready': True, 'blocking_requirements': [],
                            'install_command': 'python -m pip install --force-reinstall torch==2.14.0+cu126 --index-url https://download.pytorch.org/whl/cu126',
                            'verification_commands': ['python -c "import torch; print(torch.cuda.is_available())"']},
            'research_request': {'needed': False, 'category': 'compatibility', 'query': '', 'reason': ''}}


class FakeResearch:
    def __init__(self, result): self.result = result
    def research(self, **kwargs): return copy.deepcopy(self.result)


class FakeJev:
    def __init__(self, *, action='recommend_software_repair', terminal=False, tv=False):
        self.action, self.terminal, self.tv = action, terminal, tv
    def evaluate(self, state):
        self.last_received = copy.deepcopy(state)
        return {'answers': {'diagnosis_established': {'noul': 0.94},
                            'remediation_identified': {'noul': 0.88 if self.terminal else 0.1 if self.tv else .83},
                            'resolution_verified': {'noul': .98 if self.terminal else .02},
                            'next_action': {'choice': self.action, 'confidence': .92}},
                '_techmedic': {'jev_response_time_ms': 3.0}}


class FakeLLM:
    def __init__(self, state, integrations=(), replies=('### Next step\nVerify the stated prerequisite.',)):
        self.state = copy.deepcopy(state)
        self.integrations = list(integrations)
        self.replies = list(replies)
        self.i = 0
        self.c = 0
        self.last_integrate_research_raw = ''
        self.last_integrate_research_time_ms = 2.0
        self.last_update_state_time_ms = 2.0
        self.last_compose_response_time_ms = 2.0
        self.repair_inputs = []
    def update_state(self, **kwargs): return copy.deepcopy(self.state)
    def _candidate(self):
        value = copy.deepcopy(self.integrations[self.i])
        self.i += 1
        if isinstance(value, Exception):
            self.last_integrate_research_raw = '{BROKEN JSON: "api_key": "SYNTHETIC_FAKE_SECRET"'
            raise value
        self.last_integrate_research_raw = json.dumps(value)
        return value
    def integrate_research(self, **kwargs): return self._candidate()
    def repair_research_delta(self, **kwargs):
        self.repair_inputs.append(copy.deepcopy(kwargs))
        return self._candidate()
    def compose_response(self, **kwargs):
        value = self.replies[self.c] if self.c < len(self.replies) else self.replies[-1]
        self.c += 1
        if isinstance(value, Exception): raise value
        return value


class FaultInjection(unittest.TestCase):
    def run_engine(self, *, state=None, research=None, integrations=(), replies=None,
                   jev=None, prompt='SYNTHETIC diagnostic fault-injection cycle'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / 'test.sqlite'
        database.init_db(db_path)
        cid = database.create_case(db_path, 'Synthetic fault-injection fixture')
        llm = FakeLLM(state or established(), integrations,
                      replies or ('### Next step\nVerify prerequisite before changes.',))
        e = object.__new__(DiagnosticEngine)
        e.db_path = db_path
        e.llm = llm
        e.research = FakeResearch(research if research is not None else {'performed': False, '_techmedic': {}})
        e.jev = jev or FakeJev()
        result = e.run_cycle(cid, prompt)
        return result, llm, db_path, cid, e

    def assert_protected(self, before, after):
        for key in PROTECTED:
            self.assertEqual(before[key], after[key], key)

    def test_A1_malformed_then_valid_accepts_after_one_retry(self):
        before = established()
        bad = {'format': 'research_delta_v1', 'research_evidence': 'not an object'}
        result, llm, db, cid, _ = self.run_engine(state=before, research=cited_research(),
                                                  integrations=(bad, valid_delta()))
        audit = result['research']['_techmedic']['integration_validation']
        self.assert_protected(before, result['diagnostic_state'])
        self.assertEqual((audit['status'], audit['attempt_count'], audit['recovered_after_retry']), ('accepted', 2, True))
        self.assertFalse(audit['fallback_used'])
        self.assertEqual(result['diagnostic_state']['research_evidence']['source_ids'], ['R1'])
        self.assertTrue(result['jev_result']['_techmedic']['current_remediation_ready'])
        self.assertEqual(llm.i, 2)
        self.assertEqual(len(llm.repair_inputs), 1)
        self.assertEqual(len(database.get_turns(db, cid)), 1)

    def test_A2_two_bad_deltas_fall_back_and_close_repair_gate(self):
        before = established()
        bad = {'format': 'research_delta_v1', 'remediation': {'selection_ready': True}}
        result, llm, _, _, _ = self.run_engine(state=before, research=cited_research(), integrations=(bad, bad))
        self.assert_protected(before, result['diagnostic_state'])
        audit = result['research']['_techmedic']['integration_validation']
        self.assertEqual((audit['status'], audit['attempt_count'], audit['fallback_used']), ('rejected', 2, True))
        self.assertTrue(audit['repair_gate_closed'])
        self.assertFalse(result['jev_result']['_techmedic']['current_remediation_ready'])
        self.assertIn(result['jev_result']['_techmedic']['effective_next_action'], ('verify_compatibility', 'collect_system_information'))
        self.assertNotIn('pip install', result['assistant_text'])
        self.assertEqual(llm.i, 2)
        self.assertTrue(result['research']['performed'])
        self.assertFalse(llm.repair_inputs[0]['diagnostic_state']['remediation']['selection_ready'])

    def test_A3a_hostile_delta_protected_fields_rejected(self):
        before = established()
        hostile = valid_delta()
        hostile['observations'] = ['nothing happened']
        hostile['diagnosis'] = {'summary': 'invented root cause'}
        after, audit = integrate_research_delta_safely(before, hostile, cited_research())
        self.assertEqual(audit['status'], 'rejected')
        self.assertIn('protected diagnostic fields', str(audit['validation_errors']))
        self.assert_protected(before, after)

    def test_A3d_wrong_type_nested_nodes_rejected_without_exception(self):
        malformed = valid_delta()
        malformed['research_evidence'] = 'plain-text instead of research evidence object'
        malformed['remediation'] = 'plain-text instead of remediation object'
        malformed['research_request'] = []
        after, audit = integrate_research_delta_safely(established(), malformed, cited_research())
        self.assertEqual(audit['status'], 'rejected')
        self.assertTrue(audit['fallback_used'])
        self.assertTrue(audit['validation_errors'])
        self.assert_protected(established(), after)

    def test_A3b_forged_source_R99_rejected_and_repaired(self):
        bad = valid_delta()
        bad['research_evidence']['source_ids'] = ['R99']
        result, llm, *_ = self.run_engine(research=cited_research(), integrations=(bad, valid_delta()))
        audit = result['research']['_techmedic']['integration_validation']
        self.assertEqual(audit['status'], 'accepted')
        self.assertIn('R99', ' '.join(audit['first_attempt_errors']))
        self.assertEqual(result['diagnostic_state']['research_evidence']['source_ids'], ['R1'])
        self.assertEqual(llm.i, 2)

    def test_A3c_non_json_first_attempt_exception_then_valid(self):
        result, llm, *_ = self.run_engine(research=cited_research(),
                                           integrations=(ValueError('synthetic non-JSON'), valid_delta()))
        audit = result['research']['_techmedic']['integration_validation']
        self.assertEqual((audit['status'], audit['attempt_count']), ('accepted', 2))
        self.assertTrue(audit['recovered_after_retry'])
        self.assertEqual(llm.i, 2)

    def test_A4_bundle_tracks_attempts_hash_reject_and_sanitizes_secret(self):
        fake_secret = 'sk-' + 'z' * 24
        bad = {'format': 'research_delta_v1', 'api_key': fake_secret}
        result, _, db, cid, _ = self.run_engine(research=cited_research(), integrations=(bad, bad))
        bundle = build_diagnostic_bundle(database.get_case(db, cid), database.get_turns(db, cid))
        with zipfile.ZipFile(io.BytesIO(bundle)) as z:
            self.assertEqual(len(z.namelist()), 12)
            whole = '\n'.join(z.read(p).decode('utf-8') for p in z.namelist())
            audit = json.loads(z.read('04_LATEST_CONTROLLED_RESEARCH.json'))['_techmedic']['integration_validation']
            trace = json.loads(z.read('06_LATEST_TIMING_TELEMETRY.json'))
            self.assertEqual(audit['attempt_count'], 2)
            self.assertEqual(audit['status'], 'rejected')
            self.assertTrue(audit['fallback_used'])
            self.assertEqual(len(audit['candidate_sha256']), 64)
            self.assertTrue(audit['candidate_chars'] > 0)
            self.assertTrue(audit['validation_errors'])
            self.assertNotIn(fake_secret, whole)
            self.assertEqual(trace['research_integration_attempts'], 2)
            self.assertTrue(trace['research_performed'])
            self.assertFalse(trace['research_integrated'])

    def test_B1_contradiction_corrected_once(self):
        first = '### Current assessment\nCompatibility is fully verified. Proceed with installation now.'
        second = '### Next step\nConfirm the unresolved compatibility requirement before changing anything.'
        result, llm, *_ = self.run_engine(replies=(first, second))
        t = result['jev_result']['_techmedic']
        self.assertEqual(llm.c, 2)
        self.assertEqual(t['response_correction_status'], 'accepted')
        self.assertEqual(t['responder_retry_count'], 1)
        self.assertNotIn('fully verified', result['assistant_text'])
        self.assertEqual(t['effective_next_action'], 'verify_compatibility')

    def test_B2_two_contradictions_produce_safe_fallback(self):
        bad = 'Compatibility is fully verified. Proceed with installation immediately.'
        result, llm, *_ = self.run_engine(replies=(bad, bad))
        t = result['jev_result']['_techmedic']
        self.assertEqual((llm.c, t['response_correction_status']), (2, 'failed_safe'))
        self.assertNotIn('fully verified', result['assistant_text'])
        self.assertIn('Verify', result['assistant_text'])
        self.assertNotIn('pip install', result['assistant_text'])

    def test_B2b_ready_but_verify_action_fallback_must_not_install(self):
        state = established()
        state['remediation']['selection_ready'] = True
        state['remediation']['blocking_requirements'] = []
        state['remediation']['summary'] = 'Vetted wheel available, but effective action is compatibility check'
        state['remediation']['install_command'] = valid_delta()['remediation']['install_command']
        bad = '### Next step\npython -m pip install --force-reinstall torch==2.14.0+cu126 --index-url https://download.pytorch.org/whl/cu126'
        result, llm, *_ = self.run_engine(state=state, jev=FakeJev(action='verify_compatibility'),
                                           replies=(bad, bad))
        t = result['jev_result']['_techmedic']
        self.assertEqual(t['effective_next_action'], 'verify_compatibility')
        self.assertEqual((llm.c, t['response_correction_status']), (2, 'failed_safe'))
        self.assertNotIn('pip install', result['assistant_text'])
        self.assertIn('compatibility', result['assistant_text'].lower())

    def test_B3_terminal_safe_closing_note_not_flagged(self):
        state = established(terminal=True)
        safe = '### Resolution verified\nDo not reinstall the package or run a new diagnostic test.'
        self.assertEqual(response_issues(safe, state, 'finish_diagnosis'), [])

    def test_B4_protective_warning_does_not_trigger_false_alarm(self):
        state = established(television=True)
        safe = 'For safety, do not open the chassis; never measure high voltage. Contact service.'
        self.assertEqual(response_issues(safe, state, 'escalate'), [])

    def test_B3_terminal_response_must_not_reopen_diagnostics(self):
        state = established(terminal=True)
        bad = '### Next step\nRestart troubleshooting from scratch and run a new diagnostic test.'
        good = '### Resolution verified\nSynthetic tensor test succeeded; no further troubleshooting is needed.'
        result, llm, *_ = self.run_engine(state=state, jev=FakeJev(action='run_diagnostic_test', terminal=True),
                                           replies=(bad, good))
        t = result['jev_result']['_techmedic']
        self.assertEqual(t['effective_status'], 'resolution_verified')
        self.assertEqual(t['effective_next_action'], 'finish_diagnosis')
        self.assertEqual(t['response_correction_status'], 'accepted')
        self.assertEqual(llm.c, 2)
        self.assertNotIn('Restart troubleshooting', result['assistant_text'])

    def test_B3_second_terminal_contradiction_must_fall_back_to_closure(self):
        state = established(terminal=True)
        bad = 'Start over: run a new diagnostic test; reinstall the package.'
        result, llm, *_ = self.run_engine(state=state, jev=FakeJev(action='run_diagnostic_test', terminal=True),
                                           replies=(bad, bad))
        t = result['jev_result']['_techmedic']
        self.assertEqual((llm.c, t['response_correction_status']), (2, 'failed_safe'))
        self.assertNotIn('reinstall', result['assistant_text'].lower())
        self.assertIn('verified', result['assistant_text'].lower())

    def test_B4_escalation_unsafe_TV_response_corrected(self):
        state = established(television=True)
        bad = '### Next step\nOpen the TV and measure high voltage inside the power supply.'
        good = '### Next step\nStop using the TV if hazardous. Contact a qualified service technician; do not open the chassis.'
        result, llm, *_ = self.run_engine(state=state, jev=FakeJev(action='escalate', tv=True),
                                           replies=(bad, good))
        t = result['jev_result']['_techmedic']
        self.assertEqual(t['effective_status'], 'diagnosis_established')
        self.assertEqual(t['effective_next_action'], 'escalate')
        self.assertEqual(t['response_correction_status'], 'accepted')
        self.assertEqual(llm.c, 2)
        self.assertNotIn('measure high voltage', result['assistant_text'].lower())

    def test_B4_two_unsafe_TV_responses_fall_back_to_service(self):
        state = established(television=True)
        bad = 'Remove the rear TV cover and perform high-voltage measurements inside.'
        result, llm, *_ = self.run_engine(state=state, jev=FakeJev(action='escalate', tv=True),
                                           replies=(bad, bad))
        t = result['jev_result']['_techmedic']
        self.assertEqual((llm.c, t['response_correction_status']), (2, 'failed_safe'))
        self.assertIn('service', result['assistant_text'].lower())
        self.assertNotIn('perform high-voltage measurements', result['assistant_text'].lower())


if __name__ == '__main__':
    unittest.main()
