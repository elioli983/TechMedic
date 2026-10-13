> **Historical reference - reviewed October 12, 2026.** This document describes the version in its title, not the current v1.5.6 SQLCipher edition. Its installation paths, SQLite-copy/migration instructions, platform support, test counts and planned features are historical. Do not apply them to this edition. Use [README.md](README.md), [USER_MANUAL.md](USER_MANUAL.md) and [SQLCIPHER_VALIDATION.md](SQLCIPHER_VALIDATION.md) for current behavior. Model/repair examples are not current compatibility advice; exports may contain secrets supplied in case text.

# TechMedic v1.5.4 test plan

## Goal
Check whether current research, remediation readiness, Jev action and final instructions stay coherent, particularly after failed installation/repair and after a malformed integration response.

Use the synthetic fixture from v1.5.3 Tests 1–6, not real measurements. Start a NEW case. Continue in the SAME case.

### Turn 1
`PyTorch isn't using my NVIDIA GTX 1080. torch.cuda.is_available() returns False.`
Expected: investigating, local diagnostic test, no external research.

### Turn 2
Provide Windows 11, PyTorch `2.14.0+cpu`, `torch.version.cuda=None`, `torch.cuda.is_available()=False`, zero devices; Python and nvidia-smi still unknown.
Expected: diagnosis_established, selection_ready=false; request system information.

### Turn 3
Provide Python 3.13.5 x64, Windows 11 x64, nvidia-smi GTX 1080, NVIDIA driver 572.83, driver-reported CUDA 12.8, active torch 2.14.0+cpu, request compatibility-supported installation.
Expected: controlled research if needed. Verify source IDs, delta integration status, preservation of original observations, and current remediation readiness. Candidate install command must not have same public version/no upgrade behavior.

### Turn 4 — failed pip repair
Report previous command `python -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cu126` yielded already-satisfied CPU-only torch; torch.__version__ still CPU, torch.cuda.is_available() false.
Expected: diagnosis preserved, remediation re-evaluated, no false resolution, no identical no-op command repeated.

### Turn 5 — dry-run
Report `pip install --dry-run --upgrade` selected `torch-2.14.0+cu126-cp313-cp313-win_amd64.whl`; no actual installation.
Expected: acknowledge wheel selection alone does not prove installed GPU operation; use earlier research when adequate, and check readiness vs blocker consistency.

### Turn 6 — authorized instructions
Ask: `Proceed. Give me the exact PowerShell installation command that replaces CPU-only torch and post-install commands checking version, CUDA, GPU name and a small GPU tensor operation; do not execute anything.`
Expected: If candidate supported and ready, present a command that really replaces the CPU-only build and post-install verification, with no needless confirmation loop. If not ready, state one specific blocker accurately, rather than saying compatibility is both verified and unverified.

### Failure-injection regression (offline)
Simulate an integration response without any required keys, followed by a valid research_delta_v1. Confirm bounded repair accepted. Repeat with two invalid responses and confirm preserved evidence, blocked repair, and sanitized preview in ZIP telemetry.

### Bundle sharing
Click `Download diagnostic bundle` and upload the ZIP for an independent review. **Do not** include `.env` or credentials.

### Pass criteria
No loss of established evidence; appropriate source-ID linkage; distinct historical lifecycle and current readiness; effective action matches response; no unsupported command; resolution verified only after actual successful local GPU execution (or synthetic verification step explicitly marked simulated).
