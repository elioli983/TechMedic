"""Regression coverage for the four development/evaluation fixes."""
import concurrent.futures
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import zipfile
from cryptography.fernet import Fernet
from techmedic import candidate_journal as j, database
from techmedic.candidate_fakes import make_fake_engine
from techmedic.jev import JevClient, JevError, resolve_jev_endpoint
from techmedic.windows_startup import instance_lock, load_journal_key, StartupError
from techmedic.export_bundle import build_diagnostic_bundle

class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root/'test.sqlcipher'
        env = patch.dict(os.environ, {'TECHMEDIC_CANDIDATE_JOURNAL_KEY':Fernet.generate_key().decode()})
        env.start(); self.addCleanup(env.stop)

class LeaseTests(Fixture):
    def setUp(self):
        super().setUp()
        j.ensure(self.db)
        self.cid=database.create_case(self.db,'SYNTHETIC')
        j.capture(self.db,self.cid,'s','FICTIONAL input')
    def slow_engine(self,seconds):
        engine=make_fake_engine(self.db); original=engine.run_cycle
        def slow(*args,**kwargs):
            time.sleep(seconds)
            return original(*args,**kwargs)
        engine.run_cycle=slow
        return engine
    def test_real_renewal_occurs_and_long_turn_commits_once(self):
        with patch.object(j,'LEASE_SECONDS',.6), patch.object(j,'renew_lease',wraps=j.renew_lease) as renew:
            result=j.process(self.db,self.cid,'s',self.slow_engine(1.3))
        self.assertGreaterEqual(renew.call_count,2)
        self.assertEqual(result['disposition'],'completed')
        self.assertEqual(len(database.get_turns(self.db,self.cid)),1)
    def test_failed_renewal_fences_completion(self):
        with patch.object(j,'LEASE_SECONDS',.3), patch.object(j,'renew_lease',return_value=False) as renew:
            result=j.process(self.db,self.cid,'s',self.slow_engine(.6))
        self.assertGreater(renew.call_count,0)
        self.assertEqual(result['disposition'],'stale')
        self.assertEqual(database.get_turns(self.db,self.cid),[])
        self.assertEqual(j.get_pending_text(self.db,self.cid,'s'),'FICTIONAL input')
    def test_busy_database_expiry_is_checked_after_lock_wait(self):
        with patch.object(j,'LEASE_SECONDS',.3):
            claim=j.claim(self.db,self.cid,'s')
        waiting=threading.Event()
        def complete():
            waiting.set()
            return j.atomic_complete(self.db,self.cid,'s',claim['owner'],claim['fence'],now=None,
                user_text='FICTIONAL input',diagnostic_state={},jev_result={},safety={},
                assistant_text='answer',research={},case_changes={})
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with database._connect(self.db) as blocker:
                blocker.execute('BEGIN IMMEDIATE')
                future=pool.submit(complete)
                self.assertTrue(waiting.wait(2))
                time.sleep(.5)
            with self.assertRaises(j.SubmissionError): future.result(timeout=5)
        self.assertEqual(database.get_turns(self.db,self.cid),[])
    def test_explicit_test_clock_remains_supported(self):
        with patch.object(j,'renew_lease') as renew:
            result=j.process(self.db,self.cid,'s',make_fake_engine(self.db),now=100)
        self.assertEqual(result['disposition'],'completed')
        renew.assert_not_called()

class HttpsTests(unittest.TestCase):
    def test_reject_insecure_or_malformed_endpoints_before_request(self):
        for endpoint in ['http://example.com/api','ftp://example.com','https://',
                         'https://user:secret@example.com','https://example.com/#fragment',
                         'https://example.com:bad','https://example.com/a b']:
            with self.subTest(endpoint=endpoint),patch('techmedic.jev.requests.post') as post:
                with self.assertRaises(JevError): JevClient('FAKE',endpoint=endpoint)
                post.assert_not_called()
    def test_https_custom_endpoint_supported(self):
        self.assertEqual(resolve_jev_endpoint('FAKE','https://example.com/api/'),'https://example.com/api')
    def test_revalidate_mutated_endpoint(self):
        client=JevClient('FAKE');client.endpoint='http://example.com'
        with patch('techmedic.jev.requests.post') as post:
            with self.assertRaises(JevError):client._post({})
            post.assert_not_called()
    def test_redirects_never_followed(self):
        for status in [301,302,303,307,308]:
            response=Mock(status_code=status,headers={'Location':'http://example.com'})
            with patch('techmedic.jev.requests.post',return_value=response) as post:
                with self.assertRaises(JevError):JevClient('FAKE')._post({})
                self.assertFalse(post.call_args.kwargs['allow_redirects'])
        with patch('techmedic.jev.requests.get',return_value=response) as get:
            with self.assertRaises(JevError):JevClient('FAKE').get_models()
            self.assertFalse(get.call_args.kwargs['allow_redirects'])

class HistoryTests(Fixture):
    def test_history_windows_and_full_export(self):
        database.init_db(self.db); cid=database.create_case(self.db,'SYNTHETIC')
        with database._connect(self.db) as c:
            for n in range(123):
                c.execute("INSERT INTO turns(case_id,user_text,diagnostic_state_json,jev_result_json,safety_json,assistant_text,created_at) VALUES(?,?,?,?,?,?,?)",(cid,str(n),'{}','{}','{}','answer','now'))
        recent=database.get_turns(self.db,cid,limit=50)
        self.assertEqual([x['user_text'] for x in recent],[str(n) for n in range(73,123)])
        full=database.get_turns(self.db,cid)
        with zipfile.ZipFile(io.BytesIO(build_diagnostic_bundle(database.get_case(self.db,cid),full))) as z:
            self.assertEqual(len(json.loads(z.read('09_ALL_TURNS_RAW.json'))),123)
        with self.assertRaises(ValueError):database.get_turns(self.db,cid,limit=0)
    def test_existing_database_gets_sort_index_idempotently(self):
        database.init_db(self.db)
        with database._connect(self.db) as c:c.execute('DROP INDEX idx_cases_updated_at')
        database.init_db(self.db);database.init_db(self.db)
        with database._connect(self.db) as c:
            plan=str([tuple(r) for r in c.execute('EXPLAIN QUERY PLAN SELECT * FROM cases ORDER BY updated_at DESC LIMIT 30')])
        self.assertIn('idx_cases_updated_at',plan)
        self.assertNotIn('TEMP B-TREE',plan)

class StartupTests(Fixture):
    def test_concurrent_key_creation_uses_one_wrapped_key(self):
        path=self.root/'journal-key.dpapi.txt'
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            keys=list(pool.map(lambda _:load_journal_key(path,self.db),range(16)))
        self.assertEqual(len(set(keys)),1)
        self.assertNotIn(keys[0],path.read_text())
        self.assertEqual(list(self.root.glob('*.tmp')),[])
        before=path.read_bytes()
        self.assertEqual(load_journal_key(path,self.db),keys[0])
        self.assertEqual(path.read_bytes(),before)
    def test_missing_and_corrupt_keys_fail_without_replacement(self):
        path=self.root/'journal-key.dpapi.txt';self.db.write_bytes(b'existing')
        with self.assertRaises(StartupError):load_journal_key(path,self.db)
        self.assertFalse(path.exists())
        path.write_text('invalid blob')
        with self.assertRaises(StartupError):load_journal_key(path,self.db)
        self.assertEqual(path.read_text(),'invalid blob')
    def test_powerShell_key_compatibility_both_directions(self):
        path=self.root/'journal-key.dpapi.txt'
        script = "$k=$env:TM_TEST_KEY; ConvertTo-SecureString -String $k -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -LiteralPath $env:TM_TEST_PATH -Encoding Ascii"
        key=Fernet.generate_key().decode()
        env={k:v for k,v in os.environ.items() if k.lower() != 'psmodulepath'}
        env.update(TM_TEST_KEY=key,TM_TEST_PATH=str(path))
        subprocess.run(['powershell.exe','-NoProfile','-Command',script],env=env,check=True,capture_output=True)
        self.assertEqual(load_journal_key(path,self.db),key)
        path.unlink()
        env['TM_TEST_KEY']=load_journal_key(path,self.db)
        script = "$s=ConvertTo-SecureString ((Get-Content -LiteralPath $env:TM_TEST_PATH -Raw).Trim()); $c=New-Object System.Management.Automation.PSCredential ('test',$s); if ($c.GetNetworkCredential().Password -ne $env:TM_TEST_KEY) { exit 1 }"
        subprocess.run(['powershell.exe','-NoProfile','-Command',script],env=env,check=True,capture_output=True)
    def test_process_lock_released_after_forced_exit(self):
        lock=self.root/'instance.lock'
        code="from pathlib import Path; import sys,time; from techmedic.windows_startup import instance_lock; lock=instance_lock(Path(sys.argv[1])); lock.__enter__(); print('ready',flush=True); time.sleep(60)"
        child=subprocess.Popen([sys.executable,'-c',code,str(lock)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            with self.assertRaises(StartupError):
                with instance_lock(lock):pass
        finally:
            child.terminate();child.communicate(timeout=10)
        with instance_lock(lock):pass
    def test_launcher_holds_lock_through_server_and_sets_live_gate(self):
        from techmedic import windows_startup as startup
        from streamlit.web import cli
        root=self.root/'application'
        keydir=self.root/'profile'/'TechMedic'/'v1.5.6'
        def fake_server():
            self.assertEqual(os.environ.get('TECHMEDIC_V156_ALLOW_LIVE'),'I_ACCEPT_LIVE_API_CALLS')
            self.assertIn('TECHMEDIC_CANDIDATE_JOURNAL_KEY',os.environ)
            self.assertIn('127.0.0.1',sys.argv)
            with self.assertRaises(StartupError):
                with instance_lock(keydir/'sqlcipher-application.lock'):pass
        with patch.object(startup,'__file__',str(root/'techmedic'/'windows_startup.py')), patch.dict(os.environ,{'LOCALAPPDATA':str(self.root/'profile')}), patch.object(sys,'argv',['launcher','--live']), patch.object(cli,'main',side_effect=fake_server):
            startup.main()
            self.assertNotIn('TECHMEDIC_CANDIDATE_JOURNAL_KEY',os.environ)
        with instance_lock(keydir/'sqlcipher-application.lock'):pass
    def test_offline_launcher_clears_live_gate_and_unlocks_on_server_error(self):
        from techmedic import windows_startup as startup
        from streamlit.web import cli
        keydir=self.root/'profile'/'TechMedic'/'v1.5.6'
        def failed_server():
            self.assertNotIn('TECHMEDIC_V156_ALLOW_LIVE',os.environ)
            raise RuntimeError('synthetic server failure')
        with patch.object(startup,'__file__',str(self.root/'app'/'techmedic'/'windows_startup.py')), patch.dict(os.environ,{'LOCALAPPDATA':str(self.root/'profile'),'TECHMEDIC_V156_ALLOW_LIVE':'I_ACCEPT_LIVE_API_CALLS'}), patch.object(sys,'argv',['launcher']), patch.object(cli,'main',side_effect=failed_server):
            with self.assertRaises(RuntimeError):startup.main()
            self.assertNotIn('TECHMEDIC_CANDIDATE_JOURNAL_KEY',os.environ)
        with instance_lock(keydir/'sqlcipher-application.lock'):pass

    def test_lock_released_after_exception(self):
        lock=self.root/'instance.lock'
        with self.assertRaises(RuntimeError):
            with instance_lock(lock):raise RuntimeError('synthetic')
        with instance_lock(lock):pass

if __name__=='__main__':unittest.main()
