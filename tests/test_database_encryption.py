"""Real Windows DPAPI/SQLCipher acceptance using disposable synthetic records."""
import concurrent.futures
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from techmedic import database
from techmedic.database_crypto import load_key, key_path, _dpapi, DatabaseKeyError

class EncryptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'secure.sqlcipher'

    def test_dpapi_roundtrip_and_wrapped_key(self):
        key = load_key(self.db)
        self.assertEqual(len(key), 32)
        wrapped = key_path(self.db).read_bytes()
        self.assertNotIn(key, wrapped)
        self.assertEqual(_dpapi(wrapped, protect=False), key)
        self.assertEqual(load_key(self.db), key)

    def test_plain_sqlite_cannot_read_completed_records(self):
        database.init_db(self.db)
        marker = 'FICTIONAL_SECRET_4dbdf12a'
        cid = database.create_case(self.db, marker)
        database.add_turn(self.db,cid,marker,{'secret':marker},{},{},marker)
        self.assertEqual(database.get_turns(self.db,cid)[0]['user_text'],marker)
        self.assertFalse(self.db.read_bytes().startswith(b'SQLite format 3'))
        self.assertNotIn(marker.encode(),self.db.read_bytes())
        con = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                con.execute('SELECT * FROM cases').fetchall()
        finally:
            con.close()

    def test_missing_key_does_not_replace_or_modify_database(self):
        database.init_db(self.db)
        before = self.db.read_bytes()
        key_path(self.db).unlink()
        with self.assertRaises(DatabaseKeyError): database.init_db(self.db)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse(key_path(self.db).exists())

    def test_corrupt_key_fails_without_mutation(self):
        database.init_db(self.db)
        before = self.db.read_bytes()
        key_path(self.db).write_bytes(b'corrupt DPAPI blob')
        with self.assertRaises(DatabaseKeyError): database.init_db(self.db)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(key_path(self.db).read_bytes(),b'corrupt DPAPI blob')

    def test_wrong_valid_key_fails_and_original_recovers(self):
        database.init_db(self.db)
        before = self.db.read_bytes()
        original = key_path(self.db).read_bytes()
        key_path(self.db).write_bytes(_dpapi(os.urandom(32),protect=True))
        with self.assertRaises(database.sqlite3.DatabaseError): database.init_db(self.db)
        self.assertEqual(self.db.read_bytes(),before)
        key_path(self.db).write_bytes(original)
        self.assertEqual(database.list_cases(self.db),[])

    def test_plaintext_input_is_refused_unchanged(self):
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE old_data(secret TEXT)')
        con.close()
        before = self.db.read_bytes()
        with self.assertRaisesRegex(DatabaseKeyError,'Plaintext'): database.init_db(self.db)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse(key_path(self.db).exists())

    def test_driver_without_cipher_support_is_refused(self):
        with patch.object(database,'sqlite3',sqlite3):
            with self.assertRaisesRegex(DatabaseKeyError,'fallback'): database.init_db(self.db)
        self.assertEqual(self.db.stat().st_size,0)

    def test_wal_and_rollback_journal_have_no_plaintext(self):
        database.init_db(self.db)
        for mode,suffix in [('DELETE','-journal'),('WAL','-wal')]:
            with database._connect(self.db) as con:
                self.assertEqual(con.execute('PRAGMA temp_store').fetchone()[0],2)
                con.execute('PRAGMA journal_mode='+mode)
                marker='JOURNAL_SECRET_86cda' * 1000
                con.execute('INSERT INTO cases(id,title,created_at,updated_at) VALUES(?,?,?,?)',(mode,marker,'now','now'))
                # WAL pages appear after commit; rollback journal exists before commit.
                if mode=='WAL': con.commit()
                sidecar=Path(str(self.db)+suffix)
                self.assertTrue(sidecar.exists())
                self.assertNotIn(b'JOURNAL_SECRET_86cda',sidecar.read_bytes())
                self.assertEqual(con.execute('PRAGMA cipher_integrity_check').fetchall(),[])
            self.assertNotIn(b'JOURNAL_SECRET_86cda',self.db.read_bytes())

    def test_concurrent_first_open_uses_one_key(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            keys=list(executor.map(lambda _: load_key(self.db),range(16)))
        self.assertEqual(len(set(keys)),1)
        database.init_db(self.db)
        self.assertEqual(database.list_cases(self.db),[])

    def test_reopen_in_fresh_process(self):
        database.init_db(self.db)
        database.create_case(self.db,'RESTART_TEST')
        code='from pathlib import Path; from techmedic import database; import sys; assert database.list_cases(Path(sys.argv[1]))[0]["title"]=="RESTART_TEST"'
        result=subprocess.run([sys.executable,'-c',code,str(self.db)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__': unittest.main()
