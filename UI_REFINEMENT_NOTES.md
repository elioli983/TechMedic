# Historical UI refinement record - scope notice

Reviewed October 12, 2026. The October 11 UI changes below are already included in the current SQLCipher release. The old UI_Update.zip installation steps must not be applied to it: they can overwrite current code and documentation. Install the full TechMedic_v1.5.6_SQLCipher_DPAPI.zip using README.md instead. The current directory is `D:\TechMedic\TechMedic_v1_5_6-SQLCipher`.

The original record below describes a UI-only change before SQLCipher was implemented. Its storage, path and validation statements are historical. Current encrypted storage and unresolved findings are documented in SQLCIPHER_STORAGE.md and SQLCIPHER_VALIDATION.md. Current UI smoke coverage is Streamlit AppTest, not manual browser acceptance.

---

# TechMedic v1.5.6 — Interface Refinement

This is a **UI-only refinement of the existing Development/Evaluation release**, not a new software version. It contains no changes to the diagnostic engine, database schema, Jev integration, research, confidence, safety, or user-input recovery rules.

## What changed

1. **Synthetic Fault Injection** and its dropdown no longer appear in demo or live mode. The demo still runs with synthetic AI responses; developer fault-injection helpers remain available to automated tests.
2. In the **left sidebar**, **Diagnostic Options** opens a large dialog containing three tabs: **Professional Service Handoff** (copyable text/TXT), **Download Diagnostic Bundle** (ZIP), and **Developer Trace** (structured state/research/Jev/timing/safety). The button is enabled only after at least one completed turn is available.
3. **Return to new-case screen** was removed. Use the existing **＋ New case** button in the sidebar.
4. Each case in **Recents** has a right-hand **⋮** menu. Choose **Delete** to open a permanent-deletion warning, then choose **Delete** again to confirm or **Cancel** to retain it. Current SQLite case records and associated journal entries are deleted, but pre-existing backups and filesystem remnants are not securely erased.

## Updating an installed v1.5.6 copy

1. Close TechMedic and the corresponding browser tab.
2. Back up your current `D:\TechMedic\TechMedic_v1.5.6\app.py` and any existing case data. If you modified the source manually, compare the files before overwriting.
3. Extract **`TechMedic_v1.5.6_UI_Update.zip`** directly into `D:\TechMedic\`. It contains a `TechMedic_v1.5.6` folder; allow replacement of its `app.py`, `USER_MANUAL.md`, `README.md`, `RELEASE_NOTES_v1.5.6.md`, and file manifest.
4. Launch your normal **`START_TECHMEDIC.bat`** (demo) or **`START_LIVE_TECHMEDIC.bat`** (live, with your existing opt-in). No reinstall, new virtual environment, or database migration is needed for this UI-only update.
5. In a fictional case, confirm that the sidebar shows **＋ New case**, **Diagnostic Options**, and a three-dot action next to each case under **Recents**. Check the Delete dialog's **Cancel** path first using a disposable case.

**Security scope:** v1.5.6 remains for fictional or non-sensitive evaluation. Completed diagnostic histories are not encrypted by the pending-message journal, and this update does not change production approval.

**Validation scope:** 163 original offline test cases, 10 hardening tests, and 15 focused static UI contracts passed on Linux/Python 3.13.5. The Streamlit browser interaction has **not** been run in this environment; Windows browser verification remains for the user. No API calls or production data were used.
