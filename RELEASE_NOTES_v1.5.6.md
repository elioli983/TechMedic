# TechMedic v1.5.6 - SQLCipher release notes

**Reviewed:** October 12, 2026. **Class:** Development / Evaluation; not general-production approved. The version remains 1.5.6.

## Current changes

- Replaces ordinary SQLite connections with SQLCipher, including the pending-journal adapter. All saved case metadata, completed turns and journal records are encrypted at rest.
- Generates a random 32-byte database key and stores only its Windows current-user DPAPI-wrapped form. Missing, invalid or incorrect keys fail closed; no plaintext fallback or automatic reset is provided.
- Uses a fresh `data/techmedic_v1_5_6.sqlcipher`. Existing SQLite databases are ignored; copy migration is disabled.
- Retains additional Fernet encryption for pending submissions and the launcher's separate DPAPI-protected journal key.
- Preserves transactional turn/case/journal completion, explicit retry/abandon and owner/fence checks. Automatic renewal and current-time expiry checks are now fixed and tested.
- Retains the five diagnostic lifecycle states, evidence and safety checks, controlled research, and offline-by-default/two-gate live operation.
- Includes the October 11 UI refinement: sidebar Diagnostic Options, + New case, and confirmed deletion from Recents. The current full ZIP already includes these changes; do not apply the older UI-only patch over it.

## Four development/evaluation fixes - October 12, 2026

1. Lease renewal now executes, and expiry checks use current time after acquiring write locks. The UI exposes retry/abandon for expired workers. Targeted tests reject stale completion and prove heartbeats occur.
2. Custom Jev endpoints require HTTPS. Invalid URLs, embedded credentials and fragments are rejected. HTTP redirects are not followed; configure the final HTTPS endpoint.
3. Journal-key creation atomically publishes complete DPAPI-wrapped bytes in the existing PowerShell-compatible format. Both Windows launchers now invoke a Python startup module with a per-user server-lifetime lock. A second SQLCipher process is rejected before key initialization; process exit releases the lock.
4. History initially loads the newest 50 turns once per normal rerun. Load older messages expands the window; exports still include every turn. Recents uses a timestamp index created automatically in existing encrypted databases.

## Verification

190 core/encryption/development-fix tests plus 10 hardening tests passed (200 total) on Windows/Python 3.14.7. Expanded Streamlit AppTest passed normal operation, paging, full-history export and expired-worker retry. An isolated real Streamlit server passed its health check, rejected a second process and released its lock on termination. No live provider calls were made.

For 1,000 synthetic turns, fetching/decoding the initial 51-row window measured about 8.9 ms median versus 124.0 ms for the complete history on this machine. This excludes UI rendering and model latency. See SQLCIPHER_VALIDATION.md.

## Upgrade and remaining limits

Stop the running console with Ctrl+C before using the updated launcher. Existing encrypted databases and protected keys are retained; no conversion or replacement is needed. Older launchers/direct streamlit commands do not participate in the new lock.

The release remains development/evaluation. This work does not add browser authentication, update the SQLCipher binary, provide portable backup recovery, encrypt exports or plaintext .env files, guarantee provider billing exactly once, or establish general-production/safety-critical approval. No GitHub publication has been performed. Earlier candidate/Linux/live results remain historical evidence for their own artifacts.
