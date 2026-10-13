from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

from .presentation import friendly_action, friendly_status


APP_VERSION = "1.5.6"


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False)


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _seconds(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value) / 1000:.2f} s"
    return "—"


def _slug(text: str, max_len: int = 70) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", (text or "").strip())
    text = re.sub(r"_+", "_", text).strip("._-")
    return (text[:max_len] or "TechMedic_case")


def bundle_filename(case: dict[str, Any]) -> str:
    title = _slug(str(case.get("title") or "TechMedic_case"), max_len=55)
    return f"TechMedic_v1.5.6_{title}_diagnostic_bundle.zip"


def _assessment_markdown(turn: dict[str, Any]) -> str:
    jev = turn.get("jev_result") or {}
    answers = jev.get("answers") or {}
    telemetry = jev.get("_techmedic") or {}

    fault = answers.get("fault_domain") or {}
    evidence = answers.get("evidence_sufficient") or {}
    diagnosis = answers.get("diagnosis_established") or {}
    remediation = answers.get("remediation_identified") or {}
    resolution = answers.get("resolution_verified") or {}
    hardware = answers.get("hardware_failure_likely") or {}
    service = answers.get("professional_service_needed") or {}
    urgency = answers.get("urgency") or {}
    action = answers.get("next_action") or {}

    fault_choice = fault.get("choice")
    if fault_choice == "unknown":
        fault_value = "Not yet determined"
        fault_note = f"Jev unresolved-domain confidence: {_percent(fault.get('confidence'))}"
    else:
        fault_value = str(fault_choice or "—").replace("_", " ").title()
        fault_note = f"Jev choice confidence: {_percent(fault.get('confidence'))}"

    raw_action = action.get("choice")
    effective_action = telemetry.get("effective_next_action") or raw_action
    overridden = bool(raw_action and effective_action and raw_action != effective_action)
    action_note = f"Jev choice confidence: {_percent(action.get('confidence'))}"
    if overridden:
        action_note = (
            f"Lifecycle guardrail override; Jev proposed {friendly_action(raw_action)} "
            f"({_percent(action.get('confidence'))})"
        )

    urgency_score = urgency.get("score")
    urgency_text = f"{urgency_score:.2f} / 3" if isinstance(urgency_score, (int, float)) else "—"

    lines = [
        "### Current assessment",
        "",
        f"- **Fault domain:** {fault_value} ({fault_note})",
        f"- **Evidence sufficient:** {_percent(evidence.get('noul'))}",
        f"- **Diagnostic confidence:** {_percent(diagnosis.get('noul'))}",
        f"- **Remediation confidence:** {_percent(remediation.get('noul'))}",
        f"- **Current remediation ready:** {'Yes' if telemetry.get('current_remediation_ready') else 'No'}",
        f"- **Historical milestone/current readiness diverge:** {'Yes' if telemetry.get('historical_lifecycle_may_exceed_readiness') else 'No'}",
        f"- **Resolution verified:** {_percent(resolution.get('noul'))}",
        f"- **Hardware failure likely:** {_percent(hardware.get('noul'))}",
        f"- **Urgency score:** {urgency_text}",
        f"- **Professional service:** {_percent(service.get('noul'))}",
        f"- **TechMedic next action:** {friendly_action(effective_action)} ({action_note})",
        f"- **LLM response time:** {_seconds(telemetry.get('llm_response_time_ms'))}",
        f"- **Jev response time:** {_seconds(telemetry.get('jev_response_time_ms'))}",
        f"- **Total AI processing:** {_seconds(telemetry.get('total_ai_processing_time_ms'))}",
    ]

    research = turn.get("research") or {}
    if research.get("performed"):
        rmeta = research.get("_techmedic") or {}
        lines.append(
            f"- **Controlled web research:** used; {len(research.get('sources') or [])} source(s); "
            f"{len(research.get('citations') or [])} mapped citation(s); "
            f"{_seconds(rmeta.get('research_response_time_ms'))}"
        )
        integration = rmeta.get("integration_validation") or {}
        if integration.get("fallback_used"):
            lines.append("- **Research integration:** FAILED VALIDATION; retrieved findings retained for audit, diagnostic state preserved, repair not approved")
        elif integration.get("status") == "accepted":
            lines.append("- **Research integration:** validated and evidence-preserving")
        invalid = rmeta.get("invalid_integrated_source_ids") or []
        if invalid:
            lines.append(f"- **Research source attribution warning:** dropped {len(invalid)} unsupported source ID(s)")
    elif research.get("error"):
        lines.append(f"- **Controlled web research error:** {research.get('error')}")
    else:
        lines.append("- **Controlled web research:** not used on this turn")

    return "\n".join(lines)


def build_screen_output(case: dict[str, Any], turns: list[dict[str, Any]]) -> str:
    lines = [
        f"# TechMedic v{APP_VERSION}",
        "",
        "Observe → Form hypotheses → Test → Collect evidence → Reassess → Recommend",
        "",
        f"## {case.get('title') or 'Untitled case'}",
        "",
        f"Status: {friendly_status(case.get('status'))}",
        "",
    ]
    if not turns:
        lines.append("This case has no completed diagnostic turns.")
        return "\n".join(lines) + "\n"

    latest = turns[-1]
    lines.extend([_assessment_markdown(latest), "", "### Diagnostic conversation", ""])
    for turn in turns:
        lines.extend(
            [
                "#### User",
                "",
                str(turn.get("user_text") or ""),
                "",
                "#### TechMedic",
                "",
                str(turn.get("assistant_text") or ""),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_case_history(case: dict[str, Any], turns: list[dict[str, Any]]) -> str:
    lines = [
        f"# TechMedic case history — {case.get('title') or 'Untitled case'}",
        "",
        f"- Case ID: `{case.get('id', '')}`",
        f"- Status: {friendly_status(case.get('status'))}",
        f"- Created: {case.get('created_at', '')}",
        f"- Updated: {case.get('updated_at', '')}",
        "",
    ]
    for idx, turn in enumerate(turns, start=1):
        lines.extend(
            [
                f"## Turn {idx}",
                "",
                f"Created: {turn.get('created_at', '')}",
                "",
                "### User",
                "",
                str(turn.get("user_text") or ""),
                "",
                "### TechMedic",
                "",
                str(turn.get("assistant_text") or ""),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_combined_report(case: dict[str, Any], turns: list[dict[str, Any]]) -> str:
    latest = turns[-1] if turns else {}
    telemetry = ((latest.get("jev_result") or {}).get("_techmedic") or {}) if latest else {}
    sections = [
        build_screen_output(case, turns).rstrip(),
        "",
        "---",
        "",
        "# Latest raw diagnostic data",
        "",
        "## LLM structured state",
        "",
        "```json",
        _json_text(latest.get("diagnostic_state") or {}),
        "```",
        "",
        "## Jev decision result",
        "",
        "```json",
        _json_text(latest.get("jev_result") or {}),
        "```",
        "",
        "## Controlled research",
        "",
        "```json",
        _json_text(latest.get("research") or {}),
        "```",
        "",
        "## Safety screen",
        "",
        "```json",
        _json_text(latest.get("safety") or {}),
        "```",
        "",
        "## Timing / TechMedic telemetry",
        "",
        "```json",
        _json_text(telemetry),
        "```",
    ]
    return "\n".join(sections).rstrip() + "\n"


def build_diagnostic_bundle(case: dict[str, Any], turns: list[dict[str, Any]]) -> bytes:
    latest = turns[-1] if turns else {}
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    telemetry = ((latest.get("jev_result") or {}).get("_techmedic") or {}) if latest else {}

    manifest = {
        "bundle_format": 1,
        "techmedic_version": APP_VERSION,
        "generated_at_utc": generated_at,
        "case_id": case.get("id"),
        "case_title": case.get("title"),
        "case_status": case.get("status"),
        "turn_count": len(turns),
        "latest_turn_id": latest.get("id") if latest else None,
        "contents": [
            "00_COMBINED_REPORT.md",
            "01_SCREEN_OUTPUT.md",
            "02_LATEST_LLM_STRUCTURED_STATE.json",
            "03_LATEST_JEV_DECISION_RESULT.json",
            "04_LATEST_CONTROLLED_RESEARCH.json",
            "05_LATEST_SAFETY_SCREEN.json",
            "06_LATEST_TIMING_TELEMETRY.json",
            "07_CASE_HISTORY.md",
            "08_CASE_METADATA.json",
            "09_ALL_TURNS_RAW.json",
            "MANIFEST.json",
            "README.txt",
        ],
    }

    readme = f"""TechMedic v{APP_VERSION} diagnostic bundle

This ZIP is intended for one-click troubleshooting review and bug reporting.
It contains the user-visible case output plus the raw latest-turn diagnostic
state, Jev result, controlled research trace, safety result, timing telemetry,
case metadata, and the complete saved turn history.

No .env file or API keys are included by this exporter.

Recommended file to open first:
  00_COMBINED_REPORT.md

Generated (UTC): {generated_at}
Case: {case.get('title') or 'Untitled case'}
Turns: {len(turns)}
"""

    raw_turns = []
    for turn in turns:
        raw_turns.append({
            "id": turn.get("id"),
            "case_id": turn.get("case_id"),
            "user_text": turn.get("user_text"),
            "diagnostic_state": turn.get("diagnostic_state") or {},
            "jev_result": turn.get("jev_result") or {},
            "safety": turn.get("safety") or {},
            "research": turn.get("research") or {},
            "assistant_text": turn.get("assistant_text"),
            "created_at": turn.get("created_at"),
        })

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_COMBINED_REPORT.md", build_combined_report(case, turns))
        zf.writestr("01_SCREEN_OUTPUT.md", build_screen_output(case, turns))
        zf.writestr("02_LATEST_LLM_STRUCTURED_STATE.json", _json_text(latest.get("diagnostic_state") or {}))
        zf.writestr("03_LATEST_JEV_DECISION_RESULT.json", _json_text(latest.get("jev_result") or {}))
        zf.writestr("04_LATEST_CONTROLLED_RESEARCH.json", _json_text(latest.get("research") or {}))
        zf.writestr("05_LATEST_SAFETY_SCREEN.json", _json_text(latest.get("safety") or {}))
        zf.writestr("06_LATEST_TIMING_TELEMETRY.json", _json_text(telemetry))
        zf.writestr("07_CASE_HISTORY.md", build_case_history(case, turns))
        zf.writestr("08_CASE_METADATA.json", _json_text(case))
        zf.writestr("09_ALL_TURNS_RAW.json", _json_text(raw_turns))
        zf.writestr("MANIFEST.json", _json_text(manifest))
        zf.writestr("README.txt", readme)
    return buf.getvalue()
