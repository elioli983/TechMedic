"""v1.5.5 bounded, source-validated *delta* research integration.

Research may update documentation conclusions and the proposed remediation,
but cannot rewrite observations, tests, diagnosis, device identity, or local
resolution evidence. A failed integration is never used to authorize repair.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from .models import normalize_diagnostic_state
from .research_integration import integrate_research_safely


_SECRET = re.compile(r'(?i)(sk-[a-z0-9_-]{12,}|jv_live_[a-z0-9_-]+|bearer\s+[^\s"\']+|(?:api[_-]?key|token|password|secret)\s*[=:]\s*[^\s,}]+)')


def _strip_sensitive(value: Any) -> Any:
    """Best-effort removal of credential-bearing JSON keys in trace previews."""
    if isinstance(value, dict):
        return {str(k): ('[REDACTED]' if re.search(r'(password|secret|credential|api[_-]?key|access[_-]?token|auth)', str(k), re.I)
                         else _strip_sensitive(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_sensitive(x) for x in value]
    return value


def safe_preview(candidate: Any, limit: int = 2500) -> dict[str, Any]:
    """Bounded, best-effort credential-redacted rejected model-output preview."""
    raw = json.dumps(candidate, ensure_ascii=False, default=str) if not isinstance(candidate, str) else candidate
    cleaned = _strip_sensitive(candidate)
    text = json.dumps(cleaned, ensure_ascii=False, default=str) if not isinstance(cleaned, str) else cleaned
    text = _SECRET.sub('[REDACTED]', text)
    # JSON model responses may be strings whose content embeds secret-valued
    # keys; avoid claiming universal PII scrub, but remove common forms.
    text = re.sub(r'(?i)(["\'](?:api[_-]?key|password|secret|access[_-]?token)["\']\s*:\s*["\'])[^"\']+', r'\1[REDACTED]', text)
    return {"candidate_sha256": hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            "candidate_chars": len(raw), "rejected_candidate_preview": text[:limit],
            "preview_truncated": len(text) > limit}


def _source_errors(ids: list[str], research: dict[str, Any]) -> list[str]:
    sources = {str(s.get('id')): s for s in research.get('sources', []) if isinstance(s, dict)}
    bad = [i for i in ids if i not in sources or sources[i].get('cited_in_research') is False]
    errors = []
    if not ids:
        errors.append('research conclusion does not cite an indexed source')
    if bad:
        errors.append('source IDs not present among cited research sources: ' + ', '.join(bad))
    if not any(sources.get(i, {}).get('primary_source') is True for i in ids):
        errors.append('research conclusion has no cited primary source')
    return errors


def integrate_research_delta_safely(
    previous: dict[str, Any], candidate: Any, research: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Accept a strict narrow delta or backwards-compatible validated full state.

    Do NOT normalize the candidate before checking its schema; that would
    silently turn missing information into empty values.
    """
    before = normalize_diagnostic_state(previous)
    if not isinstance(candidate, dict):
        return before, {"status": "rejected", "fallback_used": True,
                        "validation_errors": ["integration response is not a JSON object"], "preserved_evidence": {}}
    if candidate.get('format') != 'research_delta_v1':
        # Legacy full-state responses still pass through strict v1.5.3 checks.
        return integrate_research_safely(before, candidate, research)

    errors: list[str] = []
    permitted = {'format', 'research_evidence', 'remediation', 'research_request'}
    if set(candidate) - permitted:
        errors.append('delta attempted to modify protected diagnostic fields')
    required = {
        'research_evidence': {'summary': str, 'source_ids': list, 'category': str, 'query': str},
        'remediation': {'summary': str, 'requirements': list, 'selection_ready': bool,
                        'blocking_requirements': list},
        'research_request': {'needed': bool, 'category': str, 'query': str, 'reason': str},
    }
    for group, fields in required.items():
        node = candidate.get(group)
        if not isinstance(node, dict):
            errors.append('missing or invalid ' + group)
            continue
        for key, kind in fields.items():
            if not isinstance(node.get(key), kind):
                errors.append(f'missing or invalid {group}.{key}')
        if set(node) - (set(fields) | ({'install_command', 'verification_commands', 'confidence_note'} if group == 'remediation' else set())):
            errors.append(f'unexpected fields in {group}')
    # Invalid nested types have already been recorded above. Never call .get
    # on arbitrary scalar/list values just to collect further validation errors:
    # this must be a rejection, not an AttributeError and exception-only audit.
    evidence = candidate.get('research_evidence') if isinstance(candidate.get('research_evidence'), dict) else {}
    remedy = candidate.get('remediation') if isinstance(candidate.get('remediation'), dict) else {}
    ids = evidence.get('source_ids')
    if isinstance(ids, list) and all(isinstance(x, str) for x in ids):
        errors.extend(_source_errors(ids, research))
    else:
        errors.append('research_evidence.source_ids must be a list of strings')
    if not str(evidence.get('summary') or '').strip():
        errors.append('research_evidence.summary cannot be empty')
    if remedy.get('selection_ready') is True:
        if remedy.get('blocking_requirements'):
            errors.append('remediation cannot be ready while blocking requirements remain')
        if not str(remedy.get('summary') or '').strip():
            errors.append('ready remediation requires a concrete summary')
    if 'install_command' in remedy and not isinstance(remedy['install_command'], str):
        errors.append('install_command must be a string')
    if 'verification_commands' in remedy and not (isinstance(remedy['verification_commands'], list) and
                                                  all(isinstance(v, str) for v in remedy['verification_commands'])):
        errors.append('verification_commands must be strings')
    if 'confidence_note' in remedy and not isinstance(remedy['confidence_note'], str):
        errors.append('confidence_note must be a string')
    if not errors and remedy.get('selection_ready'):
        from .consistency import installation_command_error
        command = str(remedy.get('install_command') or '').strip()
        err = installation_command_error(command, before)
        if err:
            errors.append('invalid or missing installation command: ' + err)
        # If the command selects an exact CUDA wheel, the research citations
        # must include the official distribution index for that CUDA family.
        import re as _re
        build = _re.search(r'torch\s*==\s*[\d.]+\+(cu\d+)\b', command, _re.I)
        if build:
            cited_urls = [str(s.get('url') or '') for s in research.get('sources', [])
                          if isinstance(s, dict) and s.get('id') in ids
                          and s.get('cited_in_research') is not False]
            if not any('download.pytorch.org/whl/' + build.group(1).lower() + '/torch' in url.lower() for url in cited_urls):
                errors.append('exact PyTorch CUDA build lacks matching cited official artifact index')
    if errors:
        return before, {"status": "rejected", "fallback_used": True,
                        "validation_errors": errors, "preserved_evidence": {}}

    after = copy.deepcopy(before)
    for group in ('research_evidence', 'remediation', 'research_request'):
        after[group].update(copy.deepcopy(candidate[group]))
    # Local evidence, diagnosis, and verification fields are never touched.
    return after, {"status": "accepted", "fallback_used": False,
                   "validation_errors": [], "preserved_evidence": {}, "integration_format": "research_delta_v1"}
