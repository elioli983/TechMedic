"""SQLCipher keys wrapped with Windows current-user DPAPI; no raw keys on disk."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import tempfile

class DatabaseKeyError(RuntimeError):
    pass

class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

def _dpapi(value: bytes, *, protect: bool) -> bytes:
    if os.name != 'nt':
        raise DatabaseKeyError('Encrypted TechMedic storage requires Windows DPAPI.')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    raw = ctypes.create_string_buffer(value)
    source = _Blob(len(value), ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    # UI_FORBIDDEN only; never LOCAL_MACHINE: keys belong to this Windows user.
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        ctypes.memset(raw, 0, len(raw))
        raise DatabaseKeyError('Windows DPAPI could not protect/unlock the database key. Use the original Windows profile and key file.')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(raw, 0, len(raw))
        ctypes.memset(output.data, 0, output.size)
        kernel.LocalFree(output.data)

def key_path(db: Path) -> Path:
    return Path(str(db) + '.key.dpapi')

def load_key(db: Path) -> bytes:
    """Publish wrapped keys atomically. Windows rename never replaces a winner.

    Concurrent first opens use the same key. Existing databases, including empty
    files and journal sidecars, must never receive a replacement key.
    """
    if os.name != 'nt':
        raise DatabaseKeyError('Encrypted TechMedic storage requires Windows DPAPI.')
    db = Path(db)
    path = key_path(db)
    if not path.exists():
        if any(Path(str(db) + suffix).exists() for suffix in ('', '-wal', '-shm', '-journal')):
            raise DatabaseKeyError('Database exists but its DPAPI key is missing. Restore the original key; do not regenerate it.')
        path.parent.mkdir(parents=True, exist_ok=True)
        wrapped = _dpapi(secrets.token_bytes(32), protect=True)
        fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(wrapped)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.rename(temporary, path)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    try:
        key = _dpapi(path.read_bytes(), protect=False)
    except OSError:
        raise DatabaseKeyError('Cannot read the database DPAPI key file.') from None
    if len(key) != 32:
        raise DatabaseKeyError('Invalid database key length; restore the original key file.')
    return key
