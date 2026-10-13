from __future__ import annotations

from typing import Any
from .candidate_context import candidate_active


# "Possible diagnosis" is intentionally much lower than "diagnosis established".
# It represents a coherent leading cause that still needs discriminating evidence.
POSSIBLE_DIAGNOSIS_THRESHOLD = 0.20
DIAGNOSIS_ESTABLISHED_THRESHOLD = 0.85
# A second route allows LLM #1 + Jev semantic consensus to establish a diagnosis
# without requiring Jev to assign near-root-cause certainty. This is intentionally
# NOT a simple lowering of DIAGNOSIS_ESTABLISHED_THRESHOLD: the analyst must
# explicitly classify the case at/after Diagnosis Established and supply multiple
# concrete basis items, while Jev must still provide non-trivial support.
ANALYST_ESTABLISHED_JEV_FLOOR = 0.30
ANALYST_ESTABLISHED_MIN_BASIS = 2
REMEDIATION_IDENTIFIED_THRESHOLD = 0.75
RESOLUTION_VERIFIED_THRESHOLD = 0.85

LIFECYCLE_ORDER = {
    "investigating": 0,
    "possible_diagnosis": 1,
    "diagnosis_established": 2,
    "remediation_identified": 3,
    "resolution_verified": 4,
}


def _answer_value(jev_result: dict[str, Any], name: str, field: str, default: Any = None) -> Any:
    answers = jev_result.get("answers") if isinstance(jev_result, dict) else None
    if not isinstance(answers, dict):
        return default
    answer = answers.get(name)
    if not isinstance(answer, dict):
        return default
    return answer.get(field, default)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _nested_text(state: dict[str, Any], group: str, key: str) -> str:
    value = state.get(group)
    if not isinstance(value, dict):
        return ""
    return str(value.get(key) or "").strip()


def diagnostic_confidence(jev_result: dict[str, Any]) -> float:
    """Return Jev's probability that the diagnosis is established.

    v1.4+ uses the dedicated diagnosis_established Noul. The
    evidence_sufficient fallback keeps previously saved v1.3-style Jev
    fixtures understandable.
    """
    direct = _answer_value(jev_result, "diagnosis_established", "noul", None)
    if direct is not None:
        return _number(direct)
    return _number(_answer_value(jev_result, "evidence_sufficient", "noul", 0.0))


def remediation_confidence(jev_result: dict[str, Any]) -> float:
    return _number(_answer_value(jev_result, "remediation_identified", "noul", 0.0))


def resolution_confidence(jev_result: dict[str, Any]) -> float:
    return _number(_answer_value(jev_result, "resolution_verified", "noul", 0.0))


def raw_next_action(jev_result: dict[str, Any]) -> str:
    return str(_answer_value(jev_result, "next_action", "choice", "") or "")


def _reopen_requested(diagnostic_state: dict[str, Any]) -> bool:
    control = diagnostic_state.get("lifecycle_control")
    if not isinstance(control, dict):
        return False
    requested = bool(control.get("reopen"))
    reason = str(control.get("reason") or "").strip()
    return requested and bool(reason)


_PRECONDITION_STARTS = (
    "identify ", "confirm ", "select ", "determine ", "establish ",
    "check ", "research ", "obtain ", "find ", "verify compatibility",
    "verify support", "verify that ", "validate compatibility",
)


def remediation_has_blockers(diagnostic_state: dict[str, Any]) -> bool:
    """Guard against confusing a generic repair strategy with a ready fix.

    Explicit selection_readiness is authoritative for current v1.5.2 states.
    The legacy fallback recognizes clear unfulfilled preconditions from v1.5.1
    records, including the original GTX 1080 turn. It deliberately does not
    treat post-change verification as a precondition to *identifying* a repair.
    """
    remediation = diagnostic_state.get("remediation")
    if not isinstance(remediation, dict):
        return False
    if remediation.get("selection_ready") is False:
        return True
    if remediation.get("blocking_requirements"):
        return True
    if remediation.get("selection_ready") is True:
        return False
    requirements = remediation.get("requirements")
    if not isinstance(requirements, list):
        return False
    for value in requirements:
        requirement = str(value).strip().lower()
        if any(requirement.startswith(prefix) for prefix in _PRECONDITION_STARTS):
            # A check to verify resolution is not a missing prerequisite to the fix.
            if any(x in requirement for x in ("after applying", "after the change", "post-remediation", "post-change")):
                continue
            return True
    return False


def derive_case_status(
    diagnostic_state: dict[str, Any],
    jev_result: dict[str, Any],
    safety: dict[str, Any] | None = None,
    *,
    previous_status: str | None = None,
) -> str:
    """Derive the case lifecycle from LLM state plus Jev judgments.

    Normal lifecycle progression is monotonic:
      investigating -> possible_diagnosis -> diagnosis_established ->
      remediation_identified -> resolution_verified

    The analyst can explicitly request a regression only when new evidence
    contradicts a previously established diagnosis/remediation. Escalation is
    a workflow action, not a lifecycle state, so it never replaces the five
    diagnostic lifecycle states.
    """
    llm_status = str(diagnostic_state.get("status") or "investigating")
    next_action = raw_next_action(jev_result)

    diag_p = diagnostic_confidence(jev_result)
    remediation_p = remediation_confidence(jev_result)
    resolution_p = resolution_confidence(jev_result)

    diagnosis_summary = _nested_text(diagnostic_state, "diagnosis", "summary")
    diagnosis_group = diagnostic_state.get("diagnosis")
    diagnosis_basis = diagnosis_group.get("basis") if isinstance(diagnosis_group, dict) else []
    diagnosis_basis_count = len(diagnosis_basis) if isinstance(diagnosis_basis, list) else 0
    remediation_summary = _nested_text(diagnostic_state, "remediation", "summary")
    verification = diagnostic_state.get("resolution_verification")
    verified_by_state = bool(verification.get("verified")) if isinstance(verification, dict) else False

    # Compatibility with older states that used only possible_resolution.
    legacy_resolution = str(diagnostic_state.get("possible_resolution") or "").strip()
    if not diagnosis_summary and llm_status in {"possible_diagnosis", "diagnosed"}:
        diagnosis_summary = legacy_resolution

    analyst_established = (
        llm_status in {"diagnosis_established", "remediation_identified", "resolution_verified"}
        and bool(diagnosis_summary)
        and diagnosis_basis_count >= ANALYST_ESTABLISHED_MIN_BASIS
        and diag_p >= ANALYST_ESTABLISHED_JEV_FLOOR
    )
    diagnosis_supported = diag_p >= DIAGNOSIS_ESTABLISHED_THRESHOLD or analyst_established
    # Candidate: the Jev probability is not evidence by itself. Preserve any
    # concrete basis, observation or performed test as an acceptable trace.
    if candidate_active.get():
        diagnosis_supported = diagnosis_supported and diagnostic_trace_present(diagnostic_state)

    # Resolution requires actual post-remediation evidence, not merely a proposed fix.
    if (
        diagnosis_supported
        and resolution_p >= RESOLUTION_VERIFIED_THRESHOLD
        and verified_by_state
        and (not candidate_active.get() or valid_post_change_check(diagnostic_state))
    ):
        candidate = "resolution_verified"
    # A remediation milestone means both the cause and a specific corrective path are well supported.
    elif (
        diagnosis_supported
        and remediation_p >= REMEDIATION_IDENTIFIED_THRESHOLD
        and remediation_summary
        and not remediation_has_blockers(diagnostic_state)
    ):
        candidate = "remediation_identified"
    # A diagnosis can be established even when the exact compatible repair is still unknown.
    elif diagnosis_supported and diagnosis_summary:
        candidate = "diagnosis_established"
    # A coherent leading diagnosis can exist well before a diagnosis is established.
    elif diagnosis_summary and diag_p >= POSSIBLE_DIAGNOSIS_THRESHOLD:
        candidate = "possible_diagnosis"
    else:
        candidate = "investigating"

    # Prevent ordinary evidence updates from moving a case backwards. This was
    # observed during the DNS regression test (remediation_identified ->
    # possible_diagnosis after the fix was applied). A backwards move is allowed
    # only when the analyst explicitly marks new evidence as contradictory.
    if previous_status in LIFECYCLE_ORDER and candidate in LIFECYCLE_ORDER:
        if LIFECYCLE_ORDER[candidate] < LIFECYCLE_ORDER[previous_status] and not _reopen_requested(diagnostic_state):
            return previous_status

    return candidate


def derive_effective_next_action(
    diagnostic_state: dict[str, Any],
    jev_result: dict[str, Any],
    effective_status: str,
) -> str:
    """Return the workflow action TechMedic should expose to LLM #2 and the UI.

    Jev remains the primary action chooser. Deterministic overrides are kept
    deliberately narrow and are recorded separately so the raw Jev answer is
    still auditable in Developer Trace.
    """
    raw = raw_next_action(jev_result)

    # Once post-remediation evidence verifies the original symptom is resolved,
    # the diagnostic loop must terminate. Non-blocking caveats may be stated as
    # closing notes, but they should not reopen information gathering.
    if effective_status == "resolution_verified":
        return "finish_diagnosis"

    if candidate_active.get() and raw == "finish_diagnosis":
        return "verify_resolution" if _nested_text(diagnostic_state, "remediation", "summary") else "ask_for_information"
    if candidate_active.get() and not diagnostic_trace_present(diagnostic_state) and raw in {
        "recommend_software_repair", "recommend_configuration_change"
    }:
        return "collect_system_information"

    # Jev can rate a generic remedy highly even when compatibility/prerequisite
    # work remains open. Keep its original choice in the trace and request the
    # missing verification instead of issuing an unsupported repair instruction.
    if (remediation_has_blockers(diagnostic_state)
            and raw in {"recommend_software_repair", "recommend_configuration_change", "verify_resolution"}):
        research_request = diagnostic_state.get("research_request") or {}
        if (isinstance(research_request, dict) and research_request.get("category") in
                {"compatibility", "driver", "firmware"}):
            return "verify_compatibility"
        return "collect_system_information"

    return raw


# Pass 15 candidate evidence gates: structural plausibility only, not factual proof.
def diagnostic_trace_present(state: dict[str, Any]) -> bool:
    diag = state.get("diagnosis") or {}
    if isinstance(diag, dict) and any(isinstance(v, str) and v.strip() for v in (diag.get("basis") or [])):
        return True
    for entry in state.get("tests_performed") or []:
        if isinstance(entry, dict) and str(entry.get("test") or "").strip() and str(entry.get("result") or "").strip():
            return True
    return any(isinstance(v, str) and v.strip() for v in (state.get("observations") or []))


def valid_post_change_check(state: dict[str, Any]) -> bool:
    ver = state.get("resolution_verification") or {}
    if not isinstance(ver, dict) or ver.get("verified") is not True:
        return False
    checks = ver.get("post_change_checks") or []
    if not isinstance(checks, list):
        return False
    for c in checks:
        if not isinstance(c, dict):
            continue
        if (c.get("post_change") is True and c.get("retested_original_symptom") is True
                and c.get("result") == "passed"
                and c.get("source_type") in {"user_observation", "diagnostic_test"}
                and str(c.get("original_symptom") or "").strip()
                and str(c.get("observation") or "").strip()):
            return True
    return False
