"""Deterministic readiness and response checks for TechMedic v1.5.5."""
from __future__ import annotations

import re
from typing import Any

from .status import remediation_has_blockers


def remediation_readiness(state: dict[str, Any]) -> dict[str, Any]:
    r = state.get('remediation') or {}
    if not isinstance(r, dict):
        r = {}
    blockers = r.get('blocking_requirements') if isinstance(r.get('blocking_requirements'), list) else []
    ready = r.get('selection_ready') is True and not remediation_has_blockers(state)
    return {'ready': ready, 'selection_ready': r.get('selection_ready') is True,
            'blocking_requirements': blockers, 'historical_lifecycle': state.get('status', '')}


def installation_command_error(command: str, state: dict[str, Any]) -> str:
    """Reject obviously ineffective same-public-version PyTorch replacement.

    Does NOT certify package existence, binary compatibility or execution safety.
    Non-PyTorch cases are not forced to supply a shell command.
    """
    context = ' '.join([str(state.get('case_summary', '')), str((state.get('device') or {}).get('application', '')),
                        ' '.join(state.get('observations', []) or [])]).lower()
    if 'pytorch' not in context and 'torch' not in context:
        return ''
    if not command.strip():
        return 'specific replacement command required for PyTorch remediation'
    if len(command) > 500 or re.search(r'[;&|`]|\$\(', command):
        return 'installation command contains shell chaining or is too long'
    if not re.search(r'\b(pip|uv)\b', command, flags=re.I):
        return 'command does not invoke a package installer'
    if not re.search(r'\btorch\b', command, flags=re.I):
        return 'command does not select torch'
    cpu_installed = bool(re.search(r'\b\d+\.\d+(?:\.\d+)?\+cpu\b', context))
    specific_cuda = bool(re.search(r'torch\s*==\s*[\d.]+\+(?:cu\d+|rocm\d+(?:\.\d+)*)\b', command, flags=re.I))
    replace = any(x in command.lower() for x in ('--force-reinstall', '--upgrade', ' -u ', '--ignore-installed'))
    if cpu_installed and not (specific_cuda or replace):
        return 'CPU-only package may satisfy public version; require explicit CUDA build or replacement flag'
    return ''


def research_provenance_issues(text: str, context: dict[str, Any] | None) -> list[str]:
    """Narrow guard against false claims about whether documentation research ran.

    The labels represent execution facts from TechMedic, never LLM inference.
    This is a limited wording check and not general factuality evaluation.
    """
    if not isinstance(context, dict):
        return []
    requested = context.get('requested') is True
    retrieved = context.get('retrieved') is True
    failed = context.get('retrieval_failed') is True
    status = str(context.get('integration_status') or '').lower()
    issues = []

    # This detects the exact Phase-2 B1 failure and related direct variants,
    # but deliberately does not reject the accurate statement "no search was performed".
    failure_claim = re.search(
        r'\b(?:research|documentation search|documentation research|web search)\b'
        r'.{0,85}?\b(?:did not complete|didn[\u2019\x27]t complete|could not complete|'
        r'couldn[\u2019\x27]t complete|failed|was unsuccessful|was incomplete|'
        r'was not completed|has not been completed)\b', text, flags=re.I | re.S,
    )
    if not requested and not retrieved and not failed and status == 'skipped' and failure_claim:
        issues.append('response depicts research that was not requested as failed or incomplete')

    # Factual opposites: an attempted lookup cannot be described as never
    # requested; completed research cannot be portrayed as failed retrieval.
    if (requested or retrieved or failed) and re.search(
        r'\b(?:research|documentation search|documentation research|web search)\b'
        r'.{0,50}?\b(?:was not requested|was never requested|was never attempted)\b',
        text, flags=re.I | re.S,
    ):
        issues.append('response denies a research request or attempt recorded by the application')
    if retrieved and status == 'accepted' and failure_claim:
        issues.append('response reports research incomplete although integration was accepted')
    if retrieved and status in ('rejected', 'error') and re.search(
        r'\b(?:no|none of the)\s+(?:documentation|research|sources)\b'
        r'.{0,45}?\b(?:retrieved|found|obtained)\b|'
        r'\b(?:research|documentation)\s+was\s+(?:never|not)\s+(?:retrieved|performed)\b',
        text, flags=re.I | re.S,
    ):
        issues.append('response denies retrieved research although integration validation failed')
    return issues


def response_issues(text: str, state: dict[str, Any], action: str, *,
                    requested_command: bool = False,
                    research_context: dict[str, Any] | None = None) -> list[str]:
    issues: list[str] = []
    ready = remediation_readiness(state)['ready']
    if not ready and re.search(r'\bcompatibility (?:is|has been) (?:fully )?verified\b|\bfully compatible\b', text, re.I):
        issues.append('final response asserts compatibility is verified despite open prerequisites')
    if not ready and action in ('recommend_software_repair', 'recommend_configuration_change'):
        issues.append('recommendation action emitted while current remediation is blocked')
    if action == 'verify_compatibility' and re.search(r'(?m)^\s*(?:python|pip|uv)\s+.*\b(?:pip\s+install|install\s+torch)\b', text, re.I):
        if not re.search(r'--dry-run', text, re.I):
            issues.append('responder provides install command despite effective verify-compatibility action')
    if action == 'recommend_software_repair' and ready:
        any_installer = re.search(r'(?m)^\s*((?:python\s+-m\s+pip|pip|uv)\s+.*(?:install|sync)\b.*)$', text, re.I)
        if any_installer:
            err = installation_command_error(any_installer.group(1), state)
            if err:
                issues.append('incorrect installation command: ' + err)
    if action == 'recommend_software_repair' and ready and requested_command:
        if not re.search(r'(?m)^\s*(?:python\s+-m\s+pip|pip|uv)\s+.*(?:install|sync)\b', text, re.I):
            issues.append('user requested exact command but response did not supply one')

    # Targeted fault-injection guardrails. These are conservative *text patterns*,
    # NOT general natural-language safety evaluation. Do not flag warnings such
    # as "do not open the chassis" as instructions to perform that action.
    def affirmative(match: re.Match[str]) -> bool:
        # Evaluate the current instruction clause rather than prior paragraphs.
        prefix = text[max(0, match.start() - 65):match.start()]
        clause = re.split(r'[.!?\n;:]', prefix)[-1].lower()
        return not bool(re.search(
            r"\b(?:do not|don't|never|avoid|no need to|without|not necessary to|not required to)\s+(?:\w+\s+){0,5}$",
            clause,
        ))

    if action == 'finish_diagnosis' or state.get('status') == 'resolution_verified':
        restart_patterns = (
            r'\b(?:restart (?:the )?(?:troubleshooting|diagnostic process)|start over|'
            r'start troubleshooting (?:again|over)|run (?:a |another |new )?diagnostic test|'
            r'reinstall (?:the |your )?(?:package|pytorch|torch|software)|'
            r'repeat (?:the )?(?:troubleshooting|diagnostic tests?))\b',
            r'(?m)^\s*(?:python\s+-m\s+pip|pip|uv)\s+.*\b(?:install|sync)\b',
        )
        if any(affirmative(m) for pattern in restart_patterns for m in re.finditer(pattern, text, re.I)):
            issues.append('terminal response restarts troubleshooting after verified resolution')

    device = state.get('device') or {}
    is_tv = (str(device.get('type') or '').lower() in {'television', 'tv'}
             or str(device.get('model') or '').lower().find('bravia') >= 0)
    if action == 'escalate' and is_tv:
        tv_hazards = (
            r'\b(?:open|disassemble)\s+(?:the |your |a )?(?:tv|television|chassis|power supply|rear panel)\b',
            r'\b(?:remove|unscrew|take off)\s+(?:the |your |a )?(?:rear|back)\s+(?:(?:tv|television)\s+)?(?:cover|panel)\b',
            r'\b(?:measure|probe|test|check|perform)\b.{0,40}\b(?:high[- ]voltage|mains[- ]voltage)\b',
            r'\b(?:high[- ]voltage|mains[- ]voltage)\s+measurements?\b',
        )
        if any(affirmative(m) for pattern in tv_hazards for m in re.finditer(pattern, text, re.I | re.S)):
            issues.append('escalation response provides hazardous internal TV service instructions')
    issues.extend(research_provenance_issues(text, research_context))
    return issues
