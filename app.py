from __future__ import annotations

import streamlit as st

from techmedic import database
from techmedic.config import get_settings
from techmedic.diagnostic_engine import DiagnosticEngine
from techmedic.jev import JevClient
from techmedic.presentation import friendly_action, friendly_status
from techmedic.export_bundle import build_diagnostic_bundle, bundle_filename
from techmedic import candidate_journal as journal
from techmedic.candidate_handoff import build_handoff
from techmedic.candidate_fakes import make_fake_engine
from techmedic.config import PROJECT_ROOT
from dataclasses import replace
import os
import uuid
import time


st.set_page_config(page_title="TechMedic", page_icon="🩺", layout="wide")
# Fail closed on database isolation: never read or alter the accepted release DB.
settings = replace(get_settings(), database_path=PROJECT_ROOT / 'data' / 'techmedic_v1_5_6.sqlcipher')
try:
    journal.ensure(settings.database_path)
except Exception as exc:
    st.error(f'Protected journal startup failed ({type(exc).__name__}). Check SQLCipher installation, Windows profile, and original DPAPI key files. See SQLCIPHER_STORAGE.md.')
    st.stop()
# Live requests are opt-in, and OFF by default for experimental validation.
LIVE_ALLOWED = os.getenv('TECHMEDIC_V156_ALLOW_LIVE', '') == 'I_ACCEPT_LIVE_API_CALLS'


if "active_case_id" not in st.session_state:
    st.session_state.active_case_id = None
if "web_research_enabled" not in st.session_state:
    st.session_state.web_research_enabled = settings.web_research_enabled


def rerun() -> None:
    st.rerun()


def engine() -> DiagnosticEngine:
    if not LIVE_ALLOWED or not bool(st.session_state.get('pass15_live_enabled', False)):
        return make_fake_engine(settings.database_path)
    return DiagnosticEngine(
        db_path=settings.database_path,
        openai_api_key=settings.openai_api_key,
        openai_model=settings.openai_model,
        jev_api_key=settings.jev_api_key,
        jev_model=settings.jev_model,
        jev_api_url=settings.jev_api_url,
        web_research_enabled=bool(st.session_state.web_research_enabled),
        web_research_max_sources=settings.web_research_max_sources,
    )


def percent(value) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def seconds_metric(value) -> str:
    return f"{float(value) / 1000:.2f} s" if isinstance(value, (int, float)) else "—"


def render_assessment(turn: dict) -> None:
    answers = (turn.get("jev_result") or {}).get("answers", {})
    fault = answers.get("fault_domain", {})
    evidence = answers.get("evidence_sufficient", {})
    diagnosis = answers.get("diagnosis_established", {})
    remediation = answers.get("remediation_identified", {})
    resolution = answers.get("resolution_verified", {})
    hardware = answers.get("hardware_failure_likely", {})
    service = answers.get("professional_service_needed", {})
    urgency = answers.get("urgency", {})
    action = answers.get("next_action", {})
    telemetry = (turn.get("jev_result") or {}).get("_techmedic", {})

    st.subheader("Current assessment")

    cols = st.columns([1.35, 1, 1, 1])
    fault_choice = fault.get("choice", "—")
    if fault_choice == "unknown":
        cols[0].metric("Fault domain", "Not yet determined")
        cols[0].caption(
            f"Insufficient domain evidence · Jev unresolved-domain confidence: {percent(fault.get('confidence'))}"
        )
    else:
        cols[0].metric("Likely domain", str(fault_choice).replace("_", " ").title())
        cols[0].caption(f"Jev choice confidence: {percent(fault.get('confidence'))}")

    cols[1].metric("Evidence sufficient", percent(evidence.get("noul")))
    cols[1].caption("General evidence sufficiency")
    cols[2].metric("Diagnostic confidence", percent(diagnosis.get("noul")))
    cols[2].caption("Jev: diagnosis established")
    cols[3].metric("Remediation confidence", percent(remediation.get("noul")))
    cols[3].caption(f"Resolution verified: {percent(resolution.get('noul'))}")

    cols = st.columns(3)
    cols[0].metric("Hardware failure likely", percent(hardware.get("noul")))
    urgency_score = urgency.get("score")
    cols[1].metric(
        "Urgency score",
        f"{urgency_score:.2f} / 3" if isinstance(urgency_score, (int, float)) else "—",
    )
    cols[2].metric("Professional service", percent(service.get("noul")))

    cols = st.columns([2.25, 1, 1, 1])
    raw_action_choice = action.get("choice")
    effective_action_choice = telemetry.get("effective_next_action") or raw_action_choice
    overridden = bool(
        effective_action_choice
        and raw_action_choice
        and effective_action_choice != raw_action_choice
    )
    cols[0].metric("TechMedic next action", friendly_action(effective_action_choice))
    if overridden:
        cols[0].caption(
            "Lifecycle guardrail override · "
            f"Jev proposed {friendly_action(raw_action_choice)} "
            f"({percent(action.get('confidence'))})"
        )
    else:
        cols[0].caption(f"Jev choice confidence: {percent(action.get('confidence'))}")

    cols[1].metric("LLM response time", seconds_metric(telemetry.get("llm_response_time_ms")))
    cols[1].caption("LLM analysis/integration + response")
    cols[2].metric("Jev response time", seconds_metric(telemetry.get("jev_response_time_ms")))
    cols[2].caption("HTTP round trip")
    cols[3].metric("Total AI processing", seconds_metric(telemetry.get("total_ai_processing_time_ms")))
    cols[3].caption("LLM + web research + Jev" if telemetry.get("research_performed") else "LLM + Jev")

    research = turn.get("research") or {}
    if research.get("performed"):
        research_meta = research.get("_techmedic") or {}
        integration = research_meta.get("integration_validation") or {}
        if integration.get("fallback_used"):
            st.error("Research integration failed validation; previous diagnostic evidence was preserved and research-backed repair is not approved.")
        source_count = len(research.get("sources") or [])
        st.info(
            f"Controlled web research used · {source_count} source(s) · "
            f"{seconds_metric(research_meta.get('research_response_time_ms'))}"
        )
    elif research.get("error"):
        st.warning(str(research.get("error")))


def render_history(turns: list[dict]) -> None:
    st.subheader("Diagnostic conversation")
    for turn in turns:
        with st.chat_message("user"):
            st.markdown(turn["user_text"])
        with st.chat_message("assistant"):
            st.markdown(turn["assistant_text"])


@st.dialog("Diagnostic Options", width="large")
def show_diagnostic_options(case: dict, turns: list[dict]) -> None:
    """Technical exports and traces, deliberately absent from the main diagnosis view."""
    if not turns:
        st.info("No completed diagnostic turns are available yet.")
        return
    tab_handoff, tab_bundle, tab_trace = st.tabs(
        ["Professional Service Handoff", "Download Diagnostic Bundle", "Developer Trace"]
    )
    with tab_handoff:
        summary = build_handoff(case, turns)
        st.caption("Draft for a technician. Verify factual accuracy and privacy before sharing.")
        st.code(summary, language=None)
        st.download_button(
            "Download Service Handoff TXT", data=summary,
            file_name="TechMedic_Professional_Service_Handoff.txt", mime="text/plain",
            key=f"handoff_{case['id']}",
        )
    with tab_bundle:
        st.caption("Contains full case history and diagnostic evidence. Review before sharing.")
        st.download_button(
            "Download Diagnostic Bundle", data=build_diagnostic_bundle(case, turns),
            file_name=bundle_filename(case), mime="application/zip",
            key=f"bundle_{case['id']}",
        )
    with tab_trace:
        st.caption("Structured diagnostic information for technical review; it is not required for ordinary troubleshooting.")
        st.caption("This view separates LLM diagnostic state, optional controlled research, Jev decisions, timing, and safety.")
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["LLM structured state", "Controlled research", "Jev decision result", "Timing", "Safety screen"])
        with tab1:
            st.caption("Created by LLM #1 before Jev is called; status is then guarded by Jev before LLM #2 responds.")
            st.json(turns[-1]["diagnostic_state"])
        with tab2:
            research_trace = turns[-1].get("research") or {}
            if research_trace.get("performed"):
                st.caption("Current web/documentation evidence retrieved by the analyst-gated v1.5 research stage.")
                integration = (research_trace.get("_techmedic") or {}).get("integration_validation") or {}
                if integration.get("fallback_used"):
                    st.error("Research integration failed validation. See errors below; original diagnostic state retained.")
            elif research_trace.get("error"):
                st.error(str(research_trace.get("error")))
            else:
                st.caption(str(research_trace.get("skipped_reason") or "No controlled research was used on this turn."))
            st.json(research_trace)
        with tab3:
            st.caption(
                "Raw Jev answers are preserved here. _techmedic contains locally measured "
                "telemetry plus any deterministic lifecycle/action guardrail metadata."
            )
            jev_trace = turns[-1]["jev_result"]
            if not isinstance(jev_trace, dict) or not isinstance(jev_trace.get("answers"), dict):
                st.error("Stored Jev result is missing its expected answers object.")
            st.json(jev_trace)
        with tab4:
            telemetry = (turns[-1].get("jev_result") or {}).get("_techmedic", {})
            timing_rows = [
                ("LLM #1 — structured-state analysis", telemetry.get("llm_state_response_time_ms")),
                ("Web research", telemetry.get("research_response_time_ms")),
                ("LLM — research integration", telemetry.get("llm_research_integration_response_time_ms")),
                ("Jev — decision request", telemetry.get("jev_response_time_ms")),
                ("LLM #2 — response composition", telemetry.get("llm_responder_response_time_ms")),
                ("Total AI processing", telemetry.get("total_ai_processing_time_ms")),
            ]
            for label, value in timing_rows:
                st.metric(label, seconds_metric(value))
            st.caption("Times are measured locally by TechMedic. On research turns, total AI processing includes the web-search response and research-integration LLM call; UI/database overhead is not included.")
        with tab5:
            st.json(turns[-1]["safety"])


@st.dialog("Delete case forever?")
def confirm_case_deletion(case_id: str) -> None:
    saved_case = database.get_case(settings.database_path, case_id)
    if saved_case is None:
        st.info("This case has already been deleted.")
        if st.button("Close", key="missing_case_close"):
            rerun()
        return
    st.warning(
        "This case and all its diagnostic turns and pending submissions will be "
        "deleted forever from TechMedic's current database. This cannot be undone."
    )
    st.caption("Existing backups and disk remnants may retain old data; deletion is not secure erasure.")
    st.write(f"**Case:** {saved_case['title']}")
    cancel_col, confirm_col = st.columns(2)
    with cancel_col:
        if st.button("Cancel", use_container_width=True, key=f"cancel_delete_{case_id}"):
            rerun()
    with confirm_col:
        if st.button("Delete", type="primary", use_container_width=True,
                     key=f"confirm_delete_{case_id}"):
            database.delete_case(settings.database_path, case_id)
            if st.session_state.active_case_id == case_id:
                st.session_state.active_case_id = None
            rerun()


options_requested = False
delete_requested_case_id = None
with st.sidebar:
    st.title("TechMedic v1.5.6")
    st.caption("AI-assisted technical troubleshooting")
    st.warning("DEVELOPMENT / EVALUATION RELEASE — v1.5.6. Local records are encrypted with SQLCipher and Windows user-protected keys. Downloaded exports are not encrypted. Use fictional or non-sensitive inputs only.")
    st.caption("Installed separately from the accepted v1.5.5 baseline.")
    st.session_state.pass15_live_enabled = st.toggle(
        "Enable live OpenAI / Jev (evaluation)", value=bool(st.session_state.get('pass15_live_enabled', False)),
        disabled=not LIVE_ALLOWED,
        help="Only available if TECHMEDIC_V156_ALLOW_LIVE=I_ACCEPT_LIVE_API_CALLS was explicitly set before launch.")
    if not st.session_state.pass15_live_enabled:
        st.info("OFFLINE synthetic mode (no OpenAI, Jev or research calls)")
    st.caption("DEVELOPMENT / EVALUATION ONLY • NOT APPROVED FOR SENSITIVE OR GENERAL-PRODUCTION USE")

    if settings.missing_keys and st.session_state.pass15_live_enabled:
        st.error("Missing configuration: " + ", ".join(settings.missing_keys))
        st.caption("Add the keys to the project's .env file, then restart the app.")
    elif settings.missing_keys:
        st.info("Offline demonstration: API keys are not required.")
    else:
        st.success("API keys configured")

    st.caption(f"OpenAI model: {settings.openai_model}")
    st.caption(f"Jev model: {settings.jev_model}")
    if settings.jev_api_url:
        st.caption("Jev route: Custom endpoint")
    elif settings.jev_api_key.startswith("jv_live_"):
        st.caption("Jev route: Hosted gateway")
    else:
        st.caption("Jev route: Official TypeSafe API")

    st.divider()
    st.session_state.web_research_enabled = st.toggle(
        "Controlled web research",
        value=bool(st.session_state.web_research_enabled),
        help=(
            "When enabled, TechMedic may search current web/documentation sources only when "
            "the diagnostic analyst marks current external documentation as necessary."
        ),
    )
    if st.session_state.web_research_enabled:
        st.caption("Research runs only on analyst-gated turns and uses the OpenAI web-search tool.")
    else:
        st.caption("Web/documentation research is disabled for this session.")

    if st.session_state.pass15_live_enabled and settings.jev_api_key and st.button("Test Jev connection", use_container_width=True):
        try:
            client = JevClient(
                settings.jev_api_key,
                settings.jev_model,
                endpoint=settings.jev_api_url,
            )
            with st.spinner("Testing Jev..."):
                result = client.test_connection()
            resolved_model = result.get("model", "unknown")
            test_ms = (result.get("_techmedic") or {}).get("jev_response_time_ms")
            timing = f" · {test_ms / 1000:.2f} s" if isinstance(test_ms, (int, float)) else ""
            st.success(f"Jev connection OK ({resolved_model}){timing}")
        except Exception as exc:
            st.error(str(exc))

    if st.button("＋ New case", use_container_width=True):
        st.session_state.active_case_id = None
        rerun()

    options_case = (
        database.get_case(settings.database_path, st.session_state.active_case_id)
        if st.session_state.active_case_id else None
    )
    if st.session_state.get('history_case_id') != st.session_state.active_case_id:
        st.session_state.history_case_id = st.session_state.active_case_id
        st.session_state.history_limit = 50
    history_limit = st.session_state.get('history_limit', 50)
    history_rows = (
        database.get_turns(settings.database_path, options_case["id"], limit=history_limit + 1)
        if options_case else []
    )
    has_older_history = len(history_rows) > history_limit
    options_turns = history_rows[-history_limit:]
    options_requested = st.button(
        "Diagnostic Options", use_container_width=True, disabled=not bool(options_turns),
        help="Professional handoff, diagnostic bundle and developer trace for a saved case.",
    )

    st.divider()
    st.subheader("Recents")
    cases = database.list_cases(settings.database_path)
    if not cases:
        st.caption("No saved cases yet.")
    for recent_case in cases:
        # Keep the entire case title clickable; per-case controls are separate.
        case_col, menu_col = st.columns([5, 1.5], gap="small", vertical_alignment="top")
        with case_col:
            if st.button(recent_case["title"], key=f"case_{recent_case['id']}",
                         use_container_width=True):
                st.session_state.active_case_id = recent_case["id"]
                rerun()
        with menu_col:
            with st.popover("⋮", help="Case options", use_container_width=True, key=f"recent_menu_{recent_case['id']}"):
                if st.button("Delete", key=f"request_delete_{recent_case['id']}"):
                    delete_requested_case_id = recent_case["id"]

if delete_requested_case_id:
    confirm_case_deletion(delete_requested_case_id)
if options_requested and options_case and options_turns:
    show_diagnostic_options(options_case, database.get_turns(settings.database_path, options_case["id"]))

st.title("🩺 TechMedic v1.5.6")
st.caption("Observe → Form hypotheses → Test → Collect evidence → Reassess → Recommend")
st.caption("LLM + Jev technical troubleshooting with controlled research and evidence-preserving safety checks.")

if st.session_state.active_case_id is None:
    st.subheader("Start a new diagnostic case")
    with st.form("new_case"):
        problem = st.text_area(
            "Describe the problem",
            height=170,
            placeholder="Example: My Windows computer detects my graphics card, but PyTorch says no GPU is available.",
        )
        c1, c2 = st.columns(2)
        with c1:
            device_type = st.text_input("Device type (optional)", placeholder="Windows PC")
            manufacturer = st.text_input("Manufacturer (optional)")
        with c2:
            model = st.text_input("Model (optional)")
            operating_system = st.text_input("Operating system (optional)", placeholder="Windows 11")
        submitted = st.form_submit_button("Start Diagnosis", type="primary")

    if submitted:
        if not problem.strip():
            st.warning("Please describe the technical problem first.")
        elif settings.missing_keys and st.session_state.pass15_live_enabled:
            st.error("Live services need API keys before diagnosis.")
        else:
            case_id = database.create_case(
                settings.database_path,
                title="New case (pending diagnosis)",
                device_type=device_type,
                manufacturer=manufacturer,
                model=model,
                operating_system=operating_system,
            )
            st.session_state.active_case_id = case_id
            sid=uuid.uuid4().hex
            try:
                journal.capture(settings.database_path,case_id,sid,problem.strip())
                with st.spinner("Processing diagnostic input..."):
                    outcome=journal.process(settings.database_path,case_id,sid,
                         engine())
                if outcome['disposition']=='failed':
                    st.warning("Submission preserved after processing failed. Open this case to retry without retyping.")
                else:
                    rerun()
            except Exception as exc:
                st.error(f"Diagnostic submission error ({type(exc).__name__}); inspect saved case before retrying.")
else:
    case = options_case
    if not case:
        st.session_state.active_case_id = None
        rerun()

    # Case deletion is available only in the Recents three-dot menu.
    st.header(case["title"])
    st.caption(f"Status: {friendly_status(case['status'])}")

    turns = options_turns
    entries = journal.list_ui(settings.database_path, case['id'], unfinished_only=True)
    unfinished = [row for row in entries if row['state'] in ('pending','running','failed')]
    if unfinished:
        st.warning("A submitted message is unfinished. Its exact input remains in the local journal. Retry or explicitly abandon it before adding another message.")
        for item in unfinished:
            st.caption(f"Submission: {item['submission_id'][:12]}... • {item['state']} • "
                       f"{item['utf8_bytes']} UTF-8 bytes • {item['attempts']} attempt(s)")
            lease_expired = item['state'] == 'running' and (item['lease_until'] is None or item['lease_until'] <= time.time())
            if item['state'] in ('failed','pending') or lease_expired:
                if st.button('Retry saved submission', key='retry_'+item['submission_id']):
                    outcome=journal.process(settings.database_path,case['id'],item['submission_id'],engine())
                    if outcome['disposition']=='completed': rerun()
                    st.warning(f"Retry outcome: {outcome['disposition']}. Original text remains saved.")
                verified=st.checkbox('Confirm abandoning this unfinished message',key='confirm_'+item['submission_id'])
                if st.button('Abandon saved submission', key='abandon_'+item['submission_id'],disabled=not verified):
                    journal.abandon(settings.database_path,case['id'],item['submission_id'],confirmed=True)
                    rerun()
            else:
                st.caption('Active or stale worker. Retry is available once its processing lease expires.')
    if turns:
        render_assessment(turns[-1])
        latest_state = turns[-1].get("diagnostic_state") or {}
        readiness = (turns[-1].get("jev_result") or {}).get("_techmedic", {}).get("current_remediation_ready", False)
        if readiness:
            st.success("Current remediation procedure: ready for recommendation. Success still requires post-change verification.")
        elif case.get("status") == "remediation_identified":
            blockers = (latest_state.get("remediation") or {}).get("blocking_requirements") or []
            st.warning("Previously identified remediation milestone retained; current procedure is NOT ready. "
                       + ("Blocking prerequisite: " + "; ".join(map(str, blockers[:2])) if blockers else "Additional validation is needed."))


        safety = turns[-1].get("safety") or {}
        if safety.get("blocked"):
            st.error("Safety screen blocked a proposed procedure. TechMedic should provide a safer alternative or recommend qualified service.")
        elif safety.get("warnings"):
            for warning in safety["warnings"]:
                st.warning(warning)

        if has_older_history:
            st.caption(f"Showing the most recent {len(turns)} turns. Complete history remains saved and is included in exports.")
            if st.button("Load older messages", key="load_older_history"):
                st.session_state.history_limit = history_limit + 50
                rerun()
        render_history(turns)


    else:
        st.info("This case has no completed diagnostic turn yet. Enter the problem or a test result below to continue.")

    user_text = st.chat_input("Answer TechMedic's question or paste the requested test result...")
    if user_text:
        if unfinished:
            st.warning('Finish the saved submission first. This message was not submitted.')
        elif settings.missing_keys and st.session_state.pass15_live_enabled:
            st.error('The required live API keys are missing from .env.')
        else:
            sid=uuid.uuid4().hex
            try:
                journal.capture(settings.database_path,case['id'],sid,user_text)
                with st.spinner('Processing protected diagnostic submission...'):
                    outcome=journal.process(settings.database_path,case['id'],sid,
                        engine())
                if outcome['disposition']=='completed': rerun()
                st.warning(f"Submission saved for recovery ({outcome['disposition']}).")
            except Exception as exc:
                st.error(f'Diagnostic submission error ({type(exc).__name__}).')

st.divider()
st.caption(
    "TechMedic v1.5.6 is experimental and NOT an approved release. "
    "Do not use it as authority for hazardous electrical work, damaged batteries, medical devices, "
    "industrial equipment, or other safety-critical systems."
)
