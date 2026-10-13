"""Deterministic offline fixtures for isolated candidate testing (no network)."""
from __future__ import annotations
from .models import normalize_diagnostic_state
from .jev import JevError

class FakeLLM:
    def __init__(self, fail_llm=False):
        self.fail_llm=fail_llm
        self.last_update_state_time_ms=0.1
        self.last_integrate_research_time_ms=0.0
        self.last_compose_response_time_ms=0.1
    def update_state(self,*,latest_user_text,previous_state,case_context):
        if self.fail_llm or 'Q2_FAKE_LLM_FAILURE' in latest_user_text:
            raise RuntimeError('Q2SyntheticLLMFailure')
        passed='Q2_RETEST_PASSED' in latest_user_text
        v={'case_summary':'Q2 synthetic diagnostic fixture',
           'device': {'type':'synthetic device','manufacturer':'Unknown','model':'Unknown','operating_system':'Unknown'},
           'symptoms':['Fixture malfunction under test'],
           'observations':['Synthetic fixture observation was supplied'],
           'diagnosis': {'summary':'Controlled synthetic cause (not a real diagnosis)',
                         'basis':['Synthetic test response; no real device inspected']},
           'remediation':{'summary':'Synthetic configuration correction only',
                          'selection_ready':True,'blocking_requirements':[],
                          'requirements':['No real changes authorized']},
           'resolution_verification':{'verified':passed,'evidence':['Synthetic explicit retest'] if passed else [],
             'post_change_checks':([{'original_symptom':'Fixture malfunction under test',
               'post_change':True,'retested_original_symptom':True,'result':'passed',
               'source_type':'user_observation','observation':'Q2_RETEST_PASSED marker supplied in synthetic test'}]
               if passed else [])},
           'status':'resolution_verified' if passed else 'diagnosis_established'}
        return normalize_diagnostic_state(v)
    def compose_response(self,*,diagnostic_state,jev_result,safety,research_result=None):
        if diagnostic_state['status']=='resolution_verified':
            return ('### Resolution verified\nA SYNTHETIC post-change retest was recorded. '
                    'This is not a real device diagnosis.\n')
        return ('### Current assessment\nSynthetic diagnostic fixture only. '
                'No actual repair has been performed.\n\n### Next step\n'
                'Perform and document a post-change verification test.\n')

class FakeJev:
    def evaluate(self,state):
        if state.get('candidate_fake_jev_failure'):
            raise JevError('Q2SyntheticJevFailure')
        return {'answers':{
            'fault_domain':{'type':'choice','choice':'application','confidence':0.8},
            'evidence_sufficient':{'type':'noul','noul':0.9},
            'diagnosis_established':{'type':'noul','noul':0.92},
            'remediation_identified':{'type':'noul','noul':0.82},
            'resolution_verified':{'type':'noul','noul':0.97},
            'hardware_failure_likely':{'type':'noul','noul':0.02},
            'professional_service_needed':{'type':'noul','noul':0.05},
            'urgency':{'type':'score','score':0.1},
            'next_action':{'type':'choice','choice':'verify_resolution','confidence':0.86}},
            '_techmedic':{'jev_response_time_ms':0.1}}

class FakeResearch:
    def research(self,*,request,diagnostic_state):
        return {'performed':False,'brief':'','sources':[],'citations':[],'error':'',
                '_techmedic':{'research_response_time_ms':0.0}}


def make_fake_engine(db, *, fail_jev=False, fail_llm=False):
    from .diagnostic_engine import DiagnosticEngine
    e=object.__new__(DiagnosticEngine)
    e.db_path=db;e.llm=FakeLLM(fail_llm=fail_llm);e.jev=FakeJev();e.research=FakeResearch()
    if fail_jev:
        # Explicitly isolated per-instance; no monkeypatch of global Jev client.
        orig=e.jev.evaluate
        def fail_once(state):
            return orig(dict(state,candidate_fake_jev_failure=True))
        e.jev.evaluate=fail_once
    return e
