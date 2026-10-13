"""Focused hardening-only tests; real API calls are forbidden."""
from __future__ import annotations
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
import sys, types
try:
    from openai import OpenAI  # noqa: F401
except ImportError:
    stub=types.ModuleType('openai')
    class OfflineOnly:
        def __init__(self,*a,**kw): raise AssertionError('No live OpenAI allowed in hardening tests')
    stub.OpenAI=OfflineOnly
    sys.modules['openai']=stub
from cryptography.fernet import Fernet
from techmedic import candidate_journal as j, journal_crypto, database
from techmedic.candidate_fakes import make_fake_engine
from hardening_migrate_copy import migrate_copy, create_synthetic_legacy

class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.old_key = os.environ.get(journal_crypto.KEY_ENV)
        self.key = Fernet.generate_key().decode()
        os.environ[journal_crypto.KEY_ENV] = self.key
        self.addCleanup(self._restore)
        tmp=tempfile.TemporaryDirectory(prefix='tm_hardening_')
        self.addCleanup(tmp.cleanup)
        self.tmp=Path(tmp.name)
        self.db=self.tmp/'candidate.sqlite3'
        j.ensure(self.db)
        self.case=database.create_case(self.db,'SYNTHETIC protected candidate case')
    def _restore(self):
        if self.old_key is None:os.environ.pop(journal_crypto.KEY_ENV,None)
        else:os.environ[journal_crypto.KEY_ENV]=self.old_key
    def test_pending_cipher_only_and_exact_recovery(self):
        txt='Sensitive placeholder FICTION Δ / END_MARKER'
        j.capture(self.db,self.case,'s1',txt)
        with database._connect(self.db) as c:
            r=c.execute('SELECT * FROM candidate_submissions').fetchone()
            self.assertEqual(r['user_text'],'')
            self.assertEqual(r['input_bytes'],len(txt.encode('utf-8')))
            self.assertNotIn(txt.encode('utf-8'),r['ciphertext'])
            self.assertNotIn(txt.encode('utf-8'),self.db.read_bytes())
        self.assertEqual(j.get_pending_text(self.db,self.case,'s1'),txt)
    def test_wrong_key_fails_closed_and_restores(self):
        j.capture(self.db,self.case,'s1','ORIGINAL INPUT')
        os.environ[journal_crypto.KEY_ENV]=Fernet.generate_key().decode()
        with self.assertRaises(journal_crypto.JournalKeyError):
            j.get_pending_text(self.db,self.case,'s1')
        os.environ[journal_crypto.KEY_ENV]=self.key
        self.assertEqual(j.get_pending_text(self.db,self.case,'s1'),'ORIGINAL INPUT')
    def test_complete_scrubs_duplicate_cipher_and_preserves_turn(self):
        txt='Input should appear once in the canonical history'
        j.capture(self.db,self.case,'s1',txt)
        out=j.process(self.db,self.case,'s1',make_fake_engine(self.db))
        self.assertEqual(out['disposition'],'completed')
        self.assertEqual(database.get_turns(self.db,self.case)[0]['user_text'],txt)
        with database._connect(self.db) as c:
            r=c.execute('SELECT user_text,ciphertext FROM candidate_submissions').fetchone()
            self.assertEqual(r['user_text'],'')
            self.assertIsNone(r['ciphertext'])
        self.assertEqual(j.process(self.db,self.case,'s1',make_fake_engine(self.db))['disposition'],'completed')
        j.capture(self.db,self.case,'s1',txt)
        with self.assertRaises(j.SubmissionError):j.capture(self.db,self.case,'s1','DIFFERENT')
    def test_failed_recovery_and_abandon_scrubs(self):
        text='FAILED THEN RECOVERED'
        j.capture(self.db,self.case,'s1',text)
        self.assertEqual(j.process(self.db,self.case,'s1',make_fake_engine(self.db,fail_jev=True))['disposition'],'failed')
        self.assertEqual(j.get_pending_text(self.db,self.case,'s1'),text)
        self.assertEqual(j.process(self.db,self.case,'s1',make_fake_engine(self.db))['disposition'],'completed')
        j.capture(self.db,self.case,'s2','ABANDONED FICTIONAL TEST')
        self.assertEqual(j.abandon(self.db,self.case,'s2',confirmed=True),'abandoned')
        with database._connect(self.db) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM candidate_submissions WHERE ciphertext IS NOT NULL').fetchone()[0],0)
        self.assertEqual(len(database.get_turns(self.db,self.case)),1)
    def test_renewal_owner_token_and_fencing(self):
        j.capture(self.db,self.case,'s1','TEST')
        old=j.LEASE_SECONDS
        j.LEASE_SECONDS=0.25
        try:
            first=j.claim(self.db,self.case,'s1',now=10.0)
            self.assertTrue(j.renew_lease(self.db,self.case,'s1',first['owner'],first['fence'],now=10.12))
            self.assertEqual(j.claim(self.db,self.case,'s1',now=10.25)['disposition'],'busy')
            replacement=j.claim(self.db,self.case,'s1',now=10.5)
            self.assertEqual(replacement['disposition'],'claimed')
            self.assertFalse(j.renew_lease(self.db,self.case,'s1',first['owner'],first['fence'],now=10.51))
            with database._connect(self.db) as c:
                with self.assertRaises(j.SubmissionError):j._check_owner(c,self.case,'s1',first['owner'],first['fence'],10.51)
        finally:
            j.LEASE_SECONDS=old
    def test_real_heartbeat_keeps_long_fake_engine_alive(self):
        old=j.LEASE_SECONDS
        j.LEASE_SECONDS=0.24
        j.capture(self.db,self.case,'s1','Long simulated API call')
        eng=make_fake_engine(self.db)
        original=eng.run_cycle
        def slow(*args,**kwargs):
            time.sleep(0.72)
            return original(*args,**kwargs)
        eng.run_cycle=slow
        try:
            out=j.process(self.db,self.case,'s1',eng)
            self.assertEqual(out['disposition'],'completed',out)
            with database._connect(self.db) as c:
                self.assertEqual(c.execute('SELECT attempts FROM candidate_submissions').fetchone()[0],1)
        finally:
            j.LEASE_SECONDS=old
    def test_plaintext_migration_is_disabled(self):
        source=self.tmp/'legacy.sqlite3'; dest=self.tmp/'copy.sqlite3'
        create_synthetic_legacy(source)
        before=source.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'not supported'):
            migrate_copy(source,dest)
        self.assertEqual(source.read_bytes(),before)
        self.assertFalse(dest.exists())
    def test_legacy_ensure_rejects_without_mutation(self):
        source=self.tmp/'legacy.sqlite3'; create_synthetic_legacy(source)
        before=source.read_bytes()
        with self.assertRaises(j.SubmissionError):j.ensure(source)
        self.assertEqual(source.read_bytes(),before)
    def test_migration_never_overwrites_destination(self):
        src=self.tmp/'legacy.sqlite3'; create_synthetic_legacy(src)
        dest=self.tmp/'target.sqlite3';dest.write_bytes(b'DO NOT REPLACE')
        with self.assertRaisesRegex(RuntimeError, 'not supported'):migrate_copy(src,dest)
        self.assertEqual(dest.read_bytes(),b'DO NOT REPLACE')
    def test_missing_key_refuses_new_journal(self):
        os.environ.pop(journal_crypto.KEY_ENV,None)
        with self.assertRaises(journal_crypto.JournalKeyError):j.ensure(self.tmp/'new.sqlite3')
        self.assertFalse((self.tmp/'new.sqlite3').exists())

if __name__=='__main__':unittest.main(verbosity=2)
