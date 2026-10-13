"""Legacy migration is disabled: this release starts with an empty SQLCipher DB."""
from pathlib import Path
from techmedic import database, candidate_journal as journal

def migrate_copy(source: Path, destination: Path) -> dict:
    raise RuntimeError('SQLite migration is not supported in the SQLCipher edition. Start a fresh database.')

def create_synthetic_legacy(path: Path) -> tuple[str,str]:
    """Use fictional messages only."""
    database.init_db(path)
    cid=database.create_case(path, 'SYNTHETIC MIGRATION CASE')
    text='SYNTHETIC PENDING TEXT / unicode Ω / END MARKER'
    old_schema='''CREATE TABLE candidate_submissions (
        case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        submission_id TEXT NOT NULL, user_text TEXT NOT NULL, sha256_utf8 TEXT NOT NULL,
        state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        fence INTEGER NOT NULL DEFAULT 0, owner TEXT, lease_until REAL,
        created_at REAL NOT NULL, updated_at REAL NOT NULL,
        turn_id INTEGER REFERENCES turns(id) ON DELETE SET NULL,
        error_class TEXT NOT NULL DEFAULT '', PRIMARY KEY(case_id, submission_id))'''
    with database._connect(path) as con:
        con.execute(old_schema)
        for sid,state,msg in [('one','failed',text),('two','completed','SYNTHETIC COMPLETED'),('three','abandoned','SYNTHETIC ABANDONED')]:
            con.execute('''INSERT INTO candidate_submissions(case_id,submission_id,user_text,sha256_utf8,state,created_at,updated_at)
                           VALUES (?,?,?,?,?,1.0,1.0)''',(cid,sid,msg,journal.sha(msg),state))
    return cid,text


if __name__ == '__main__':
    raise SystemExit('Migration disabled. See SQLCIPHER_STORAGE.md; use a fresh encrypted database.')
