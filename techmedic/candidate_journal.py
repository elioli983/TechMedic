"""Hardening candidate: encrypted pending-message journal with fenced commits.

All persistent records use SQLCipher through the shared database adapter.
"""
from __future__ import annotations

import hashlib
import json
from sqlcipher3 import dbapi2 as sqlite3
import time
import threading
import uuid
from pathlib import Path
from typing import Any
from . import database
from .candidate_context import candidate_active
from . import journal_crypto

TABLE = 'candidate_submissions'
STATES = {'pending', 'running', 'failed', 'completed', 'abandoned'}
LEASE_SECONDS = 3600  # renewable processing lease; a timed-out worker is fenced
MAX_WORKER_SECONDS = 4 * 3600  # upper bound on renewals, not an HTTP cancellation mechanism

class SubmissionError(RuntimeError):
    pass

def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def ensure(db: Path) -> None:
    # Validate key before touching SQLite (avoid orphaned encrypted rows).
    journal_crypto.cipher()
    # Reject legacy schema BEFORE any migration or init_db side effect.
    if Path(db).exists():
        with database._connect(Path(db)) as check:
            exists = check.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
            if exists:
                colnames = {r[1] for r in check.execute(f'PRAGMA table_info({TABLE})')}
                if 'ciphertext' not in colnames or 'input_bytes' not in colnames:
                    raise SubmissionError('Legacy journal is unsupported; use a fresh SQLCipher database, source unchanged')
    database.init_db(db)
    with database._connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
        if old:
            cols = {r['name'] for r in c.execute(f'PRAGMA table_info({TABLE})')}
            if 'ciphertext' not in cols or 'input_bytes' not in cols:
                raise SubmissionError('Legacy journal is unsupported. No automatic migration is available.')
        c.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE} (
            case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            submission_id TEXT NOT NULL,
            user_text TEXT NOT NULL DEFAULT '', -- always empty; retained for old schema compatibility
            ciphertext BLOB,
            input_bytes INTEGER NOT NULL DEFAULT 0,
            sha256_utf8 TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','running','failed','completed','abandoned')),
            attempts INTEGER NOT NULL DEFAULT 0,
            fence INTEGER NOT NULL DEFAULT 0,
            owner TEXT,
            lease_until REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            turn_id INTEGER REFERENCES turns(id) ON DELETE SET NULL,
            error_class TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(case_id, submission_id)
        )''')
        c.execute(f'CREATE INDEX IF NOT EXISTS idx_candidate_pending ON {TABLE}(case_id,state,created_at)')


def _record(c, cid, sid):
    row=c.execute(f'SELECT * FROM {TABLE} WHERE case_id=? AND submission_id=?', (cid,sid)).fetchone()
    return dict(row) if row else None


def capture(db: Path, cid: str, sid: str, text: str, *, now=None):
    if not isinstance(text,str) or not text.strip() or not isinstance(sid,str) or not sid.strip():
        raise ValueError('submission ID and user text must be nonempty')
    payload = journal_crypto.encrypt(text)
    now=time.time() if now is None else float(now)
    with database._connect(db) as c:
        if not c.execute('SELECT 1 FROM cases WHERE id=?',(cid,)).fetchone():
            raise SubmissionError('case missing')
        c.execute(f'''INSERT OR IGNORE INTO {TABLE}
            (case_id,submission_id,user_text,ciphertext,input_bytes,sha256_utf8,state,created_at,updated_at)
            VALUES (?,?, '',?,?,?,'pending',?,?)''', (cid,sid,payload,len(text.encode('utf-8')),sha(text),now,now))
        row=_record(c,cid,sid)
        if row['sha256_utf8'] != sha(text) or row['input_bytes'] != len(text.encode('utf-8')):
            raise SubmissionError('submission identifier reused for different text')
        return row


def list_ui(db:Path, cid:str, *, unfinished_only=False):
    state_filter = " AND state IN ('pending','running','failed')" if unfinished_only else ""
    with database._connect(db) as c:
        rows=c.execute(f'''SELECT submission_id,state,attempts,sha256_utf8,
              input_bytes AS utf8_bytes,created_at,updated_at,lease_until
              FROM {TABLE} WHERE case_id=? {state_filter} ORDER BY created_at,rowid''',(cid,)).fetchall()
        return [dict(r) for r in rows]


def get_pending_text(db, cid, sid):
    with database._connect(db) as c:
        r=_record(c,cid,sid)
        if not r: raise SubmissionError('submission not found')
        if r['state'] in ('completed', 'abandoned'):
            raise SubmissionError('Completed/abandoned journal payload was securely dereferenced; use canonical turns')
        if not r['ciphertext']:
            raise SubmissionError('Pending encrypted payload missing')
        return journal_crypto.decrypt(r['ciphertext'], r['sha256_utf8'])


def claim(db:Path, cid:str, sid:str, *, now=None):
    with database._connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        now = time.time() if now is None else float(now)
        r=_record(c,cid,sid)
        if not r:raise SubmissionError('submission not found')
        if r['state'] in ('completed','abandoned'):
            return {'disposition':r['state']}
        if r['state']=='running' and r['lease_until'] is not None and now<r['lease_until']:
            return {'disposition':'busy'}
        earlier=c.execute(f'''SELECT 1 FROM {TABLE} WHERE case_id=? AND rowid<
              (SELECT rowid FROM {TABLE} WHERE case_id=? AND submission_id=?)
              AND state NOT IN ('completed','abandoned') LIMIT 1''',(cid,cid,sid)).fetchone()
        if earlier:return {'disposition':'earlier_unfinished'}
        active=c.execute(f'''SELECT 1 FROM {TABLE} WHERE case_id=? AND submission_id!=?
              AND state='running' AND lease_until>? LIMIT 1''',(cid,sid,now)).fetchone()
        if active:return {'disposition':'busy'}
        owner=uuid.uuid4().hex
        fence=r['fence']+1
        c.execute(f'''UPDATE {TABLE} SET state='running',owner=?,fence=?,lease_until=?,
                    attempts=attempts+1,error_class='',updated_at=?
                    WHERE case_id=? AND submission_id=?''',
                  (owner,fence,now+LEASE_SECONDS,now,cid,sid))
        return {'disposition':'claimed','owner':owner,'fence':fence}


def _check_owner(c,cid,sid,owner,fence,now):
    r=_record(c,cid,sid)
    if (not r or r['state']!='running' or r['owner']!=owner or r['fence']!=fence
            or r['lease_until'] is None or now>=r['lease_until']):
        raise SubmissionError('lease lost or expired; cannot commit')
    return r


def renew_lease(db, cid, sid, owner, fence, *, now=None) -> bool:
    """Heartbeat extends a running lease only for the still-current owner.

    Every renewal uses a short IMMEDIATE transaction and validates generation.
    Failed renewals are fail-closed; the later atomic commit rechecks ownership.
    """
    with database._connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        now = time.time() if now is None else float(now)
        try:
            _check_owner(c, cid, sid, owner, fence, now)
        except SubmissionError:
            return False
        r = c.execute(f"""UPDATE {TABLE} SET lease_until=?,updated_at=?
            WHERE case_id=? AND submission_id=? AND state='running' AND owner=? AND fence=?""",
            (now + LEASE_SECONDS, now, cid, sid, owner, fence))
        return r.rowcount == 1


def failed(db,cid,sid,owner,fence,*,now=None,exc):
    with database._connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        now = time.time() if now is None else float(now)
        _check_owner(c,cid,sid,owner,fence,now)
        c.execute(f'''UPDATE {TABLE} SET state='failed',owner=NULL,lease_until=NULL,
              error_class=?,updated_at=? WHERE case_id=? AND submission_id=?''',
              (type(exc).__name__[:60],now,cid,sid))


def _update_case_in_tx(c,cid,kw):
    fields=[];params=[]
    if kw.get('title') is not None:
        fields.append('title=?');params.append(kw['title'])
    if kw.get('status') is not None:
        fields.append('status=?');params.append(kw['status'])
    for col in ('device_type','manufacturer','model','operating_system'):
        val=kw.get(col)
        if isinstance(val,str) and val.strip():
            fields.append(f'''{col}=CASE WHEN LOWER(TRIM({col})) IN
                ('', 'unknown', 'not known', 'not provided', 'not specified',
                 'undetermined', 'n/a', 'none') THEN ? ELSE {col} END''')
            params.append(val.strip())
    fields.append('updated_at=?');params.append(database._utc_now())
    params.append(cid)
    updated=c.execute('UPDATE cases SET '+','.join(fields)+' WHERE id=?',params)
    if updated.rowcount!=1:raise SubmissionError('case missing at commit')


def atomic_complete(db,cid,sid,owner,fence,*,now=None,user_text,diagnostic_state,
                    jev_result,safety,assistant_text,research,case_changes,inject_error=False):
    with database._connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        now = time.time() if now is None else float(now)
        r=_check_owner(c,cid,sid,owner,fence,now)
        if not r['ciphertext'] or user_text!=journal_crypto.decrypt(r['ciphertext'],r['sha256_utf8']) or sha(user_text)!=r['sha256_utf8']:
            raise SubmissionError('input changed between capture and completion')
        cur=c.execute('''INSERT INTO turns(case_id,user_text,diagnostic_state_json,jev_result_json,
              safety_json,research_json,assistant_text,created_at)
              VALUES (?,?,?,?,?,?,?,?)''',
              (cid,user_text,json.dumps(diagnostic_state,ensure_ascii=False),
               json.dumps(jev_result,ensure_ascii=False),json.dumps(safety,ensure_ascii=False),
               json.dumps(research or {},ensure_ascii=False),assistant_text,database._utc_now()))
        tid=int(cur.lastrowid)
        _update_case_in_tx(c,cid,case_changes)
        if inject_error:raise RuntimeError('SyntheticAtomicRollback')
        result=c.execute(f'''UPDATE {TABLE} SET state='completed',turn_id=?,owner=NULL,
              lease_until=NULL,error_class='',user_text='',ciphertext=NULL,updated_at=? WHERE case_id=? AND submission_id=?
              AND state='running' AND owner=? AND fence=?''',(tid,now,cid,sid,owner,fence))
        if result.rowcount!=1:raise SubmissionError('journal changed during commit')
        return tid


def process(db:Path,cid:str,sid:str,engine,*,inject_rollback=False,now=None):
    # Preserve None for real-time processing; explicit timestamps are test clocks.
    now = None if now is None else float(now)
    cl=claim(db,cid,sid,now=now)
    if cl['disposition']!='claimed':return cl
    owner,fence=cl['owner'],cl['fence']
    try:
        text=get_pending_text(db,cid,sid)
    except Exception as exc:
        try:
            failed(db,cid,sid,owner,fence,now=now,exc=exc)
        except SubmissionError:
            return {'disposition':'stale','error_class':type(exc).__name__}
        return {'disposition':'failed','error_class':type(exc).__name__}
    result_id={}
    stop = threading.Event()
    lost_lease = threading.Event()
    started_at = time.monotonic()
    heartbeat_thread = None
    if now is None:
        def heartbeat():
            interval = max(0.05, min(60.0, LEASE_SECONDS / 3))
            while not stop.wait(interval):
                if time.monotonic() - started_at >= MAX_WORKER_SECONDS:
                    lost_lease.set()
                    return
                try:
                    if not renew_lease(db, cid, sid, owner, fence):
                        lost_lease.set()
                        return
                except sqlite3.Error:
                    # Retry next interval; if the lease truly expires, commit is fenced.
                    continue
                except Exception:
                    lost_lease.set()
                    return
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True, name='TechMedicJournalHeartbeat')
        heartbeat_thread.start()
    def on_persist(**data):
        if lost_lease.is_set() or time.monotonic() - started_at > MAX_WORKER_SECONDS:
            raise SubmissionError('Lease lost or maximum processing time exceeded; stale worker cannot commit')
        if data.pop('case_id', None) != cid:
            raise SubmissionError('engine case differs from submission case')
        result_id['turn_id']=atomic_complete(
            db,cid,sid,owner,fence,now=now,
            inject_error=inject_rollback,**data)
    engine.candidate_persist=on_persist
    engine.candidate_strict=True
    ctx=candidate_active.set(True)
    try:
        result=engine.run_cycle(cid,text)
        if 'turn_id' not in result_id:raise SubmissionError('engine did not commit turn')
        return {'disposition':'completed','turn_id':result_id['turn_id'],'status':result['diagnostic_state']['status']}
    except Exception as exc:
        try:
            failed(db,cid,sid,owner,fence,now=now,exc=exc)
        except SubmissionError:
            return {'disposition':'stale','error_class':type(exc).__name__}
        return {'disposition':'failed','error_class':type(exc).__name__}
    finally:
        stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=3.0)
        candidate_active.reset(ctx)
        engine.candidate_persist=None


def abandon(db,cid,sid,*,confirmed=False,now=None):
    if confirmed is not True:raise SubmissionError('explicit confirmation required')
    now=time.time() if now is None else float(now)
    with database._connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        r=_record(c,cid,sid)
        if not r:raise SubmissionError('submission not found')
        if r['state']=='completed':raise SubmissionError('cannot abandon completed submission')
        if r['state']=='abandoned':return 'already_abandoned'
        if r['state']=='running' and r['lease_until'] and now<r['lease_until']:
            raise SubmissionError('cannot abandon an active worker')
        c.execute(f'''UPDATE {TABLE} SET state='abandoned',owner=NULL,lease_until=NULL,
            ciphertext=NULL,user_text='',fence=fence+1,updated_at=? WHERE case_id=? AND submission_id=?''',(now,cid,sid))
        return 'abandoned'
