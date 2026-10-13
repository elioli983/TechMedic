# TechMedic v1.5.6 SQLCipher architecture

Reviewed October 12, 2026. Windows-only, single-user local Streamlit application; development/evaluation status. See [validation and outstanding findings](../SQLCIPHER_VALIDATION.md).

## Execution and storage

The Windows launcher uses the release-local `.venv` to run `techmedic.windows_startup`. That module holds a per-user server-lifetime file lock, unwraps the pending-message Fernet key using current-user DPAPI and invokes Streamlit in the same process bound to `127.0.0.1:8519`. Offline mode uses synthetic services. Live mode requires both START_LIVE_TECHMEDIC.bat and the in-app toggle. No application login is implemented.

`app.py` fixes the database path to `PROJECT_ROOT/data/techmedic_v1_5_6.sqlcipher`, overriding the general settings path. `.env` holds optional provider credentials and configuration; the app does not need them for offline mode.

```text
User input -> Fernet-encrypted pending journal -> claim owner/fence
  -> structured diagnostic analysis
  -> optional analyst-gated research and evidence-preserving integration
  -> deterministic safety checks -> Jev decisions
  -> lifecycle/action/readiness guards -> response consistency checks
  -> one transaction: completed turn + case metadata + journal completion
  -> Streamlit history, assessment and optional readable exports
```

`techmedic/database.py` is the shared SQLCipher adapter. Each operation opens a connection, loads/unlocks the DPAPI database key, verifies cipher support, applies the raw random key and format-4 compatibility, forces temporary tables into memory, checks schema readability and enables foreign keys. Connections commit/roll back and close explicitly. There is no ordinary SQLite fallback. Plaintext databases are rejected, not migrated.

The key sidecar is `data/techmedic_v1_5_6.sqlcipher.key.dpapi`; `database_crypto.py` atomically publishes the wrapped random 32-byte key. Missing keys for existing databases fail closed. The separate pending key remains at `%LOCALAPPDATA%\TechMedic\v1.5.6\journal-key.dpapi.txt` and is passed to Python via `TECHMEDIC_CANDIDATE_JOURNAL_KEY`. Its first-run creation now atomically publishes a flushed DPAPI hex file without overwriting an existing key; compatibility with PowerShell-generated keys is tested.

## Journal and recovery

`candidate_journal.py` captures input before external calls. It records fingerprints, pending/running/failed/completed/abandoned state, attempts, owner, fence, lease expiry and completed-turn linkage. Atomic completion verifies input/ownership and writes turn, case changes and journal completion together. Retry/abandon is explicit; duplicate external charges remain possible.

**Corrected:** `process()` preserves the real-time clock sentinel so the heartbeat runs. Claim, renewal, failure and atomic completion resolve time after acquiring the write lock. Lost/expired leases cannot commit; explicit timestamps remain available for deterministic tests. The UI allows retry/abandon of expired workers while active leases remain protected. Tests assert renewal calls and reject completion after lock-wait expiry.

## Diagnostic semantics

The five lifecycle states are investigating, possible_diagnosis, diagnosis_established, remediation_identified and resolution_verified. Escalation is an action. Historical milestones and current remediation readiness are separate. Resolution requires structured post-change verification evidence; human factual review remains necessary.

Research runs only when requested by the analyst and enabled. Results retain queries, source identifiers/URLs, citations, timings and integration outcome. Bounded delta validation preserves local evidence and rejects unsupported changes. Safety/response checks are heuristic rather than an exhaustive guarantee. Jev probabilities are not independently calibrated.

## Interface, exports and performance

Diagnostic Options groups handoff TXT, full diagnostic bundle and developer trace. Recents offers confirmed deletion. Downloaded exports are readable and unencrypted; case text can contain pasted secrets. Database encryption does not cover those files or the plaintext `.env`.

Every database operation opens and unlocks a connection. Normal UI reruns read one bounded history window (50 turns plus one look-behind row initially), reused for assessment and conversation rendering. Load older messages increases the limit by 50; switching cases resets it. Complete history is fetched only when Diagnostic Options is requested for exports/trace. Unfinished-journal queries exclude completed rows. An idempotent index on cases(updated_at DESC) supports Recents ordering. Measured timings and limits are in SQLCIPHER_VALIDATION.md.

## Maintenance boundaries

Keep Windows DPAPI, SQLCipher and the deployment dependency chain under review. Custom Jev URLs must use HTTPS; embedded credentials, fragments and invalid endpoints are rejected. Requests disable redirects and reject 3xx responses, requiring the configured final HTTPS URL. Do not claim multi-user isolation, portable key recovery, live-provider acceptance or general-production security from the offline tests. Older release notes, upgrade guides and the v1.0 specification describe historical designs, not current installation or migration behavior.
