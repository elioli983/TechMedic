from __future__ import annotations

from typing import Any

import copy
import hashlib
import json

from .models import normalize_diagnostic_state
from .candidate_response_guard import unsupported_closure
from .research_delta import integrate_research_delta_safely, safe_preview
from .consistency import remediation_readiness, response_issues

from . import database
from .jev import JevClient
from .llm import LLMClient
from .research import (
    ResearchClient, append_research_sources, linkify_research_citations,
    reconcile_research_source_ids,
)
from .safety import assess_candidate_tests
from .status import (
    derive_case_status, derive_effective_next_action, raw_next_action,
    remediation_has_blockers,
)


class DiagnosticEngine:
    def __init__(
        self,
        *,
        db_path,
        openai_api_key: str,
        openai_model: str,
        jev_api_key: str,
        jev_model: str,
        jev_api_url: str = "",
        web_research_enabled: bool = True,
        web_research_max_sources: int = 10,
    ) -> None:
        self.db_path = db_path
        self.llm = LLMClient(openai_api_key, openai_model)
        self.research = ResearchClient(
            openai_api_key,
            openai_model,
            enabled=web_research_enabled,
            max_sources=web_research_max_sources,
        )
        self.jev = JevClient(jev_api_key, jev_model, endpoint=jev_api_url)

    def run_cycle(self, case_id: str, user_text: str) -> dict[str, Any]:
        case = database.get_case(self.db_path, case_id)
        if not case:
            raise ValueError("Case not found")

        previous_state = database.get_latest_state(self.db_path, case_id)
        case_context = {
            "device_type": case.get("device_type", ""),
            "manufacturer": case.get("manufacturer", ""),
            "model": case.get("model", ""),
            "operating_system": case.get("operating_system", ""),
        }

        diagnostic_state = self.llm.update_state(
            latest_user_text=user_text,
            previous_state=previous_state,
            case_context=case_context,
        )
        llm_state_ms = self.llm.last_update_state_time_ms

        # v1.5 controlled research is analyst-gated. Most turns do not search.
        # When current documentation materially affects the decision, the
        # analyst emits one focused research_request and TechMedic performs a
        # web-grounded retrieval before Jev sees the final state.
        research_request = diagnostic_state.get("research_request")
        if not isinstance(research_request, dict):
            research_request = {}
        research_result = self.research.research(
            request=research_request,
            diagnostic_state=diagnostic_state,
        )

        llm_research_integration_ms: float | None = None
        integration_audit: dict[str, Any] = {
            "status": "skipped", "fallback_used": False,
            "validation_errors": [], "preserved_evidence": {}, "attempt_count": 0,
        }
        pre_research_state = copy.deepcopy(diagnostic_state)
        if research_result.get("performed"):
            # One normal attempt plus, if necessary, ONE bounded delta repair.
            # All candidates pass exactly the same source/evidence validator.
            candidate: Any = None
            for attempt in range(2):
                if attempt == 1 and not hasattr(self.llm, "repair_research_delta"):
                    break
                integration_audit["attempt_count"] += 1
                try:
                    if attempt == 0:
                        candidate = self.llm.integrate_research(
                            diagnostic_state=pre_research_state,
                            research_result=research_result,
                        )
                    else:
                        candidate = self.llm.repair_research_delta(
                            diagnostic_state=pre_research_state,
                            research_result=research_result,
                            errors=integration_audit["validation_errors"],
                            invalid_preview=integration_audit.get("rejected_candidate_preview", ""),
                        )
                    elapsed = getattr(self.llm, "last_integrate_research_time_ms", None)
                    if isinstance(elapsed, (float, int)):
                        llm_research_integration_ms = (llm_research_integration_ms or 0.0) + elapsed
                    safe = safe_preview(candidate)
                    # For accepted candidates, retain only a digest; the protected
                    # structured state is already saved separately in the bundle.
                    proposed_state, outcome = integrate_research_delta_safely(
                        pre_research_state, candidate, research_result,
                    )
                    if outcome["status"] == "accepted":
                        diagnostic_state = proposed_state
                        integration_audit.update(outcome)
                        integration_audit.update({k: safe[k] for k in ("candidate_sha256", "candidate_chars")})
                        integration_audit["recovered_after_retry"] = attempt == 1
                        reconcile_research_source_ids(diagnostic_state, research_result)
                        break
                    integration_audit.update(outcome)
                    integration_audit.update(safe)
                except Exception as exc:
                    elapsed = getattr(self.llm, "last_integrate_research_time_ms", None)
                    if isinstance(elapsed, (float, int)):
                        llm_research_integration_ms = (llm_research_integration_ms or 0.0) + elapsed
                    integration_audit.update({
                        "status": "error", "fallback_used": True,
                        "validation_errors": [f"integration exception ({type(exc).__name__})"],
                    })
                    raw = getattr(self.llm, "last_integrate_research_raw", "")
                    if raw:
                        integration_audit.update(safe_preview(raw))
                if attempt == 0:
                    integration_audit["first_attempt_errors"] = list(integration_audit["validation_errors"])
            else:
                pass
            if integration_audit["status"] != "accepted":
                diagnostic_state = normalize_diagnostic_state(pre_research_state)
                integration_audit["fallback_used"] = True

        # Failed/invalidated research cannot silently promote a compatibility-
        # sensitive remediation supplied by the initial analyst alone.
        if research_result.get("performed") and integration_audit["fallback_used"]:
            remediation = diagnostic_state.get("remediation")
            if not isinstance(remediation, dict):
                remediation = {}
                diagnostic_state["remediation"] = remediation
            remediation["selection_ready"] = False
            blockers = remediation.get("blocking_requirements")
            if not isinstance(blockers, list):
                blockers = []
            marker = "Research integration did not validate; confirm current compatibility before selecting an installation."
            if marker not in blockers:
                blockers.append(marker)
            remediation["blocking_requirements"] = blockers
            integration_audit["repair_gate_closed"] = True
        research_result.setdefault("_techmedic", {})["integration_validation"] = integration_audit
        # If integration did not validate, the retrieved web text is retained
        # for auditing but cannot be supplied as established repair evidence.
        research_integrated = integration_audit["status"] == "accepted"
        decision_research = research_result if research_integrated else {
            "performed": False, "brief": "", "sources": [], "citations": [],
            "error": "Research was retrieved but integration failed validation; no research-based fix is approved."
            if research_result.get("performed") else str(research_result.get("error") or ""),
            "_techmedic": {"integration_validation": integration_audit},
        }

        # Distinguish "not requested" from "attempted but failed" and
        # "retrieved but not validated". Preserve this exact status in the
        # responder payload, separately from source-backed research evidence.
        research_process_status = {
            "requested": bool(research_request.get("needed")),
            "retrieved": bool(research_result.get("performed")),
            "retrieval_failed": bool(research_result.get("error")),
            "integration_status": integration_audit["status"],
        }
        decision_research = copy.deepcopy(decision_research)
        decision_research["research_process_status"] = research_process_status

        safety = assess_candidate_tests(diagnostic_state)

        jev_state = dict(diagnostic_state)
        jev_state["safety_screen"] = safety
        if research_result.get("performed") or research_result.get("error"):
            jev_state["controlled_research"] = {
                "performed": research_integrated,
                "category": research_result.get("category", ""),
                "query": research_result.get("query", ""),
                "brief": research_result.get("brief", "") if research_integrated else "",
                "sources": research_result.get("sources", []) if research_integrated else [],
                "error": decision_research.get("error", ""),
                "integration_status": integration_audit["status"],
            }
        jev_result = self.jev.evaluate(jev_state)
        if getattr(self, "candidate_strict", False):
            JevClient._validate_lifecycle_scores(jev_result)

        # Apply Jev-backed lifecycle guardrails BEFORE the second LLM writes the
        # user-facing response. This lets the responder distinguish diagnosis,
        # remediation, and verification correctly.
        previous_status = None
        if isinstance(previous_state, dict):
            previous_status = str(previous_state.get("status") or "") or None
        if previous_status is None:
            previous_status = str(case.get("status") or "") or None

        effective_status = derive_case_status(
            diagnostic_state,
            jev_result,
            safety,
            previous_status=previous_status,
        )
        diagnostic_state["status"] = effective_status

        # Keep Jev's raw answer untouched for auditability, but expose a narrow
        # deterministic workflow guardrail to LLM #2 and the main UI.
        telemetry = jev_result.setdefault("_techmedic", {})
        if not isinstance(telemetry, dict):
            telemetry = {}
            jev_result["_techmedic"] = telemetry
        raw_action = raw_next_action(jev_result)
        effective_action = derive_effective_next_action(diagnostic_state, jev_result, effective_status)
        if research_result.get("performed") and integration_audit["fallback_used"] and effective_action in {
            "recommend_software_repair", "recommend_configuration_change", "verify_resolution", "finish_diagnosis",
        }:
            effective_action = "verify_compatibility"
        requested_command = any(term in user_text.lower() for term in (
            "exact command", "installation command", "powershell installation", "provide the command",
        ))
        if (requested_command and remediation_readiness(diagnostic_state)["ready"]
                and effective_action == "verify_compatibility"
                and str((diagnostic_state.get("remediation") or {}).get("install_command") or "").strip()):
            effective_action = "recommend_software_repair"
        telemetry["raw_next_action"] = raw_action
        telemetry["effective_next_action"] = effective_action
        telemetry["next_action_overridden"] = bool(effective_action and effective_action != raw_action)
        telemetry["previous_status"] = previous_status or ""
        telemetry["effective_status"] = effective_status
        telemetry["research_requested"] = bool(research_request.get("needed"))
        telemetry["research_performed"] = bool(research_result.get("performed"))
        telemetry["research_integrated"] = research_integrated
        telemetry["research_integration_status"] = integration_audit["status"]
        telemetry["research_response_provenance"] = dict(research_process_status)
        telemetry["research_integration_fallback_used"] = integration_audit["fallback_used"]
        telemetry["research_integration_validation_errors"] = integration_audit["validation_errors"]
        telemetry["research_preserved_evidence"] = integration_audit["preserved_evidence"]
        telemetry["research_source_count"] = len(research_result.get("sources") or [])
        telemetry["research_citation_count"] = len(research_result.get("citations") or [])
        telemetry["research_unmatched_citation_count"] = sum(
            not item.get("source_id") for item in (research_result.get("citations") or [])
            if isinstance(item, dict)
        )
        telemetry["research_invalid_integrated_source_ids"] = (
            (research_result.get("_techmedic") or {}).get("invalid_integrated_source_ids") or []
        )
        current_readiness = remediation_readiness(diagnostic_state)
        telemetry["remediation_blocked_by_prerequisites"] = not current_readiness["ready"]
        telemetry["current_remediation_ready"] = current_readiness["ready"]
        telemetry["current_remediation_blockers"] = current_readiness["blocking_requirements"]
        telemetry["historical_lifecycle_may_exceed_readiness"] = (
            effective_status == "remediation_identified" and not current_readiness["ready"]
        )
        telemetry["research_integration_attempts"] = integration_audit["attempt_count"]
        telemetry["research_integration_repaired"] = integration_audit.get("recovered_after_retry", False)
        research_ms = (research_result.get("_techmedic") or {}).get("research_response_time_ms")
        if isinstance(research_ms, (int, float)):
            telemetry["research_response_time_ms"] = round(float(research_ms), 1)

        assistant_text = self.llm.compose_response(
            diagnostic_state=diagnostic_state,
            jev_result=jev_result,
            safety=safety,
            research_result=decision_research,
        )
        llm_response_total_ms = self.llm.last_compose_response_time_ms or 0.0
        issues = response_issues(assistant_text, diagnostic_state, effective_action,
                                requested_command=requested_command,
                                research_context=research_process_status)
        if getattr(self, "candidate_strict", False) and unsupported_closure(assistant_text, effective_status):
            issues = list(issues) + ["Unverified case response asserts final resolution"]
        telemetry["responder_consistency_initial_issues"] = list(issues)
        if issues:
            # A single correction pass; never accept a still-inconsistent answer.
            telemetry["responder_repair_attempted"] = True
            telemetry["responder_repair_reason"] = issues
            telemetry["response_correction_status"] = "requested"
            telemetry["responder_retry_count"] = 1
            telemetry["last_rejected_response_preview"] = safe_preview(assistant_text, 600)["rejected_candidate_preview"]
            try:
                jev_result.setdefault("_techmedic", {})["response_correction"] = {
                    "errors": issues,
                    "instruction": "Fix every error. Follow effective action and current remediation readiness. Do not claim unsupported compatibility. Report whether research was NOT REQUESTED, retrieval FAILED, integration FAILED, or research was ACCEPTED, strictly as research_result.research_process_status records. If a vetted install_command exists and action is recommend_software_repair, include it exactly.",
                }
                revision = self.llm.compose_response(
                    diagnostic_state=diagnostic_state,
                    jev_result=jev_result, safety=safety, research_result=decision_research,
                )
                llm_response_total_ms += self.llm.last_compose_response_time_ms or 0.0
                issues = response_issues(revision, diagnostic_state, effective_action,
                                         requested_command=requested_command,
                                         research_context=research_process_status)
                if getattr(self, "candidate_strict", False) and unsupported_closure(revision, effective_status):
                    issues = list(issues) + ["Unverified case response asserts final resolution"]
                if not issues:
                    assistant_text = revision
                    telemetry["response_correction_status"] = "accepted"
                else:
                    telemetry["response_correction_status"] = "failed_safe"
            except Exception as exc:
                telemetry["response_correction_status"] = "failed_safe"
                telemetry["responder_retry_error"] = type(exc).__name__
            if telemetry["response_correction_status"] == "failed_safe":
                remediation = diagnostic_state.get("remediation") or {}
                # Safe fallback must respect the *effective action*, not just
                # remediation readiness: a verified case must not be reopened,
                # and an escalation must never become a local repair procedure.
                if effective_action == "finish_diagnosis" or effective_status == "resolution_verified":
                    assistant_text = ("### Resolution verified\nThe recorded verification evidence supports "
                                      "closing this case. No additional troubleshooting or repair is "
                                      "required for the resolved symptom. Reopen only if new contradictory "
                                      "observations are supplied.\n")
                elif effective_action == "escalate":
                    assistant_text = ("### Current assessment\nThe observed issue warrants qualified "
                                      "professional service. The specific internal component and repair "
                                      "remain unconfirmed.\n\n### Next step\nContact a qualified "
                                      "service technician and provide the existing observations and "
                                      "completed tests. Do not open the chassis or perform electrical "
                                      "measurements yourself.\n")
                elif not remediation_readiness(diagnostic_state)["ready"]:
                    blockers = remediation.get("blocking_requirements") or ["A required compatibility prerequisite remains unresolved."]
                    assistant_text = ("### Current assessment\nThe established diagnosis has been retained. "
                                      "A previously identified remediation milestone does not mean the current procedure is ready.\n\n"
                                      "### Next step\nVerify the remaining prerequisite before making a change: "
                                      + "; ".join(map(str, blockers[:3])) + "\n")
                elif effective_action == "verify_compatibility":
                    # Ready does not override the effective compatibility action.
                    assistant_text = ("### Current assessment\nThe established diagnosis is retained.\n\n"
                                      "### Next step\nVerify compatibility before making changes; "
                                      "do not execute an installation procedure yet.\n")
                elif effective_action == "recommend_software_repair":
                    cmd = str(remediation.get("install_command") or "").strip()
                    checks = remediation.get("verification_commands") or []
                    assistant_text = ("### Current assessment\nA specific corrective procedure has been identified. "
                                      "This does not establish that the repair has succeeded.\n\n"
                                      "### Next step\n" + ("```powershell\n" + cmd + "\n```\n" if cmd else str(remediation.get("summary") or ""))
                                      + ("\n### Verify afterward\n```powershell\n" + "\n".join(checks) + "\n```" if checks else ""))
                else:
                    assistant_text = ("### Current assessment\nThe recorded diagnosis and safety "
                                      "restrictions are unchanged.\n\n### Next step\nFollow the "
                                      "effective workflow action and confirm prerequisites with a "
                                      "qualified support provider before attempting a change.\n")
        else:
            telemetry["response_correction_status"] = "not_needed"
        llm_response_ms = llm_response_total_ms
        assistant_text = linkify_research_citations(assistant_text, decision_research)
        assistant_text = append_research_sources(assistant_text, decision_research)

        if isinstance(llm_state_ms, (int, float)):
            telemetry["llm_state_response_time_ms"] = round(float(llm_state_ms), 1)
        if isinstance(llm_research_integration_ms, (int, float)):
            telemetry["llm_research_integration_response_time_ms"] = round(
                float(llm_research_integration_ms), 1
            )
        if isinstance(llm_response_ms, (int, float)):
            telemetry["llm_responder_response_time_ms"] = round(float(llm_response_ms), 1)

        llm_parts = [value for value in (llm_state_ms, llm_research_integration_ms, llm_response_ms) if isinstance(value, (int, float))]
        if llm_parts:
            telemetry["llm_response_time_ms"] = round(sum(float(value) for value in llm_parts), 1)

        jev_ms = telemetry.get("jev_response_time_ms")
        llm_total_ms = telemetry.get("llm_response_time_ms")
        research_total_ms = telemetry.get("research_response_time_ms", 0.0)
        if isinstance(jev_ms, (int, float)) and isinstance(llm_total_ms, (int, float)):
            total = float(jev_ms) + float(llm_total_ms)
            if isinstance(research_total_ms, (int, float)):
                total += float(research_total_ms)
            telemetry["total_ai_processing_time_ms"] = round(total, 1)

        device = diagnostic_state.get("device") if isinstance(diagnostic_state.get("device"), dict) else {}
        case_changes = dict(
            title=diagnostic_state.get("case_summary") or case.get("title") or "TechMedic case",
            status=effective_status,
            device_type=str(device.get("type") or "").strip() or None,
            manufacturer=str(device.get("manufacturer") or "").strip() or None,
            model=str(device.get("model") or "").strip() or None,
            operating_system=str(device.get("operating_system") or "").strip() or None,
        )
        if getattr(self, "candidate_persist", None) is not None:
            self.candidate_persist(
                case_id=case_id, user_text=user_text,
                diagnostic_state=diagnostic_state, jev_result=jev_result,
                safety=safety, assistant_text=assistant_text, research=research_result,
                case_changes=case_changes,
            )
        else:
            database.add_turn(self.db_path, case_id, user_text, diagnostic_state,
                              jev_result, safety, assistant_text, research=research_result)
            database.update_case(self.db_path, case_id, **case_changes)

        return {
            "diagnostic_state": diagnostic_state,
            "jev_result": jev_result,
            "safety": safety,
            "research": research_result,
            "assistant_text": assistant_text,
        }
