"""Pre-release candidate: encrypted PENDING journal payload only.

Additional protection for pending payloads; SQLCipher encrypts the entire database.
The key MUST live outside the shipped ZIP and SQLite file.
"""
from __future__ import annotations
import os
from cryptography.fernet import Fernet, InvalidToken

KEY_ENV = 'TECHMEDIC_CANDIDATE_JOURNAL_KEY'

class JournalKeyError(RuntimeError):
    pass

def cipher() -> Fernet:
    key = os.environ.get(KEY_ENV, '')
    if not key:
        raise JournalKeyError(f'{KEY_ENV} not configured. Do not generate a fresh key over existing pending submissions.')
    try:
        return Fernet(key.encode('ascii'))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise JournalKeyError(f'{KEY_ENV} must contain an unmodified Fernet key') from exc

def encrypt(text: str) -> bytes:
    return cipher().encrypt(text.encode('utf-8'))

def decrypt(payload: bytes, expected_hash: str) -> str:
    from hashlib import sha256
    try:
        raw = cipher().decrypt(bytes(payload))
        text = raw.decode('utf-8')
    except (InvalidToken, UnicodeError, TypeError, ValueError) as exc:
        raise JournalKeyError('Cannot decrypt pending submission. Check original key; DO NOT overwrite the ciphertext.') from exc
    if sha256(raw).hexdigest() != expected_hash:
        raise JournalKeyError('Decrypted pending submission fingerprint mismatch')
    return text
