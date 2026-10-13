"""Deterministic, copyable professional-service summary; never requests the LLM.

Explicitly distinct from diagnostic export. This is a condensed, user-reviewable
summary of recorded case evidence, not professional diagnosis or certification.
"""
from __future__ import annotations
from typing import Any


def _line(text:Any)->str:
    return ' '.join(str(text or '').split())


def _joined(seq, limit=8):
    return '\n'.join(f'- {_line(x)}' for x in seq[:limit] if _line(x)) or '- Not documented.'


def build_handoff(case:dict[str,Any],turns:list[dict[str,Any]])->str:
    if not turns:
        return ('PROFESSIONAL-SERVICE HANDOFF (DRAFT)\n'
                'No completed TechMedic diagnostic turns are recorded.\n'
                'Review pending submissions separately; they are not completed diagnoses.')
    latest=turns[-1]
    state=latest.get('diagnostic_state') or {}
    diag=state.get('diagnosis') or {}
    remedy=state.get('remediation') or {}
    ver=state.get('resolution_verification') or {}
    safety=latest.get('safety') or {}
    jev=latest.get('jev_result') or {}
    telemetry=jev.get('_techmedic') or {}
    answers=jev.get('answers') or {}
    service=answers.get('professional_service_needed') or {}
    diagnosis_answer=answers.get('diagnosis_established') or {}
    diagnosis_score=diagnosis_answer.get('noul')
    summary=[
        'TECHMEDIC — PROFESSIONAL-SERVICE HANDOFF (DRAFT)',
        'This handoff is AI-assisted. Verify all reported facts before professional use.',
        '',
        'CASE',
        f'Case ID: {_line(case.get("id"))}',
        f'Title: {_line(case.get("title"))}',
        f'Diagnostic lifecycle: {_line(case.get("status"))}',
        f'Device: {_line(case.get("device_type"))} / {_line(case.get("manufacturer"))} / {_line(case.get("model"))}',
        f'Operating system: {_line(case.get("operating_system"))}',
        '',
        'REPORTED SYMPTOMS',
        _joined(state.get('symptoms') or []),
        '',
        'OBSERVATIONS / DIRECT EVIDENCE',
        _joined(state.get('observations') or []),
        '',
        'TESTS ALREADY RECORDED',
        _joined([f"{_line(t.get('test'))}: {_line(t.get('result'))}"
                 for t in (state.get('tests_performed') or []) if isinstance(t,dict)]),
        '',
        'WORKING DIAGNOSIS (NOT INDEPENDENTLY CONFIRMED)',
        _line(diag.get('summary')) or 'Not established.',
        'Recorded diagnostic basis:',
        _joined(diag.get('basis') or []),
        f"Jev diagnostic score (not empirically calibrated): {diagnosis_score if isinstance(diagnosis_score,(int,float)) and not isinstance(diagnosis_score,bool) else 'N/A'}",
        '',
        'REMEDIATION / CURRENT BARRIERS',
        _line(remedy.get('summary')) or 'No confirmed remediation.',
        f"Technical readiness only (NOT permission to perform work): {'yes' if telemetry.get('current_remediation_ready') is True else 'no / not established'}",
        "Authorization: NOT determined by TechMedic. Check requirements and obtain necessary permission before acting.",
        'Documented requirements (may include verification steps):',
        _joined(remedy.get('requirements') or []),
        'Outstanding prerequisites:',
        _joined(remedy.get('blocking_requirements') or []),
        '',
        'VERIFICATION STATUS',
        f"Case currently marked resolved: {'yes' if case.get('status')=='resolution_verified' else 'no'}",
        'Recorded post-change retests:',
        _joined([f"{_line(r.get('original_symptom'))}: {_line(r.get('result'))} — {_line(r.get('observation'))}"
                 for r in (ver.get('post_change_checks') or []) if isinstance(r,dict)]),
        '',
        'SAFETY / SERVICE',
        f"Safety screen blocked action: {'yes' if safety.get('blocked') else 'no'}",
        'Safety warnings:',
        _joined(safety.get('warnings') or []),
        f"Jev professional-service score: {_line(service.get('noul')) or 'not available'}",
        '',
        'QUESTIONS / INFORMATION FOR THE TECHNICIAN',
        _joined(state.get('missing_information') or []),
        '',
        'HANDOFF NOTE',
        'User descriptions, model-generated analysis, and third-party service scores have differing reliability. '
        'Review actual tests and original documentation. Do not assume a proposed fix was performed, '
        'or that a reported resolution was independently verified.',
    ]
    return '\n'.join(summary).strip()+'\n'
