from __future__ import annotations

from typing import Any
from .candidate_context import candidate_active


ALLOWED_STATUSES = {
    "investigating",
    "possible_diagnosis",
    "diagnosis_established",
    "remediation_identified",
    "resolution_verified",
}


def normalize_diagnostic_state(value: dict[str, Any] | None) -> dict[str, Any]:
    """Return a predictable v1.5 diagnostic-state shape even if an LLM omits fields."""
    value = value if isinstance(value, dict) else {}

    device = value.get("device") if isinstance(value.get("device"), dict) else {}
    diagnosis = value.get("diagnosis") if isinstance(value.get("diagnosis"), dict) else {}
    remediation = value.get("remediation") if isinstance(value.get("remediation"), dict) else {}
    verification = (
        value.get("resolution_verification")
        if isinstance(value.get("resolution_verification"), dict)
        else {}
    )
    lifecycle_control = (
        value.get("lifecycle_control")
        if isinstance(value.get("lifecycle_control"), dict)
        else {}
    )
    research_request = (
        value.get("research_request")
        if isinstance(value.get("research_request"), dict)
        else {}
    )
    research_evidence = (
        value.get("research_evidence")
        if isinstance(value.get("research_evidence"), dict)
        else {}
    )

    state = {
        "case_summary": str(value.get("case_summary") or "Technical problem under investigation"),
        "device": {
            "type": str(device.get("type") or ""),
            "manufacturer": str(device.get("manufacturer") or ""),
            "model": str(device.get("model") or ""),
            "operating_system": str(device.get("operating_system") or ""),
            "application": str(device.get("application") or ""),
        },
        "symptoms": _string_list(value.get("symptoms")),
        "observations": _string_list(value.get("observations")),
        "tests_performed": _dict_list(value.get("tests_performed"), {"test", "result"}),
        "hypotheses": _dict_list(value.get("hypotheses"), {"name", "rationale"}),
        "missing_information": _string_list(value.get("missing_information")),
        "candidate_next_tests": _dict_list(
            value.get("candidate_next_tests"),
            {"name", "instructions", "purpose", "risk"},
        )[:3],
        "diagnosis": {
            "summary": str(diagnosis.get("summary") or ""),
            "basis": _string_list(diagnosis.get("basis")),
        },
        "remediation": {
            "summary": str(remediation.get("summary") or ""),
            "requirements": _string_list(remediation.get("requirements")),
            "selection_ready": _optional_bool(remediation.get("selection_ready")),
            "blocking_requirements": _string_list(remediation.get("blocking_requirements")),
            "install_command": str(remediation.get("install_command") or ""),
            "verification_commands": _string_list(remediation.get("verification_commands")),
            "confidence_note": str(remediation.get("confidence_note") or ""),
        },
        "resolution_verification": {
            "verified": _bool_value(verification.get("verified")),
            "evidence": _string_list(verification.get("evidence")),
            **({"post_change_checks": [
                {
                    "original_symptom": str(item.get("original_symptom") or "").strip(),
                    "post_change": item.get("post_change") is True,
                    "retested_original_symptom": item.get("retested_original_symptom") is True,
                    "result": str(item.get("result") or "").strip().lower(),
                    "source_type": str(item.get("source_type") or "").strip().lower(),
                    "observation": str(item.get("observation") or "").strip(),
                }
                for item in (verification.get("post_change_checks") or [])[:20]
                if isinstance(item, dict)
            ] if isinstance(verification.get("post_change_checks"), list) else []} if candidate_active.get() else {}),
        },
        "lifecycle_control": {
            "reopen": _bool_value(lifecycle_control.get("reopen")),
            "reason": str(lifecycle_control.get("reason") or ""),
        },
        "research_request": {
            "needed": _bool_value(research_request.get("needed")),
            "category": _research_category(research_request.get("category")),
            "query": str(research_request.get("query") or ""),
            "reason": str(research_request.get("reason") or ""),
        },
        "research_evidence": {
            "summary": str(research_evidence.get("summary") or ""),
            "source_ids": _string_list(research_evidence.get("source_ids")),
            "category": _research_category(research_evidence.get("category")),
            "query": str(research_evidence.get("query") or ""),
        },
        # Retained for compatibility with v1.0-v1.3 saved states and exports.
        "possible_resolution": str(value.get("possible_resolution") or remediation.get("summary") or ""),
        "status": str(value.get("status") or "investigating"),
    }
    if state["status"] == "diagnosed":
        state["status"] = "diagnosis_established"
    if state["status"] not in ALLOWED_STATUSES:
        state["status"] = "investigating"
    return state


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return _bool_value(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _dict_list(value: Any, keys: set[str]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            out.append({key: str(item.get(key) or "") for key in keys})
    return out


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def _research_category(value: Any) -> str:
    allowed = {"", "compatibility", "driver", "firmware", "manufacturer_support", "release_notes", "documentation", "warranty_service", "other"}
    text = str(value or "").strip().lower()
    return text if text in allowed else "other"
