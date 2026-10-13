"""Pass 15 integrated-candidate acceptance on disposable SQLite only."""
from __future__ import annotations
import json
# Tests never instantiate a live OpenAI client; a sentinel stub permits isolated
# offline runs without the optional OpenAI SDK installed on the runner.
import sys, types
if 'openai' not in sys.modules:
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        m=types.ModuleType('openai')
        class OfflineOnly:
            def __init__(self,*a,**kw): raise AssertionError('no live OpenAI in offline tests')
        m.OpenAI=OfflineOnly
        sys.modules['openai']=m
import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path
from techmedic import database
from techmedic import candidate_journal as j
from techmedic.candidate_fakes import make_fake_engine
from techmedic.candidate_handoff import build_handoff
from techmedic.candidate_context import candidate_active
from techmedic import models, status
from techmedic.jev import JevClient, JevError
from techmedic.export_bundle import build_diagnostic_bundle
from io import BytesIO
from zipfile import ZipFile

class CandidateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='tm_pass15_')
        self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'candidate.sqlite3'
        j.ensure(self.db)
        self.cid=database.create_case(self.db,'Synthetic diagnostic case')

    def submit(self,txt='User test content',sid=None,*,fail=False,rollback=False):
        sid=sid or uuid.uuid4().hex
        j.capture(self.db,self.cid,sid,txt)
        return sid,j.process(self.db,self.cid,sid,make_fake_engine(self.db,fail_jev=fail),inject_rollback=rollback)

    def test_initial_capture_success_and_audit(self):
        txt='Synthetic Δ 文字 🎯\n'+('A'*12000)+'\nEND'
        sid,out=self.submit(txt)
        self.assertEqual(out['disposition'],'completed')
        turns=database.get_turns(self.db,self.cid)
        self.assertEqual(len(turns),1)
        self.assertEqual(turns[0]['user_text'],txt)
        self.assertEqual(j.list_ui(self.db,self.cid)[0]['sha256_utf8'],hashlib.sha256(txt.encode()).hexdigest())

    def test_error_retains_user_input_and_retry(self):
        txt='User text on Jev failure'
        sid,out=self.submit(txt,fail=True)
        self.assertEqual(out['disposition'],'failed')
        self.assertEqual(len(database.get_turns(self.db,self.cid)),0)
        self.assertEqual(j.get_pending_text(self.db,self.cid,sid),txt)
        retry=j.process(self.db,self.cid,sid,make_fake_engine(self.db))
        self.assertEqual(retry['disposition'],'completed')
        self.assertEqual(database.get_turns(self.db,self.cid)[0]['user_text'],txt)
        self.assertEqual(j.process(self.db,self.cid,sid,make_fake_engine(self.db))['disposition'],'completed')
        self.assertEqual(len(database.get_turns(self.db,self.cid)),1)

    def test_llm_exception_recoverable(self):
        sid=uuid.uuid4().hex
        text='Synthetic LLM failure text'
        j.capture(self.db,self.cid,sid,text)
        failed=j.process(self.db,self.cid,sid,make_fake_engine(self.db,fail_llm=True))
        self.assertEqual(failed['disposition'],'failed')
        self.assertEqual(len(database.get_turns(self.db,self.cid)),0)
        self.assertEqual(j.get_pending_text(self.db,self.cid,sid),text)
        self.assertEqual(j.process(self.db,self.cid,sid,make_fake_engine(self.db))['disposition'],'completed')

    def test_atomic_rollback_and_recovery(self):
        sid,out=self.submit('Rollback test',rollback=True)
        self.assertEqual(out['disposition'],'failed')
        self.assertEqual(len(database.get_turns(self.db,self.cid)),0)
        self.assertEqual(database.get_case(self.db,self.cid)['title'],'Synthetic diagnostic case')
        self.assertEqual(j.process(self.db,self.cid,sid,make_fake_engine(self.db))['disposition'],'completed')
        self.assertEqual(len(database.get_turns(self.db,self.cid)),1)

    def test_ordering_prevents_overtake(self):
        sid,out=self.submit('first',fail=True)
        sid2=uuid.uuid4().hex
        j.capture(self.db,self.cid,sid2,'second')
        self.assertEqual(j.process(self.db,self.cid,sid2,make_fake_engine(self.db))['disposition'],'earlier_unfinished')
        j.abandon(self.db,self.cid,sid,confirmed=True)
        self.assertEqual(j.process(self.db,self.cid,sid2,make_fake_engine(self.db))['disposition'],'completed')
        self.assertEqual(len(database.get_turns(self.db,self.cid)),1)

    def test_summary_is_copyable_separate_export(self):
        self.submit('test')
        case=database.get_case(self.db,self.cid)
        turns=database.get_turns(self.db,self.cid)
        summary=build_handoff(case,turns)
        self.assertIn('PROFESSIONAL-SERVICE HANDOFF',summary)
        self.assertIn('not empirically calibrated',summary)
        self.assertIn('No real changes authorized',summary)
        self.assertNotIn('Bearer ',summary)
        blob=build_diagnostic_bundle(case,turns)
        with ZipFile(BytesIO(blob)) as z:
            self.assertIn('MANIFEST.json',z.namelist())

    def test_diagnosis_trace_guard_and_structured_retest(self):
        state=models.normalize_diagnostic_state({'diagnosis':{'summary':'Possible cause'},
          'remediation':{'summary':'Remedy','selection_ready':True},
          'resolution_verification':{'verified':True,'evidence':['changed settings']}})
        jev=make_fake_engine(self.db).jev.evaluate({})
        token=candidate_active.set(True)
        try:
            self.assertIn(status.derive_case_status(state,jev),('investigating','possible_diagnosis'))
            state['diagnosis']['basis']=['Observed test']
            self.assertNotEqual(status.derive_case_status(state,jev),'resolution_verified')
            state['resolution_verification']['post_change_checks']=[{
              'original_symptom':'Original symptom', 'post_change':True,
              'retested_original_symptom':True,'result':'passed',
              'source_type':'user_observation','observation':'Retested and now passes'}]
            self.assertEqual(status.derive_case_status(state,jev),'resolution_verified')
        finally:
            candidate_active.reset(token)

    def test_safe_score_validator_rejects_nonfinite_string_and_bool(self):
        good=make_fake_engine(self.db).jev.evaluate({})
        JevClient._validate_lifecycle_scores(good)
        for bad in (1.1,-0.1,float('nan'),float('inf'),'0.9',True,None):
            result=json.loads(json.dumps(good))
            result['answers']['resolution_verified']['noul']=bad
            with self.subTest(bad=repr(bad)),self.assertRaises(JevError):
                JevClient._validate_lifecycle_scores(result)

    def test_fake_retest_evidence_can_close_synthetically(self):
        self.submit('Initial synthetic problem')
        _,out=self.submit('Q2_RETEST_PASSED: after change, original issue no longer occurs')
        self.assertEqual(out['disposition'],'completed')
        self.assertEqual(database.get_case(self.db,self.cid)['status'],'resolution_verified')
        self.assertEqual(len(database.get_turns(self.db,self.cid)),2)

    def test_invalid_case_duplicate_conflict_and_delete(self):
        sid='my-submission';j.capture(self.db,self.cid,sid,'hello')
        with self.assertRaises(j.SubmissionError):
            j.capture(self.db,self.cid,sid,'other')
        self.assertEqual(j.abandon(self.db,self.cid,sid,confirmed=True),'abandoned')
        database.delete_case(self.db,self.cid)
        self.assertEqual(j.list_ui(self.db,self.cid),[])

    def test_journal_reinit_and_no_raw_ui_text(self):
        sid=uuid.uuid4().hex
        j.capture(self.db,self.cid,sid,'PRIVATE_FIXTURE_NEVER_SHOW')
        j.ensure(self.db)
        public=json.dumps(j.list_ui(self.db,self.cid))
        self.assertNotIn('PRIVATE_FIXTURE_NEVER_SHOW',public)

    def test_unverified_responder_false_closure_is_detected(self):
        from techmedic.candidate_response_guard import unsupported_closure
        self.assertTrue(unsupported_closure('The issue is resolved. You are done.', 'remediation_identified'))
        self.assertFalse(unsupported_closure('The issue is not resolved.', 'remediation_identified'))
        self.assertFalse(unsupported_closure('The issue is resolved.', 'resolution_verified'))

    def test_original_regression_context_off_by_default(self):
        self.assertFalse(candidate_active.get())
        state=models.normalize_diagnostic_state({'resolution_verification':{'verified':False}})
        self.assertEqual(state['resolution_verification'],{'verified':False,'evidence':[]})

if __name__=='__main__':unittest.main()
