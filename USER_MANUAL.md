# TechMedic v1.5.6 — User Manual
**Edition:** SQLCipher / Windows Development / Evaluation | **Reviewed:** October 12, 2026  
**Audience:** One-user Windows evaluation with fictional or non-sensitive technical problems.

## 1. What TechMedic does
TechMedic is an AI-assisted, stateful technical troubleshooting application. It accepts a problem description, uses an OpenAI model to maintain structured diagnostic hypotheses, optionally consults controlled web/documentation research, asks Jev (TypeSafe.ai) for probabilistic decisions and recommended next actions, and uses an OpenAI responder to explain the next step. It stores cases and conversation turns in an encrypted SQLCipher database, with diagnostics, evidence, safety and timing traces.

**This is not a verified repair service.** Do not use it as authority for hazardous electrical work, damaged batteries, medical systems, industrial safety, or other dangerous equipment. Jev confidence scores have not been statistically calibrated against independently verified outcomes.

## 2. Install on Windows

1. **Keep your existing v1.5.5 installation.** Extract the release ZIP to its own folder, for example `D:\TechMedic\TechMedic_v1_5_6-SQLCipher`. Do not extract on top of v1.5.5.
2. Double-click **`INSTALL_WINDOWS.bat`**. A separate `.venv` is created inside the new release folder and required Python packages are installed (internet access needed once). Python 3.14.7 on Windows x64 was tested. Other interpreter/platform combinations need a compatible SQLCipher binary wheel and are not covered by this acceptance. The source ZIP intentionally excludes `.venv`; each fresh extraction needs installation.
3. Double-click **`START_TECHMEDIC.bat`**. The app starts at `http://127.0.0.1:8519` in **offline synthetic demonstration mode**, with no OpenAI or Jev charges.
4. On first launch, Python creates a random database key protected by Windows current-user DPAPI in `data/techmedic_v1_5_6.sqlcipher.key.dpapi`. The launcher also creates or loads the separate pending-submission Fernet key at `%LOCALAPPDATA%\TechMedic\v1.5.6\journal-key.dpapi.txt`. Neither key is shipped in the ZIP or stored in `.env`.

Both protected keys depend on the original Windows profile. Losing that profile or the database key can make all saved cases unrecoverable; losing the journal key can prevent startup and pending-message recovery. **Do not move old v1.5.5 databases into this release folder.** They are not automatically migrated.

## 3. First diagnostic case (offline demonstration)

In the left sidebar, leave **Enable live OpenAI / Jev (evaluation)** turned off for a fictional demonstration. The previous **Synthetic fault injection** control was removed from the user interface; ordinary demonstrations no longer inject artificial failures. Click **+ New case** and enter a fictional problem into **Describe the problem**. Optionally specify a device type, manufacturer, model and operating system; click **Start Diagnosis**. The application records a synthetic analysis, decision scores and next-action suggestion. The results are **not real diagnoses**, and are not evidence of live service operation.

The diagnostic lifecycle has five stages: **Investigating**, **Possible Diagnosis**, **Diagnosis Established**, **Remediation Identified**, and **Resolution Verified**. An *action* such as testing, verifying compatibility or escalating is distinct from the lifecycle stage. Resolution should only be marked verified when a successful post-change retest is documented; model-generated records still require human fact-checking.

Type subsequent information into the chat input beneath the case; the case history and assessment will update. The latest 50 turns appear initially; Load older messages adds 50 more at a time. Switching cases resets that view limit, and full exports always include all saved turns. The sidebar lists saved cases under **Recents**. Select a title to open it, or select its adjacent **⋮** menu and choose **Delete**. A confirmation dialog warns that deletion is permanent. Click **Delete** a second time to confirm, or **Cancel** to keep the case. Deletion removes current database records but does not securely erase old backups or filesystem remnants. The **+ New case** sidebar button is the only new-case navigation control.

## 4. Optional live OpenAI / Jev use

This is an **evaluation-only option**. Use fictional input, not confidential records. If you wish to enable it, open the new release folder's `.env` file (created during installation) and enter `OPENAI_API_KEY` and `JEV_API_KEY` from your respective providers; never share them. Set `OPENAI_MODEL` to an API model available to your account and `JEV_MODEL` / `JEV_API_URL` as required by your working TypeSafe deployment. The shipped `.env.example` names `gpt-5.1` (a configuration example, not an availability guarantee), but you should keep the provider/model settings known to work in your existing environment. Jev `jv_live_...` keys use the hosted endpoint unless overridden. Custom endpoints must use HTTPS without embedded credentials or a URL fragment. HTTP and redirects are rejected before a redirected request can send credentials or case data; configure the final HTTPS endpoint. `.env` is plaintext, so protect it as a credential file.

Double-click **`START_LIVE_TECHMEDIC.bat`**. Then deliberately turn ON **Enable live OpenAI / Jev (evaluation)** in the sidebar. The two-stage opt-in is intentional. Live API calls are billable and can be repeated after an explicit retry. Synthetic fault injection is no longer offered in either the demonstration or live interface. Recoverable failures can still occur naturally during API or database operations.

The **Controlled web research** toggle allows source gathering only when the analyst indicates a need for current documentation. This can add provider cost/time; retrieved source provenance and skipped/failed states are recorded. It is not necessary for the first offline demonstration.

## 5. Confidence, safety, and status

The **Current assessment** panel distinguishes evidence sufficiency, diagnostic confidence, remediation confidence, resolution confidence, professional-service score and recommended next action. These are Jev/TechMedic estimates, **not independently calibrated probabilities**. TechMedic blocks unsupported diagnostic advancement, unsafe or unready remediation, malformed confidence fields, and newly verified resolution without structured successful post-remediation checks in the evaluated decision paths. A reported test must still be factually validated by a human.

Read safety warnings. Do not perform potentially destructive or hazardous procedures solely on an AI suggestion. Advanced inspection is grouped under **Diagnostic Options** in the left sidebar, available once the selected case has a completed turn. Open it to see **Developer Trace**, including structured diagnostic state, research provenance, Jev answers, timing and safety results.

## 6. Failures, saved submissions, and retries

An attempted submission is placed in a local encrypted *pending-message journal* **before** the diagnostic engine runs. If OpenAI, Jev or a database step fails, the original message is saved for explicit recovery and no completed turn is falsely created. Open the saved case, then select **Retry saved submission**; or explicitly confirm **Abandon saved submission**. Unfinished older messages can block newer submissions until resolved. A processing worker may remain marked running until its lease expires. Automatic renewal now runs, and claim/renewal/completion expiry checks use current time after acquiring the database write lock. An expired running submission exposes Retry/Abandon on refresh; an active lease still blocks takeover. See SQLCIPHER_VALIDATION.md. **Retry may incur duplicate external provider charges** if the first attempt reached a service before failing.

Pending messages retain their additional encryption. **All database records, including completed turns, device metadata and notes, are encrypted by SQLCipher.** The database key is protected with Windows current-user DPAPI. Downloaded reports, bundles, old databases and OS swap/crash dumps are outside this protection. See SQLCIPHER_STORAGE.md.

## 7. Export a diagnostic bundle or professional handoff

After one completed diagnostic turn, select **Diagnostic Options** in the left sidebar, then open the **Download Diagnostic Bundle** tab for a ZIP containing the case, full turns, analytical state, Jev results, research metadata, timing, safety, and a manifest. Treat it as unencrypted and potentially sensitive: it includes full user text and can include credentials pasted into a case. The exporter does not load `.env`, but it is not a universal secret-redaction filter. For a shorter deliverable, open the **Professional Service Handoff** tab of the same dialog, copy the report, or select **Download Service Handoff TXT**. The third tab is **Developer Trace**. Its readiness field describes technical readiness, **not permission or authorization**. Check reported facts, diagnosis and safety before forwarding to a technician.

## 8. Storage, upgrades, backups

This is a standalone release with its **own v1.5.6 SQLCipher file** at `data/techmedic_v1_5_6.sqlcipher`; it does not overwrite, import, or migrate v1.5.5 cases. **There is no automatic in-place database upgrade.** Back up your separate folder before changing versions or experimenting with legacy data. Existing SQLite data is ignored. The old migration utility is disabled in this edition.

SQLCipher encrypts completed history as well as pending records. It does not encrypt `.env`, downloaded exports, old SQLite files or OS swap/crash dumps. The earlier drive-encryption audit is historical and has not been repeated. The local HTTP interface has no login; localhost is not Windows-user isolation. General-production approval remains withheld because of the findings in SQLCIPHER_VALIDATION.md. See SQLCIPHER_STORAGE.md for backup requirements; a portable restore process has not been validated.

## 9. Troubleshooting and support notes

- **`No module named streamlit`**: Run `INSTALL_WINDOWS.bat` for this release, not the system Python launcher.
- **Launch says no virtual environment**: Complete installation once.
- **DPAPI key cannot be decrypted / missing**: Do not generate a replacement for an existing database. Recover the original Windows user profile/key if possible; seek technical assistance. An incorrect database key prevents access to the entire database; an incorrect journal key prevents pending-message recovery.
- **Already running / port 8519 occupied**: Stop the existing app console with Ctrl+C, then restart. The supported launchers prevent a second SQLCipher server for the same Windows user. A stale lock file is harmless: Windows releases the actual lock when its owning process exits. Do not delete key files. Older launchers and direct streamlit commands bypass the guard and must be stopped manually.
- **Live model not found / authentication errors**: Check model availability and keys in `.env`. Offline mode does not need credentials.
- **Case remains Investigating**: This is normal when evidence is insufficient. Provide results of one suggested low-risk diagnostic test instead of inventing certainty.
- **Application crashes or fails mid-turn**: Reopen the saved case and use the recovery controls. Do not resubmit the same text as a brand-new message until you have inspected its pending state.

## 10. Release boundary

The updated SQLCipher edition passed 190 core/encryption/development-fix tests and 10 hardening tests on Windows (200 total), plus expanded Streamlit AppTest checks for two-turn operation, history paging, complete exports and expired-worker recovery. The newly installed `.venv` in the flattened SQLCipher folder passed its dependency check and the UI smoke test. Earlier candidate/live/Linux results are historical and do not certify this edition. The lease-renewal, custom-HTTP, journal-key publication/competing-startup and history-query issues are fixed. Local-access authentication, dependency updating and portable recovery remain outside this change; see SQLCIPHER_VALIDATION.md. No new live-provider or separate-account acceptance is claimed.
