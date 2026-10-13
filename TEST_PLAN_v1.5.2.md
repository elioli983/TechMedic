> **Historical reference - reviewed October 12, 2026.** This document describes the version in its title, not the current v1.5.6 SQLCipher edition. Its installation paths, SQLite-copy/migration instructions, platform support, test counts and planned features are historical. Do not apply them to this edition. Use [README.md](README.md), [USER_MANUAL.md](USER_MANUAL.md) and [SQLCIPHER_VALIDATION.md](SQLCIPHER_VALIDATION.md) for current behavior. Model/repair examples are not current compatibility advice; exports may contain secrets supplied in case text.

# TechMedic v1.5.2 — Controlled Research and Lifecycle Regression Plan

## Preflight
- Use `run_techmedic.bat` in a **new extraction folder**.
- Preserve the previous `.env` and SQLite database safely per `UPGRADE_FROM_v1.5.1.txt`.
- Confirm UI header shows **TechMedic v1.5.2**.
- Start a **new case**. Do not reuse a case that already advanced incorrectly in v1.5.1:
  established states normally stay monotonic.
- These four turns are **synthetic fixtures**, not measurements from the actual machine.

## Turn 1: Local investigation

Enter exactly:

> PyTorch isn't using my NVIDIA GTX 1080. `torch.cuda.is_available()` returns False.

Expect: `Investigating`; evidence sought locally; **no research needed**.

## Turn 2: CPU-only diagnosis, but compatible fix not yet selected

Enter:

> I am using Windows 11. I ran the diagnostic Python code you provided in the
> affected Python environment. Results: `torch.__version__ = 2.14.0+cpu`;
> `torch.version.cuda = None`; `torch.version.hip = None`;
> `torch.cuda.is_available() = False`; `device_count = 0`;
> `device_name = unavailable`. I have not yet checked the Python version
> or run `nvidia-smi`. I have not changed drivers or reinstalled PyTorch.

Expect: `Diagnosis Established`, not `Remediation Identified`. The general
correction is evident but the exact supported build/driver/platform combination
is not yet established. Relevant additional information should be requested.
In Developer Trace, check `remediation.selection_ready = false` and/or
`remediation.blocking_requirements` are populated.

## Turn 3: Controlled documentation research

Enter:

> OS Windows 11 x64; Python 3.13.5 x64; PyTorch 2.14.0+cpu.
> `nvidia-smi` reports NVIDIA GeForce GTX 1080, driver 572.83, CUDA 12.8.
> Device Manager recognizes GTX 1080 with no error. No changes made.
> What compatible PyTorch version and CUDA-enabled installation should I use?

Expect: controlled research requested and performed; documentation-based
compatibility evaluated, preferably from official release/compatibility and
actual distribution index pages. All `citations[*].source_id` values must be
nonempty and match `sources[*].id`. `research_evidence.source_ids` should cite
sources flagged `cited_in_research: true`. Check that *each specific recommendation*
is genuinely supported by its linked source. Search alone does not verify facts.
A specific, supported fix should be offered only if all compatibility blockers
are resolved; otherwise retain `Diagnosis Established` and seek more evidence.

## Turn 4: Simulated verified resolution

Enter:

> I installed the supported CUDA-enabled PyTorch build in the same affected
> environment. The installation succeeded. My verification produced:
> `torch.__version__ = 2.14.1+cu126`, `torch.version.cuda = 12.6`,
> `torch.cuda.is_available() = True`, `device_count = 1`,
> GPU name `NVIDIA GeForce GTX 1080`. GPU tensor multiplication succeeded.
> No other changes were made. This is a simulated verification result.

Expect: `Resolution Verified`, effective `finish_diagnosis`, no new research.

## Validation and reporting

After each significant turn (especially Turn 3), click **Download diagnostic bundle**
and upload ZIP for review. The 12 expected files include
`04_LATEST_CONTROLLED_RESEARCH.json`, `08_CASE_METADATA.json`,
`09_ALL_TURNS_RAW.json`, and `MANIFEST.json`.

Additional regression scenarios to repeat using *new cases*:
1. Network: Wi-Fi connected, `ping 8.8.8.8` succeeds but websites do not load;
   resolver path via `192.168.1.1` fails, direct resolver succeeds. Confirm
   investigation → diagnosis → remediation → verification, no unwarranted regressions.
2. TV: intermittent dark screen with audio continuing, faint moving image under
   flashlight, manufacturer/model details collected; assert diagnosis stays
   established and `escalate` remains an ACTION rather than a lifecycle status.

## Exit criteria

Pass only when the lifecycle/action guards, documented research provenance,
correctly attributed installation evidence, exported ZIP, and regression cases
behave as intended in a **live** TechMedic run. All offline tests passing is
necessary but not sufficient to declare the new release validated.
