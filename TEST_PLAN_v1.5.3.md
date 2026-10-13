> **Historical reference - reviewed October 12, 2026.** This document describes the version in its title, not the current v1.5.6 SQLCipher edition. Its installation paths, SQLite-copy/migration instructions, platform support, test counts and planned features are historical. Do not apply them to this edition. Use [README.md](README.md), [USER_MANUAL.md](USER_MANUAL.md) and [SQLCIPHER_VALIDATION.md](SQLCIPHER_VALIDATION.md) for current behavior. Model/repair examples are not current compatibility advice; exports may contain secrets supplied in case text.

# TechMedic v1.5.3 — Test Plan

## Offline acceptance

Run `python -m unittest discover -s tests -v` from the v1.5.3 folder.
Ensure the v1.5.2 tests still pass, plus new integrity regression tests:
- incomplete/missing-key JSON rejected BEFORE normalization;
- actual v1.5.2 erased-state regression fixture rejected, prior evidence retained;
- valid integration preserves symptoms, tests, observations, diagnosis basis;
- invalid/unsupported research citations or remediation flags fail closed;
- downstream Jev sees preserved state on rejected integrations;
- raw research outcome is still available in diagnostic bundle telemetry;
- OS case metadata upgrades from `Unknown` to `Windows 11`;
- TV/Network regression and terminal-state guardrails remain intact.

## Live acceptance (existing PyTorch case sequence, new case)

Turn 1: `PyTorch isn't using my NVIDIA GTX 1080. torch.cuda.is_available() returns False.`
Turn 2: CPU-only build, Windows 11, driver and Python details not yet supplied.
Turn 3: Python 3.13.5, Windows 11, nvidia-smi reports GTX 1080,
        NVIDIA driver 572.83, CUDA 12.8; ask for compatible CUDA PyTorch.

Expected: diagnosis evidence preserved; research triggered in Turn 3;
source IDs mapped to official evidence; remediation advanced only with
specific supported package source; research integration audit.status accepted;
no diagnostic-confidence collapse from loss of user evidence.

Export `Download diagnostic bundle` after Turn 3, inspect
`04_LATEST_CONTROLLED_RESEARCH.json`, `06_LATEST_TIMING_TELEMETRY.json`, and
`09_ALL_TURNS_RAW.json`. Continue to resolution verification ONLY once
research integration and research recommendation are validated.
