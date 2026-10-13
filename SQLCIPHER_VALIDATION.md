# SQLCipher validation and development-fix results

**Evidence date:** October 12, 2026. **Documentation review:** October 12, 2026.

## Tested artifact and environment

Source lineage: UI-refined ZIP SHA-256 `2d4d0f1a5ca92358a266d92694af52c5739a4befa7623438ef681a4e80b857c9`; original CRC and 88/88 source hashes were verified before SQLCipher changes. Current file hashes are in FILE_MANIFEST_SHA256.json. Hashes establish consistency, not a security certification.

Windows x64, Python 3.14.7, sqlcipher3-wheels 0.5.7, SQLCipher 4.12.0 community, SQLite core 3.51.1. The audit used Streamlit 1.65.0 and cryptography 50.0.2. Most requirements specify minimum versions, so later installations can resolve differently.

## Current verification - four fixes completed

- 190 core/encryption/development-fix tests plus 10 hardening tests passed: **200 total** on Windows/Python 3.14.7.
- The 17 additional tests cover actual heartbeat calls, long-turn completion, failed renewal, expiry during write-lock contention, explicit test clocks, HTTPS-only endpoints, redirect refusal, bounded ordered history, complete exports, index creation, concurrent journal-key creation, missing/corrupt keys, PowerShell compatibility in both directions, process lock contention/forced exit, launcher lifetime and live/offline gates.
- Expanded Streamlit AppTest passed startup/two turns, 50/100/122-turn paging, complete-history retrieval for Diagnostic Options, and retry of an expired worker. A normal rerun was verified to make just one limited history read.
- An actual isolated Streamlit server passed its HTTP health check. A second process using the same temporary Windows profile was refused, and the lock could be acquired after the first process terminated. The server smoke used a synthetic page and alternate port; normal TechMedic UI behavior was checked separately with AppTest.
- Existing database encryption tests continue to pass: ordinary SQLite rejection, DPAPI unlock, wrong/missing/corrupt keys, restart, journal protection and transaction checks.
- No live OpenAI/Jev calls, separate-Windows-account authorization test or production acceptance is claimed. The live launcher gate was exercised with a mocked server, not billable services.

## Status of the earlier audit findings

1. **Lease renewal/expiry - fixed.** Real-time processing retains its clock sentinel; all relevant ownership checks resolve time after write-lock acquisition. Heartbeat tests assert actual renewal calls, not just a successful result.
2. **Custom HTTP/redirects - fixed.** HTTPS is required before requests; all redirects are refused so credentials/body are not forwarded through a downgraded route.
3. **Journal initialization/competing startup - fixed for supported launchers.** Complete wrapped keys are atomically published, existing keys remain compatible, and the lock is held by the server process. Direct streamlit invocation and older launchers bypass this guard and must not be used.
4. **History and Recents query cost - improved.** Initial reads are bounded and reused; full history remains available on demand, and Recents uses idx_cases_updated_at.
5. **Local browser access, dependency upgrade, portable recovery - still outside this change.** Localhost is not Windows-user authentication. SQLCipher remains 4.12.0 from wheel 0.5.7; see the previously reviewed [4.19.0 advisory](https://www.zetetic.net/blog/2026/09/08/sqlcipher-4.19.0-release/). The specifically affected URI hexkey/sqlcipher_export features were not found in use here. No portable profile/key recovery process has been certified.

The previous audit's 183-test pass did not catch the lease defect; its failing targeted probe is historical evidence, superseded for that defect by the new regressions. The original audit folder below is not a test report for this updated code. The optional cipher_memory_security setting remains off after its earlier native Windows failure; database encryption stays enabled.

## Updated history measurement

On a fresh disposable 1,000-turn database with roughly 8 KB of JSON detail per turn, ten reads each measured median **124.011 ms** for all turns versus **8.876 ms** for the initial 51-row window (50 displayed plus one look-behind). These are database fetch/decode timings, not browser-render or provider latency guarantees. EXPLAIN QUERY PLAN confirmed Recents uses idx_cases_updated_at without a temporary sort. Evaluation evidence: `D:\TechMedic\Testing\four_fixes_results.json` (not shipped).

## Earlier baseline performance measurements

Disposable synthetic data on this workstation; medians and 95th-percentile samples are not service-level guarantees. No live provider latency is included. The plaintext comparison uses a simpler schema and is not an identical end-to-end workload.

| Operation | Samples | Median ms | p95 ms |
|---|---:|---:|---:|
| DPAPI unlock | 50 | 0.601 | 0.803 |
| Encrypted connection and case-list read | 50 | 2.028 | 2.750 |
| Simple plaintext SQLite read | 50 | 1.088 | 1.165 |
| Encrypted case creation/commit | 30 | 18.429 | 30.839 |
| Read/decode 1,000 synthetic turns | 10 | 110.295 | 112.301 |

The 1,000-turn fixture included roughly 8 KB of JSON detail plus input and response text per turn. Results support modest encryption overhead for this single-user workload.

Audit evidence on the evaluation workstation (not shipped): `D:\TechMedic\Testing\SQLCipher_Audit_2026_10_12\tests.log`, `results.json`, and `audit.py`.

## Reproduce

From the installed SQLCipher folder in a normal Windows user session:

```bat
VALIDATE_OFFLINE_OPTIONAL.bat
.venv\Scripts\python.exe -m unittest -v hardening_tests
.venv\Scripts\python.exe check_sqlcipher_ui.py
.venv\Scripts\python.exe -m pip check
```

The first runner blocks network calls. Fixtures are synthetic and use temporary databases. These are evaluation checks, not unrestricted production approval.
