> **Historical reference - reviewed October 12, 2026.** This document describes the version in its title, not the current v1.5.6 SQLCipher edition. Its installation paths, SQLite-copy/migration instructions, platform support, test counts and planned features are historical. Do not apply them to this edition. Use [README.md](README.md), [USER_MANUAL.md](USER_MANUAL.md) and [SQLCIPHER_VALIDATION.md](SQLCIPHER_VALIDATION.md) for current behavior. Model/repair examples are not current compatibility advice; exports may contain secrets supplied in case text.

# TechMedic v1.5.5

A stateful, AI-assisted technical troubleshooting application combining **OpenAI LLMs**,
**Jev (typesafe.ai)**, deterministic safety and lifecycle guardrails, optional
controlled documentation research, SQLite case storage, and a Streamlit interface.

**This is a full maintenance-release package, not an update-only patch.**

## Windows installation

1. Unzip this package to a **new** location, e.g. `D:\TechMedic\TechMedic_v1_5_5`.
   Do not overwrite your v1.5.4 installation.
2. Run `setup_windows.bat` to create a local `.venv`, install requirements,
   and generate `.env` from `.env.example` if absent.
3. Open `.env` in Notepad and supply your own `OPENAI_API_KEY`, `JEV_API_KEY`,
   and working model settings. **Never upload `.env` or API keys.**
4. Run `run_offline_validation.bat`. The suite contains **146 offline tests**.
5. Run `run_techmedic.bat`, and use the sidebar to **Test Jev connection**.
6. Start one small *synthetic* case, then click **Download diagnostic bundle**.
   Verify `MANIFEST.json` in that bundle says `techmedic_version=1.5.5`.

Detailed history migration instructions: `UPGRADE_FROM_v1.5.4.txt`.
Release notes: `RELEASE_NOTES_v1.5.5.txt`.

## Data and configuration

- `.env` is created locally and is **not included** in this ZIP.
- Database: `data\techmedic.db`, created on first launch.
- To keep case histories, stop the old instance and copy a **backed-up** DB into
  this version's `data` folder before launch (optional).
- Web research is controlled by `TECHMEDIC_WEB_RESEARCH_ENABLED` (default true)
  and requests only when needed for a concrete evidence question.
- Live OpenAI/Jev calls may incur API charges. Offline tests require no keys.
- Diagnostic bundles can contain sensitive user-provided case text; review before sharing.

## Architecture

User → LLM #1 (structured analysis) → optional controlled source research and
strict evidence-preserving integration → deterministic safety → Jev decision →
lifecycle/action/readiness guardrails → LLM #2 user response with consistency
checks (one correction retry, safe fallback) → SQLite persistence → Streamlit.

The five permitted lifecycle states are: **Investigating**, **Possible Diagnosis**,
**Diagnosis Established**, **Remediation Identified**, **Resolution Verified**.
Escalation is a *workflow action*, never a lifecycle state. Resolution requires
post-remediation evidence, not merely a suggested fix.

The case export ZIP contains 12 entries, including structured state, Jev decision,
controlled research, timing/guardrail telemetry, saved conversation and manifest.

## Testing

Windows: `run_offline_validation.bat` (log at `test_results\last_offline_validation.log`).
Any OS with dependencies installed: `python -m unittest discover -s tests -v`.
The installed `tests/` include original regressions, 16 Phase 1 injection tests,
2 SQLite tests, and 16 Phase 3 provenance tests (146 total).

## Validation boundaries and known limitations

- Offline cases use **synthetic diagnostic evidence**; no physical repair is proven.
- Controlled fault-injection and earlier targeted live tests qualified the fixes,
  but not every possible unsafe response or research failure can be detected.
- Open issues: intermittent apparent input truncation; confidence calibration;
  separate service-provider handoff summary presentation.
- This app supports technical diagnosis and should not replace qualified service
  for high-voltage equipment, electrical safety, batteries or critical systems.

Older `docs/` and version-specific test plans are retained as **historical documents**;
use this README and `RELEASE_NOTES_v1.5.5.txt` for the current release.
