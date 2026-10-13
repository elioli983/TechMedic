"""Validated, evidence-preserving research integration for TechMedic v1.5.3.

The LLM output is NOT authoritative until validated. In particular, JSON shape
normalization must never convert an incomplete response into a replacement
state that erases user-supplied observations, tests, or the diagnosis.
"""
from __future__ import annotations

import copy
from typing import Any

from .models import ALLOWED_STATUSES, normalize_diagnostic_state

# These keys must be present in the RAW integration response. Checking only
# the normalized output would conceal missing fields behind empty defaults.
_REQUIRED_TYPES: dict[str, type] = {
    "case_summary": str,
    "device": dict,
    "symptoms": list,
    "observations": list,
    "tests_performed": list,
    "hypotheses": list,
    "missing_information": list,
    "candidate_next_tests": list,
    "diagnosis": dict,
    "remediation": dict,
    "resolution_verification": dict,
    "lifecycle_control": dict,
    "research_request": dict,
    "research_evidence": dict,
    "status": str,
}
_REQUIRED_NESTED = {
    "device": ("type", "manufacturer", "model", "operating_system", "application"),
    "diagnosis": ("summary", "basis"),
    "remediation": ("summary", "requirements", "selection_ready", "blocking_requirements"),
    "research_evidence": ("summary", "source_ids", "category", "query"),
    "research_request": ("needed", "category", "query", "reason"),
    "resolution_verification": ("verified", "evidence"),
    "lifecycle_control": ("reopen", "reason"),
}
_UNKNOWN = {"", "unknown", "not known", "not specified", "not provided", "undetermined", "n/a", "none"}


def _known(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() not in _UNKNOWN


def _append_unique(before: list[Any], after: list[Any]) -> tuple[list[Any], int]:
    # Preserve original ordering and every established item. The model can
    # append research-specific notes, but cannot remove local test evidence.
    combined = copy.deepcopy(before)
    for item in after:
        if item not in combined:
            combined.append(copy.deepcopy(item))
    return combined, len([x for x in before if x not in after])


def integrate_research_safely(
    pre_research_state: dict[str, Any],
    candidate: Any,
    research_result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate RAW candidate, merge protected evidence or fall back atomically.

    Returns (effective_state, audit). For unsafe candidates the returned state
    is the pre-research state, and the caller must not use research as support
    for a repair recommendation. No partial/unvalidated state reaches Jev.
    """
    before = normalize_diagnostic_state(pre_research_state)
    errors: list[str] = []
    restored: dict[str, int] = {}
    if not isinstance(candidate, dict):
        errors.append("integration output is not a JSON object")
        candidate = {}
    for name, expected in _REQUIRED_TYPES.items():
        if not isinstance(candidate.get(name), expected):
            errors.append(f"missing or invalid {name} ({expected.__name__})")
    for group, keys in _REQUIRED_NESTED.items():
        obj = candidate.get(group)
        if isinstance(obj, dict):
            for key in keys:
                if key not in obj:
                    errors.append(f"missing {group}.{key}")
    if str(candidate.get("status") or "") not in ALLOWED_STATUSES:
        errors.append("invalid integration lifecycle state")
    if errors:
        return before, {"status": "rejected", "fallback_used": True,
                        "validation_errors": errors, "preserved_evidence": restored}

    after = normalize_diagnostic_state(candidate)
    if before["case_summary"] != "Technical problem under investigation" and (
        after["case_summary"] == "Technical problem under investigation" or
        len(after["case_summary"].strip()) < 12
    ):
        errors.append("case summary lost meaningful information")

    for field in ("type", "manufacturer", "model", "operating_system", "application"):
        old, new = before["device"][field], after["device"][field]
        if _known(old) and not _known(new):
            after["device"][field] = old
            restored[f"device.{field}"] = 1
        # Research cannot change verified local device identity; a contradiction
        # requires a new user observation and lifecycle reopening, not a web page.
        elif _known(old) and _known(new) and old.casefold() != new.casefold():
            # An external page cannot rewrite the locally identified device.
            # Keep the recorded identity, without mistaking harmless changes
            # such as "GTX 1080" -> "GeForce GTX 1080" for a new device.
            after["device"][field] = old
            restored[f"device.{field}"] = 1

    for field in ("symptoms", "observations", "tests_performed"):
        combined, count = _append_unique(before[field], after[field])
        after[field] = combined
        if count:
            restored[field] = count
    # Existing diagnosis basis must remain traceable even after research.
    combined, count = _append_unique(before["diagnosis"]["basis"], after["diagnosis"]["basis"])
    after["diagnosis"]["basis"] = combined
    if count:
        restored["diagnosis.basis"] = count
    if _known(before["diagnosis"]["summary"]) and not _known(after["diagnosis"]["summary"]):
        errors.append("established diagnosis was erased")

    # Never accept changes to local verification merely because documentation
    # exists. Only another *local* diagnostic turn may verify resolution.
    if before["resolution_verification"]["verified"] != after["resolution_verification"]["verified"]:
        errors.append("documentation integration changed local resolution verification")
    after["resolution_verification"] = copy.deepcopy(before["resolution_verification"])
    if after["lifecycle_control"]["reopen"] and not before["lifecycle_control"]["reopen"]:
        errors.append("documentation integration attempted to reopen lifecycle")
    after["lifecycle_control"] = copy.deepcopy(before["lifecycle_control"])

    # An LLM cannot erase existing blockers without providing a specific repair
    # and at least one cited primary source. Source IDs alone are not proof of
    # technical correctness, but this ensures traceability and fail-closed flow.
    requested_ids = after["research_evidence"]["source_ids"]
    cited_sources = {
        str(x.get("id")) for x in research_result.get("sources", [])
        if isinstance(x, dict) and x.get("cited_in_research") is not False
        and x.get("primary_source") is True
    }
    if not _known(after["research_evidence"]["summary"]) or not requested_ids:
        errors.append("completed research has no integrated, attributed conclusion")
    elif not any(i in cited_sources for i in requested_ids):
        errors.append("integrated research does not cite a primary source")
    if any(i not in {str(s.get("id")) for s in research_result.get("sources", [])
                      if isinstance(s, dict) and s.get("cited_in_research") is not False}
           for i in requested_ids):
        errors.append("integrated research references invalid or uncited source IDs")

    if before["remediation"]["selection_ready"] is False and after["remediation"]["selection_ready"] is None:
        errors.append("remediation selection readiness became unknown")
    if before["remediation"]["blocking_requirements"] and not after["remediation"]["blocking_requirements"]:
        if not after["remediation"]["selection_ready"] or not _known(after["remediation"]["summary"]):
            errors.append("remediation prerequisites disappeared without supported selection")
    if after["remediation"]["selection_ready"] is True and (
        not _known(after["remediation"]["summary"]) or not requested_ids or
        not any(i in cited_sources for i in requested_ids)
    ):
        errors.append("remediation marked ready without attributable supporting evidence")
    if before["status"] in {"diagnosis_established", "remediation_identified", "resolution_verified"} and not _known(after["diagnosis"]["summary"]):
        errors.append("previously established diagnosis lost during integration")

    if errors:
        return before, {"status": "rejected", "fallback_used": True,
                        "validation_errors": errors, "preserved_evidence": restored}
    return after, {"status": "accepted", "fallback_used": False,
                   "validation_errors": [], "preserved_evidence": restored}
