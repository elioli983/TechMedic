"""Focused v1.5.4 regression tests: delta, fallback, response/action agreement."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from techmedic.consistency import installation_command_error, remediation_readiness, response_issues
from techmedic.diagnostic_engine import DiagnosticEngine
from techmedic.models import normalize_diagnostic_state
from techmedic.research_delta import integrate_research_delta_safely, safe_preview
from techmedic.status import derive_effective_next_action
from techmedic import database


def previous():
    return normalize_diagnostic_state({
        'case_summary': 'PyTorch GTX 1080 CUDA unavailable after CPU-only install',
        'device': {'operating_system': 'Windows 11', 'model': 'GTX 1080', 'application': 'PyTorch'},
        'observations': ['torch.__version__ 2.14.0+cpu', 'CUDA unavailable'],
        'tests_performed': [{'test': 'torch runtime', 'result': '2.14.0+cpu'}],
        'diagnosis': {'summary': 'CPU-only torch cannot use CUDA', 'basis': ['2.14.0+cpu', 'torch.version.cuda=None']},
        'remediation': {'summary': 'Replace CPU-only build', 'selection_ready': False,
                        'blocking_requirements': ['Verify compatible CUDA wheel']},
        'status': 'remediation_identified',
    })


def research():
    return {'performed': True, 'category': 'compatibility', 'query': 'GTX 1080 CUDA 12.6',
            'brief': 'Official index lists wheel and official source lists Pascal support',
            'sources': [{'id': 'R1', 'primary_source': True, 'cited_in_research': True,
                         'url': 'https://download.pytorch.org/whl/cu126/torch/',
                         'title': 'Official wheel index'}],
            'citations': [{'source_id': 'R1'}], '_techmedic': {'research_response_time_ms': 8.0}}


def delta(ready=True, command='python -m pip install --force-reinstall "torch==2.14.0+cu126" --index-url https://download.pytorch.org/whl/cu126'):
    return {'format': 'research_delta_v1',
            'research_evidence': {'summary': 'Official index and build metadata support a trial installation',
                                  'source_ids': ['R1'], 'category': 'compatibility', 'query': 'GTX 1080 CUDA 12.6'},
            'remediation': {'summary': 'Replace CPU-only build with CUDA-specific wheel',
                            'requirements': ['Verify by executing tensor on GPU after install'],
                            'selection_ready': ready,
                            'blocking_requirements': [] if ready else ['Exact wheel unsupported'],
                            'install_command': command if ready else '',
                            'verification_commands': ['python -c "import torch; print(torch.__version__,torch.cuda.is_available())"',
                                                      'python -c "import torch; print(torch.cuda.get_device_name(0))"'],
                            'confidence_note': 'Build metadata is not proof of local runtime success'},
            'research_request': {'needed': False, 'category': 'compatibility', 'query': '', 'reason': ''}}


class V154DeltaTests(unittest.TestCase):
    def test_accept_delta_preserves_device_observations_and_diagnosis(self):
        before = previous()
        after, audit = integrate_research_delta_safely(before, delta(), research())
        self.assertEqual(audit['status'], 'accepted')
        for k in ('device', 'diagnosis', 'observations', 'tests_performed', 'resolution_verification', 'status'):
            self.assertEqual(before[k], after[k])
        self.assertTrue(after['remediation']['selection_ready'])
        self.assertEqual(after['research_evidence']['source_ids'], ['R1'])

    def test_rejects_delta_that_modifies_local_observations(self):
        d = delta(); d['observations'] = []
        after, audit = integrate_research_delta_safely(previous(), d, research())
        self.assertTrue(audit['fallback_used'])
        self.assertEqual(after['observations'], previous()['observations'])

    def test_reject_unknown_source_id(self):
        d = delta(); d['research_evidence']['source_ids'] = ['R99']
        self.assertEqual(integrate_research_delta_safely(previous(), d, research())[1]['status'], 'rejected')

    def test_no_ready_remediation_while_blockers_exist(self):
        d = delta(); d['remediation']['blocking_requirements'] = ['GPU support unknown']
        self.assertEqual(integrate_research_delta_safely(previous(), d, research())[1]['status'], 'rejected')

    def test_reject_same_public_version_without_replacement(self):
        d = delta(command='python -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cu126')
        self.assertEqual(integrate_research_delta_safely(previous(), d, research())[1]['status'], 'rejected')

    def test_accept_explicit_local_cuda_variant_and_force(self):
        self.assertFalse(installation_command_error(delta()['remediation']['install_command'], previous()))

    def test_reject_unsafe_chained_shell_command(self):
        d = delta(command='python -m pip install torch==2.14.0+cu126; Remove-Item -Recurse C:\\')
        self.assertEqual(integrate_research_delta_safely(previous(), d, research())[1]['status'], 'rejected')

    def test_lifecycle_retained_but_current_readiness_blocked(self):
        r = remediation_readiness(previous())
        self.assertEqual(r['historical_lifecycle'], 'remediation_identified')
        self.assertFalse(r['ready'])
        result = {'answers': {'next_action': {'choice': 'recommend_software_repair'}}}
        self.assertEqual(derive_effective_next_action(previous(), result, 'remediation_identified'), 'collect_system_information')

    def test_detect_false_claim_compatibility_verified(self):
        self.assertTrue(response_issues('Compatibility is verified.', previous(), 'verify_compatibility'))

    def test_detect_missing_command_when_user_requests_it(self):
        after, _ = integrate_research_delta_safely(previous(), delta(), research())
        self.assertTrue(response_issues('Please reply proceed.', after, 'recommend_software_repair', requested_command=True))

    def test_preview_scrubs_api_keys(self):
        text = safe_preview({'bad': 'Bearer abcdef123', 'key': 'sk-' + 'q'*20})['rejected_candidate_preview']
        self.assertNotIn('abcdef123', text)
        self.assertNotIn('sk-', text)


class FakeLLM:
    def __init__(self, *, good_second=True, bad_response=False):
        self.good_second = good_second
        self.bad_response = bad_response
        self.last_update_state_time_ms = 10.0
        self.last_integrate_research_time_ms = 11.0
        self.last_compose_response_time_ms = 5.0
        self.integrated = 0
        self.composed = 0

    def update_state(self, **kwargs):
        return previous()

    def integrate_research(self, **kwargs):
        self.integrated += 1
        return {'unexpected': 'not a valid diagnostic state or delta'}

    def repair_research_delta(self, **kwargs):
        self.integrated += 1
        return delta() if self.good_second else {'unexpected': 'still invalid'}

    def compose_response(self, **kwargs):
        self.composed += 1
        return ('Compatibility is verified.' if self.bad_response and self.composed == 1
                else '### Next step\npython -m pip install --force-reinstall "torch==2.14.0+cu126" --index-url https://download.pytorch.org/whl/cu126')


class FakeJev:
    def evaluate(self, state):
        self.latest_state = copy.deepcopy(state)
        return {'answers': {'diagnosis_established': {'noul': .94}, 'remediation_identified': {'noul': .9},
                            'resolution_verified': {'noul': .02},
                            'next_action': {'choice': 'recommend_software_repair', 'confidence': .9}},
                '_techmedic': {'jev_response_time_ms': 3.0}}


class FakeResearch:
    def research(self, **kwargs):
        return research()


class V154WorkflowTests(unittest.TestCase):
    def run_case(self, *, good_second=True, bad_response=False):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        db = Path(t.name) / 'db.sqlite'
        database.init_db(db)
        cid = database.create_case(db, 'PyTorch')
        e = object.__new__(DiagnosticEngine)
        e.db_path = db; e.llm = FakeLLM(good_second=good_second, bad_response=bad_response)
        e.jev = FakeJev(); e.research = FakeResearch()
        result = e.run_cycle(cid, 'Provide exact installation command')
        return e, result, db, cid

    def test_repair_revalidates_delta_and_keeps_diagnosis(self):
        engine, result, db, cid = self.run_case()
        audit = result['research']['_techmedic']['integration_validation']
        self.assertEqual(audit['status'], 'accepted')
        self.assertTrue(audit['recovered_after_retry'])
        self.assertEqual(audit['attempt_count'], 2)
        self.assertEqual(result['diagnostic_state']['diagnosis']['summary'], previous()['diagnosis']['summary'])
        self.assertTrue(result['jev_result']['_techmedic']['current_remediation_ready'])
        self.assertEqual(len(database.get_turns(db, cid)), 1)

    def test_second_rejection_keeps_repair_gate_closed(self):
        engine, result, db, cid = self.run_case(good_second=False)
        audit = result['research']['_techmedic']['integration_validation']
        self.assertEqual(audit['status'], 'rejected')
        self.assertEqual(audit['attempt_count'], 2)
        self.assertFalse(result['jev_result']['_techmedic']['current_remediation_ready'])
        self.assertEqual(result['jev_result']['_techmedic']['effective_next_action'], 'collect_system_information')
        self.assertTrue(result['diagnostic_state']['diagnosis']['summary'])

    def test_response_correction_attempted_and_accepted(self):
        engine, result, *_ = self.run_case(bad_response=True)
        meta = result['jev_result']['_techmedic']
        self.assertEqual(engine.llm.composed, 2)
        self.assertEqual(meta['response_correction_status'], 'accepted')
        self.assertNotIn('Compatibility is verified.', result['assistant_text'])


if __name__ == '__main__':
    unittest.main()
