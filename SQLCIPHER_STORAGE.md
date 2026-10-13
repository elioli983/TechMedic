# TechMedic v1.5.6 SQLCipher storage update

Reviewed October 12, 2026. Current folder: `D:\TechMedic\TechMedic_v1_5_6-SQLCipher`.

This Windows-only edition starts with an empty encrypted database. Existing SQLite databases are ignored, not converted or deleted. Historical handoffs and old release notes describing plaintext storage or copy migration do not describe this edition.

## Install and run

Run INSTALL_WINDOWS.bat after extracting the source ZIP to create `.venv` locally, then START_TECHMEDIC.bat. The ZIP excludes `.venv`, `.env`, data and keys. Python 3.14 on Windows x64 was tested. The installer requires a compatible binary wheel for sqlcipher3-wheels==0.5.7 and verifies SQLCipher availability. Missing SQLCipher is an installation error; there is no ordinary SQLite fallback. START_LIVE_TECHMEDIC.bat retains the existing additional in-app live-service gate.

The app automatically creates:
- `data/techmedic_v1_5_6.sqlcipher`: encrypted database.
- `data/techmedic_v1_5_6.sqlcipher.key.dpapi`: random 32-byte database key wrapped by Windows current-user DPAPI. This is a binary protected blob, not a password or plaintext key.

The existing pending-message Fernet key remains protected separately at `%LOCALAPPDATA%\TechMedic\v1.5.6\journal-key.dpapi.txt`. It is loaded by `techmedic/windows_startup.py`, invoked by the Windows launcher. No database key is passed in an environment variable, command line, or log. Direct database callers use the same SQLCipher/DPAPI adapter.

## Protection and recovery

All case/turn fields and pending journal records are stored in SQLCipher format 4. Rollback journals and WAL page contents use database encryption. Temporary SQL tables stay in memory. Foreign keys, transactional rollback and atomic completion remain enabled. Lease renewal now runs, and ownership/expiry checks use current time after the write lock is acquired. Targeted expiry and renewal tests pass; see SQLCIPHER_VALIDATION.md. The implementation verifies cipher availability and reads the schema with the key before application queries.

Automatic unlock requires the original Windows user profile. Missing, damaged, or unusable keys stop access; the application never regenerates a key for an existing database or silently resets saved cases. Restore the original key and database together. Do not delete a key to troubleshoot startup.

For backup, fully close TechMedic before copying the database, its `.key.dpapi` sidecar, and the separate journal-key file. Retain a recoverable backup of the Windows profile/DPAPI credentials. Copying these files alone to another account or machine is not a supported recovery method. There is no portable recovery password or key rotation UI in this update. Losing the profile/key can make saved data unrecoverable.

The separate journal key is also published atomically: a fully written, flushed DPAPI-wrapped hex file is renamed into place without replacing an existing key. The format remains compatible with existing PowerShell SecureString files. Failed decryption never regenerates a key.

Only encrypted bytes are written during atomic database-key creation. Concurrent initializers use the same published key. Wrapped key sidecars must not be shipped in a release archive.

## Supported startup and instance lock

Use START_TECHMEDIC.bat or START_LIVE_TECHMEDIC.bat. Both call the same Python startup module, which acquires `%LOCALAPPDATA%\TechMedic\v1.5.6\sqlcipher-application.lock` before loading/creating the journal key. The byte-range lock stays in the Streamlit server process for its lifetime. Windows releases it on normal or forced process exit; the file can remain. A competing launch for the same Windows user fails before key initialization. This is startup coordination, not browser authentication.

Stop any older running instance before upgrading. Direct `streamlit run` and older releases do not participate in this lock and are unsupported ways to launch the updated SQLCipher app. Existing keys and data need no conversion. Existing encrypted databases gain the recent-case index automatically.

## Boundaries

Downloaded TXT/ZIP reports are deliberately readable exports and are not encrypted by SQLCipher. Old SQLite files, old backups, screenshots, API traffic, OS pagefiles/crash dumps and software running as the logged-in user are outside this at-rest protection. Old SQLite files are retained on disk and remain plaintext; this update does not claim to erase them. The app retains its development/evaluation label. Its localhost service has no application login, so DPAPI does not isolate browser access from other local users. `.env` remains a plaintext credential file. The Streamlit UI fixes the database path shown above; `TECHMEDIC_DB_PATH` does not override it.

The SQLCipher Windows wheel is the third-party `sqlcipher3-wheels` distribution, not a commercial Zetetic binary. Version 0.5.7 is pinned and supplied SQLCipher 4.12.0 in testing. Dependency-update findings are recorded in SQLCIPHER_VALIDATION.md; no runtime upgrade is included in this documentation update. The optional `cipher_memory_security=ON` setting caused a native Windows memory-lock failure during validation; the release uses SQLCipher's default memory-security setting. This does not disable database encryption.

## Validation

Run VALIDATE_OFFLINE_OPTIONAL.bat for the core plus encryption tests, and `.venv\Scripts\python.exe -m unittest -v hardening_tests` for recovery/atomicity tests. Use a normal Windows user session so DPAPI can access that profile. Fixtures are disposable and synthetic.

Implementation references:
- https://www.zetetic.net/sqlcipher/sqlcipher-api/
- https://www.zetetic.net/sqlcipher/design/
- https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
- https://pypi.org/project/sqlcipher3-wheels/0.5.7/
