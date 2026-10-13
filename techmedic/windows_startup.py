"""Windows launcher: server-lifetime instance lock and atomic DPAPI journal key."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile
from cryptography.fernet import Fernet
from .database_crypto import _dpapi

class StartupError(RuntimeError):
    pass

@contextmanager
def instance_lock(path: Path):
    import msvcrt
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise StartupError('TechMedic SQLCipher is already running for this Windows user. Stop its console before starting another instance.') from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

def load_journal_key(path: Path, db: Path) -> str:
    """PowerShell-compatible DPAPI hex format; never replace an existing key."""
    if not path.exists():
        if any(Path(str(db) + suffix).exists() for suffix in ('', '-wal', '-shm', '-journal')):
            raise StartupError('Existing database but journal key is missing. Restore the original journal key; do not regenerate it.')
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key().decode('ascii')
        protected = _dpapi(key.encode('utf-16-le'), protect=True).hex().encode('ascii')
        fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(protected)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.rename(name, path)
            except FileExistsError:
                pass
        finally:
            Path(name).unlink(missing_ok=True)
    try:
        wrapped = bytes.fromhex(path.read_text(encoding='utf-8-sig').strip())
        key = _dpapi(wrapped, protect=False).decode('utf-16-le')
        Fernet(key.encode('ascii'))
        return key
    except Exception:
        raise StartupError('Cannot unlock the original journal key. Restore its file and Windows profile; the key was not replaced.') from None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt' or not os.environ.get('LOCALAPPDATA'):
        raise StartupError('Windows and LOCALAPPDATA are required for protected startup.')
    root = Path(__file__).resolve().parent.parent
    key_dir = Path(os.environ['LOCALAPPDATA']) / 'TechMedic' / 'v1.5.6'
    with instance_lock(key_dir / 'sqlcipher-application.lock'):
        os.environ['TECHMEDIC_CANDIDATE_JOURNAL_KEY'] = load_journal_key(
            key_dir / 'journal-key.dpapi.txt', root / 'data' / 'techmedic_v1_5_6.sqlcipher')
        if args.live:
            os.environ['TECHMEDIC_V156_ALLOW_LIVE'] = 'I_ACCEPT_LIVE_API_CALLS'
            print('Live services permitted; also enable the in-app toggle.')
        else:
            os.environ.pop('TECHMEDIC_V156_ALLOW_LIVE', None)
            print('Offline synthetic demonstration. No live model calls.')
        try:
            from streamlit.web import cli
            sys.argv = ['streamlit', 'run', str(root / 'app.py'), '--server.address', '127.0.0.1', '--server.port', '8519']
            cli.main()
        finally:
            os.environ.pop('TECHMEDIC_CANDIDATE_JOURNAL_KEY', None)

if __name__ == '__main__':
    try:
        main()
    except StartupError as exc:
        print('Startup prevented: ' + str(exc), file=sys.stderr)
        raise SystemExit(4)
