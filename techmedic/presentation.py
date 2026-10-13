from __future__ import annotations

ACTION_LABELS = {
    "ask_for_information": "Ask for information",
    "collect_system_information": "Collect system information",
    "run_diagnostic_test": "Run diagnostic test",
    "verify_compatibility": "Verify compatibility",
    "recommend_configuration_change": "Recommend configuration change",
    "recommend_software_repair": "Recommend software repair",
    "recommend_hardware_inspection": "Recommend hardware inspection",
    "verify_resolution": "Verify resolution",
    "finish_diagnosis": "Finish diagnosis",
    "escalate": "Escalate",
}

STATUS_LABELS = {
    "investigating": "Investigating",
    "possible_diagnosis": "Possible Diagnosis",
    "diagnosis_established": "Diagnosis Established",
    "remediation_identified": "Remediation Identified",
    "resolution_verified": "Resolution Verified",
    # Backward-compatible display only for cases saved by v1.4.2. New turns
    # never use escalation as a lifecycle state.
    "escalate": "Escalate (legacy status)",
}


def friendly_action(value: str | None) -> str:
    if not value:
        return "—"
    return ACTION_LABELS.get(value, value.replace("_", " ").strip().title())


def friendly_status(value: str | None) -> str:
    if not value:
        return "Investigating"
    return STATUS_LABELS.get(value, value.replace("_", " ").strip().title())
