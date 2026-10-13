"""Supplemental, offline-only TechMedic v1.5.4 fault-injection tests.

Run within TechMedic_v1.5.4 project: python -m unittest discover -s validation_addon -v
This file never uses actual OpenAI/Jev requests or changes production code.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from techmedic import database
from techmedic.diagnostic_engine import DiagnosticEngine
from techmedic.models import normalize_diagnostic_state
from techmedic.research_delta import integrate_research_delta_safely
from techmedic.consistency import response_issues


def state(*, title, os_name, status, diagnosis='', basis=None, remedy='', ready=False, blocked=None,
          resolved=False, verification=None, candidates=None, observations=None):
    return normalize_diagnostic_state({
        'case_summary': title,
        'device': {'operating_system': os_name, 'model': 'Synthetic test fixture'},
        'observations': observations or [],
        'tests_performed': [{'test': 'Synthetic fixture', 'result': x} for x in (observations or [])],
        'diagnosis': {'summary': diagnosis, 'basis': basis or []},
        'remediation': {'summary': remedy, 'selection_ready': ready,
                        'blocking_requirements': blocked or []},
        'resolution_verification': {'verified': resolved, 'evidence': verification or []},
        'candidate_next_tests': candidates or [],
        'research_request': {'needed': False, 'category': '', 'query': '', 'reason': ''},
        'status': status,
    })


def jev(diag, remedy, resolve, action):
    return {'answers': {'diagnosis_established': {'noul': diag},
                        'remediation_identified': {'noul': remedy},
                        'resolution_verified': {'noul': resolve},
                        'next_action': {'choice': action, 'confidence': 0.8}},
            '_techmedic': {'jev_response_time_ms': 1.0}}


class ScriptedLLM:
    def __init__(self, scripted_states, *, first_response='', always_bad=False):
        self.scripted_states = scripted_states
        self.first_response = first_response
        self.always_bad = always_bad
        self.updates = 0
        self.compose_calls = 0
        self.last_update_state_time_ms = 1.0
        self.last_integrate_research_time_ms = 0.0
        self.last_compose_response_time_ms = 1.0
        self.seen_previous = []

    def update_state(self, **kwargs):
        self.seen_previous.append(copy.deepcopy(kwargs.get('previous_state')))
        r = copy.deepcopy(self.scripted_states[self.updates])
        self.updates += 1
        return r

    def compose_response(self, **kwargs):
        self.compose_calls += 1
        if self.always_bad:
            return 'Compatibility is verified.'
        if self.first_response and self.compose_calls == 1:
            return self.first_response
        action = ((kwargs['jev_result'].get('_techmedic') or {}).get('effective_next_action'))
        if action == 'finish_diagnosis':
            return 'Resolution verified. Diagnosis complete.'
        if action == 'escalate':
            return 'Arrange qualified television service. Do not open the television.'
        return 'Evidence reviewed. Proceed with the selected next diagnostic action.'


class ScriptedJev:
    def __init__(self, answers):
        self.answers = answers
        self.calls = 0
        self.seen = []
    def evaluate(self, st):
        self.seen.append(copy.deepcopy(st))
        r = copy.deepcopy(self.answers[self.calls])
        self.calls += 1
        return r


class NoResearch:
    def __init__(self): self.calls = 0
    def research(self, **kwargs):
        self.calls += 1
        return {'performed': False, 'category': '', 'query': '',
                'sources': [], 'citations': [], 'skipped_reason': 'Not requested'}


class CrossDomainTests(unittest.TestCase):
    def engine(self, states, decisions, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dbpath = Path(tmp.name) / 'techmedic.sqlite3'
        database.init_db(dbpath)
        case_id = database.create_case(dbpath, 'Synthetic regression fixture')
        engine = object.__new__(DiagnosticEngine)
        engine.db_path = dbpath
        engine.llm = ScriptedLLM(states, **kw)
        engine.jev = ScriptedJev(decisions)
        engine.research = NoResearch()
        return engine, case_id, dbpath

    def test_network_investigation_diagnosis_remediation_verification(self):
        states = [
            state(title='Network DNS problem', os_name='Windows 11', status='investigating',
                  observations=['Wi-Fi connected; ping 8.8.8.8 succeeds']),
            state(title='Network DNS problem', os_name='Windows 11', status='diagnosis_established',
                  diagnosis='DNS lookups via 192.168.1.1 fail',
                  basis=['Default DNS lookup timed out', 'Public DNS lookup succeeded'],
                  blocked=['Confirm corrective DNS route'], observations=['192.168.1.1 timeout', '1.1.1.1 works']),
            state(title='Network DNS problem', os_name='Windows 11', status='remediation_identified',
                  diagnosis='DNS lookups via 192.168.1.1 fail',
                  basis=['Configured resolver timed out', 'Public resolver succeeded'],
                  remedy='Change DNS resolver to a verified working address', ready=True,
                  observations=['Reversible DNS change selected']),
            state(title='Network DNS problem', os_name='Windows 11', status='resolution_verified',
                  diagnosis='DNS lookups via 192.168.1.1 were failing',
                  basis=['Default resolver failed', 'Public resolver worked'],
                  remedy='Changed DNS configuration', ready=True, resolved=True,
                  verification=['Websites now load', 'Default DNS lookup succeeds']),
        ]
        decisions = [jev(.08,.04,.01,'run_diagnostic_test'),
                     jev(.92,.10,.02,'verify_compatibility'),
                     jev(.93,.86,.02,'recommend_configuration_change'),
                     jev(.96,.84,.96,'ask_for_information')]
        engine, case_id, db = self.engine(states, decisions)
        results = [engine.run_cycle(case_id, f'Network simulated turn {n}') for n in range(4)]
        self.assertEqual([r['diagnostic_state']['status'] for r in results],
                         ['investigating', 'diagnosis_established', 'remediation_identified', 'resolution_verified'])
        self.assertEqual(results[-1]['jev_result']['_techmedic']['raw_next_action'], 'ask_for_information')
        self.assertEqual(results[-1]['jev_result']['_techmedic']['effective_next_action'], 'finish_diagnosis')
        self.assertEqual(engine.research.calls, 4)
        self.assertTrue(all(not r['research']['performed'] for r in results))
        self.assertEqual(len(database.get_turns(db, case_id)), 4)
        self.assertEqual(database.get_case(db,case_id)['operating_system'], 'Windows 11')
        self.assertEqual(engine.llm.seen_previous[1]['status'], 'investigating')
        self.assertEqual(engine.llm.seen_previous[3]['status'], 'remediation_identified')

    def test_tv_lifecycle_escalation_is_action_not_state_and_safety_flagged(self):
        states = [
            state(title='Television dark screen with sound', os_name='', status='investigating',
                  observations=['Sound continues; picture dark']),
            state(title='Television dark screen with sound', os_name='', status='diagnosis_established',
                  diagnosis='Internal display illumination path is failing',
                  basis=['Flashlight reveals faint moving picture', 'Sound and controls work when dark'],
                  blocked=['No safe user-serviceable correction established'],
                  candidates=[{'name': 'unsafe candidate',
                               'instructions': 'Open the power supply and measure mains voltage',
                               'purpose': 'Synthetic safety regression'}],
                  observations=['Flashlight shows silhouettes', 'Audio remains working']),
        ]
        decisions = [jev(.11,.03,.02,'collect_system_information'), jev(.91,.31,.01,'escalate')]
        engine, case_id, db = self.engine(states, decisions)
        engine.run_cycle(case_id,'TV symptom fixture')
        second=engine.run_cycle(case_id,'TV flashlight fixture')
        self.assertEqual(second['diagnostic_state']['status'], 'diagnosis_established')
        self.assertEqual(second['jev_result']['_techmedic']['effective_next_action'], 'escalate')
        self.assertTrue(second['safety']['blocked'])
        self.assertEqual(second['safety']['risk_level'], 'high')
        self.assertIn('Do not open the television.', second['assistant_text'])
        self.assertEqual(len(database.get_turns(db,case_id)),2)

    def test_response_retry_exhaustion_falls_back_without_unverified_claim(self):
        # A cross-domain response erroneously says 'compatibility is verified'
        # despite explicitly incomplete preconditions; both attempts fail.
        blocked_dns=state(title='DNS scenario', os_name='Windows 11', status='diagnosis_established',
                          diagnosis='Router DNS resolution path fails', basis=['Timeout on router', 'Direct lookup succeeds'],
                          remedy='Change resolver only after checking policy', ready=False,
                          blocked=['Network policy approval not yet obtained'])
        engine, case_id, _=self.engine([blocked_dns], [jev(.93,.03,.01,'verify_compatibility')],always_bad=True)
        result=engine.run_cycle(case_id,'Check compatibility; no change authorized')
        meta=result['jev_result']['_techmedic']
        self.assertEqual(meta['response_correction_status'], 'failed_safe')
        self.assertTrue(meta['responder_consistency_initial_issues'])
        self.assertEqual(engine.llm.compose_calls,2)
        self.assertNotIn('Compatibility is verified.',result['assistant_text'])
        self.assertIn('Network policy approval not yet obtained',result['assistant_text'])
        self.assertFalse(meta['current_remediation_ready'])

    def test_malformed_research_delta_rejection_keeps_tv_evidence(self):
        pre=state(title='Dark-screen TV',os_name='',status='diagnosis_established',
                  diagnosis='Display illumination path likely failed',
                  basis=['Flashlight image', 'Audio works'],
                  observations=['Flashlight showed motion', 'Sound continues'],
                  blocked=['Seek qualified service'])
        bad={'format':'research_delta_v1','observations':[],
             'research_evidence':{'summary':'No primary source linked', 'source_ids':['R99'], 'category':'manufacturer_support','query':'TV'},
             'remediation':{'summary':'Open the TV', 'requirements':[], 'selection_ready':True, 'blocking_requirements':[]},
             'research_request':{'needed':False,'category':'','query':'','reason':''}}
        after,audit=integrate_research_delta_safely(pre,bad,{'sources':[]})
        self.assertEqual(audit['status'],'rejected')
        self.assertTrue(audit['fallback_used'])
        self.assertEqual(after['observations'],pre['observations'])
        self.assertEqual(after['diagnosis'],pre['diagnosis'])
        self.assertTrue(audit['validation_errors'])


if __name__=='__main__':unittest.main()
