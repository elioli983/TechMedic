from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from openai import OpenAI


class ResearchError(RuntimeError):
    pass


RESEARCH_INSTRUCTIONS = """
You are TechMedic's controlled documentation-research stage.

Your purpose is narrow: retrieve current, authoritative technical information that materially affects diagnosis or remediation. Typical targets include compatibility matrices, supported versions, driver requirements, firmware/release notes, manufacturer support articles, official troubleshooting guidance, and warranty/service documentation.

Rules:
1. You MUST use web search for this task.
2. Prefer primary/official sources: vendor documentation, manufacturer support, official release notes, official compatibility matrices, standards bodies, and project documentation maintained by the software/hardware owner.
3. Use secondary/community sources only when primary sources are unavailable or needed to locate primary documentation; clearly label secondary evidence.
4. Do not infer a user's local configuration from documentation. Distinguish "the documentation says X" from "this machine/device has X".
5. Do not provide hazardous service instructions. Do not direct the user to open power supplies, work on exposed mains/high voltage, open/damage lithium batteries, defeat safety interlocks, or perform unsafe internal repair.
6. Be concise and evidence-focused. Include exact version/model identifiers and dates when they matter.
7. If authoritative sources conflict or are incomplete, state that explicitly.
8. The result will be consumed by another diagnostic model. Do not tell the user what to do unless the documentation itself establishes a requirement; focus on verified facts, support constraints, and source-grounded implications.
9. For any exact recommended download, package version, firmware image, or installation command, locate and cite the PRIMARY distribution/download listing or official instructions supporting that exact artifact. A release announcement alone is not evidence that a specific platform wheel exists.
10. Include readable Markdown source links/citations immediately after source-backed assertions. Prefer 2–6 high-quality, directly relevant sources rather than numerous tangential search hits.
11. If an exact artifact cannot be independently confirmed from a primary source, explicitly say it remains unverified and do not present the artifact as confirmed available.

Return a concise research brief in plain text. Cite source links with each material source-grounded claim.
"""


class ResearchClient:
    def __init__(self, api_key: str, model: str, *, enabled: bool = True, max_sources: int = 10) -> None:
        self.model = model
        self.enabled = bool(enabled)
        self.max_sources = max(1, min(int(max_sources), 20))
        self.client = OpenAI(api_key=api_key)
        self.last_response_time_ms: float | None = None

    def research(self, *, request: dict[str, Any], diagnostic_state: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return _empty_result(request, skipped_reason="Controlled web research is disabled.")

        if not bool(request.get("needed")):
            return _empty_result(request, skipped_reason="No research requested for this turn.")

        query = str(request.get("query") or "").strip()
        reason = str(request.get("reason") or "").strip()
        category = str(request.get("category") or "documentation").strip() or "documentation"
        if not query:
            return _empty_result(request, skipped_reason="Research was requested without a usable query.")

        payload = {
            "research_category": category,
            "research_reason": reason,
            "query": query,
            "device": diagnostic_state.get("device", {}),
            "diagnosis": diagnostic_state.get("diagnosis", {}),
            "remediation_requirements": (
                diagnostic_state.get("remediation", {}).get("requirements", [])
                if isinstance(diagnostic_state.get("remediation"), dict)
                else []
            ),
            "instruction": (
                "Search for current authoritative documentation that answers the query. "
                "Prioritize official primary sources and state any unresolved ambiguity."
            ),
        }

        started = time.perf_counter()
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=RESEARCH_INSTRUCTIONS,
                tools=[{"type": "web_search"}],
                tool_choice="required",
                include=["web_search_call.action.sources"],
                input=json.dumps(payload, ensure_ascii=False),
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.last_response_time_ms = elapsed_ms

            brief = (getattr(response, "output_text", "") or "").strip()
            raw = _response_to_dict(response)
            sources, citations = _extract_provenance(raw, brief, limit=self.max_sources)
            calls = _count_web_search_calls(raw)

            if not brief:
                raise ResearchError("OpenAI web research returned an empty brief.")

            return {
                "performed": True,
                "category": category,
                "query": query,
                "reason": reason,
                "brief": brief,
                "sources": sources,
                "citations": citations,
                "error": "",
                "_techmedic": {
                    "research_response_time_ms": round(elapsed_ms, 1),
                    "web_search_calls": calls,
                    "source_count": len(sources),
                    "citation_count": len(citations),
                    "unmatched_citation_count": sum(not c.get("source_id") for c in citations),
                    "model": self.model,
                },
            }
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.last_response_time_ms = elapsed_ms
            return {
                "performed": False,
                "category": category,
                "query": query,
                "reason": reason,
                "brief": "",
                "sources": [],
                "citations": [],
                "error": f"Controlled web research failed: {exc}",
                "_techmedic": {
                    "research_response_time_ms": round(elapsed_ms, 1),
                    "web_search_calls": 0,
                    "source_count": 0,
                    "model": self.model,
                },
            }


def _empty_result(request: dict[str, Any], *, skipped_reason: str) -> dict[str, Any]:
    return {
        "performed": False,
        "category": str(request.get("category") or ""),
        "query": str(request.get("query") or ""),
        "reason": str(request.get("reason") or ""),
        "brief": "",
        "sources": [],
        "citations": [],
        "error": "",
        "skipped_reason": skipped_reason,
        "_techmedic": {
            "research_response_time_ms": 0.0,
            "web_search_calls": 0,
            "source_count": 0,
        },
    }


def _response_to_dict(response: Any) -> dict[str, Any]:
    for method_name in ("model_dump", "to_dict"):
        method = getattr(response, method_name, None)
        if callable(method):
            value = method()
            if isinstance(value, dict):
                return value
    if isinstance(response, dict):
        return response
    return {}


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


# Only remove tracking parameters. Functional query arguments are important for
# versioned/vendor documentation and must not be stripped.
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_URL_IN_MARKDOWN = re.compile(r"\[[^\]]+\]\((https?://[^\s)]+)\)")


def _canonical_url(url: str) -> str:
    value = str(url or "").strip().rstrip(".,;)")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    parts = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not (k.lower().startswith("utm_") or k.lower() in _TRACKING_QUERY_KEYS)]
    host = parsed.netloc.lower().removeprefix("www.")
    return urlunparse((parsed.scheme.lower(), host, parsed.path or "/", "", urlencode(parts), ""))


def _official_primary(url: str) -> bool:
    """Conservative provenance ranking, not a proof of a source's reliability."""
    parsed = urlparse(url)
    host, path = parsed.netloc.lower(), parsed.path.lower()
    official_hosts = (
        "docs.pytorch.org", "download.pytorch.org", "pytorch.org",
        "dev-discuss.pytorch.org", "docs.nvidia.com", "developer.nvidia.com",
        "nvidia.com", "learn.microsoft.com", "support.microsoft.com",
        "docs.python.org", "python.org", "pypi.org", "docs.amd.com",
    )
    if any(host == h or host.endswith("." + h) for h in official_hosts):
        return True
    if host == "github.com":
        # Project-maintained documentation/releases count as primary.
        return any(path.startswith("/" + org + "/") for org in ("pytorch", "python", "nvidia"))
    return False


def _source_title(url: str, title: str) -> str:
    value = str(title or "").strip()
    if value and value.lower() not in {"github.com", "www.github.com", "source", "url"}:
        return value
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    return f"{parsed.netloc} — {path}" if path else parsed.netloc


def _extract_provenance(raw: dict[str, Any], brief: str, *, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Index citations BEFORE uncited search hits, keeping every citation linked.

    v1.5.1 selected the first N search hits and then attempted to associate
    annotations with that truncated set. The actual relevant citations could
    arrive much later, yielding empty source_id fields. The new logic reserves
    source IDs for cited URLs first and fills remaining capacity with discovery.
    """
    entries: dict[str, dict[str, Any]] = {}
    cited_order: list[str] = []
    discovered_order: list[str] = []

    def remember(url: str, title: str, *, cited: bool, origin: str) -> None:
        key = _canonical_url(url)
        if not key:
            return
        if key not in entries:
            entries[key] = {"url": key, "title": _source_title(key, title),
                            "cited": cited, "origins": [origin]}
            (cited_order if cited else discovered_order).append(key)
        else:
            entry = entries[key]
            if title and (not entry["title"] or entry["title"].startswith(urlparse(key).netloc + " —")):
                entry["title"] = _source_title(key, title)
            if origin not in entry["origins"]:
                entry["origins"].append(origin)
            if cited and not entry["cited"]:
                entry["cited"] = True
                cited_order.append(key)

    # Prefer citation annotations: they identify what the research model
    # actually relied on, unlike the broad list of search results.
    for node in _walk(raw):
        if str(node.get("type") or "") == "url_citation":
            remember(node.get("url", ""), str(node.get("title") or ""),
                     cited=True, origin="url_citation")

    # Responses may include Markdown citations not exposed as SDK annotations.
    # URLs in shell commands/inline code are NOT automatically source evidence.
    for link in _URL_IN_MARKDOWN.findall(brief or ""):
        remember(link, "", cited=True, origin="research_brief_link")

    for node in _walk(raw):
        if str(node.get("type") or "") == "url_citation":
            continue
        url = node.get("url")
        if isinstance(url, str):
            remember(url, str(node.get("title") or node.get("name") or ""),
                     cited=False, origin="web_search_result")

    # Prioritize official primary references among noncited search hits.
    remaining = [key for key in discovered_order if key not in cited_order]
    remaining_rank = {key: idx for idx, key in enumerate(remaining)}
    remaining.sort(key=lambda u: (not _official_primary(u), remaining_rank[u]))

    # Citation completeness takes precedence over the configured cap. Should
    # a long brief cite too many pages, keep them all for auditability, rather
    # than silently emitting citations with missing IDs.
    selected = cited_order + remaining[:max(0, limit - len(cited_order))]
    sources: list[dict[str, Any]] = []
    by_url: dict[str, str] = {}
    for index, key in enumerate(selected, start=1):
        item = entries[key]
        sid = f"R{index}"
        by_url[key] = sid
        sources.append({
            "id": sid, "title": item["title"], "url": key,
            "domain": urlparse(key).netloc.lower(),
            "primary_source": _official_primary(key),
            "cited_in_research": bool(item["cited"]),
            "provenance_origins": item["origins"],
        })

    citations = [{"source_id": by_url[key], "url": key, "title": entries[key]["title"]}
                 for key in cited_order]
    return sources, citations


def _extract_sources(raw: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    """Compatibility wrapper for existing integrations/test fixtures."""
    return _extract_provenance(raw, "", limit=limit)[0]


def _extract_citations(raw: dict[str, Any], sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Compatibility wrapper: map canonical citation URLs to provided IDs."""
    id_by_url = {_canonical_url(s.get("url", "")): s.get("id", "") for s in sources}
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in _walk(raw):
        if str(node.get("type") or "") != "url_citation":
            continue
        key = _canonical_url(node.get("url", ""))
        if key and key not in seen and id_by_url.get(key):
            out.append({"source_id": id_by_url[key], "url": key,
                        "title": _source_title(key, str(node.get("title") or ""))})
            seen.add(key)
    return out


def reconcile_research_source_ids(state: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Ensure integrated source ID references correspond to indexed sources.

    Invalid IDs and uncited search-only IDs are removed from the diagnostic
    state rather than allowing unsupported attribution. Audit anomalies are
    recorded. Older source fixtures without the cited_in_research flag remain
    supported.
    """
    evidence = state.get("research_evidence")
    if not isinstance(evidence, dict):
        return []
    ids = evidence.get("source_ids")
    if not isinstance(ids, list):
        return []
    valid = {
        str(s.get("id")) for s in result.get("sources", [])
        if isinstance(s, dict) and s.get("cited_in_research") is not False
    }
    missing = [str(i) for i in ids if str(i) not in valid]
    if missing:
        evidence["source_ids"] = [str(i) for i in ids if str(i) in valid]
        result.setdefault("_techmedic", {})["invalid_integrated_source_ids"] = missing
    return missing


def _count_web_search_calls(raw: dict[str, Any]) -> int:
    count = 0
    for node in _walk(raw):
        if str(node.get("type") or "") == "web_search_call":
            count += 1
    return count


def linkify_research_citations(text: str, research_result: dict[str, Any]) -> str:
    """Turn model-emitted [R1] markers into clickable Markdown links."""
    if not text or not isinstance(research_result, dict):
        return text
    sources = research_result.get("sources")
    if not isinstance(sources, list):
        return text
    out = text
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("id") or "").strip()
        url = str(source.get("url") or "").strip()
        if not source_id or not url:
            continue
        pattern = re.compile(rf"(?<!\])\[{re.escape(source_id)}\](?!\()")
        out = pattern.sub(f"[{source_id}]({url})", out)
    return out


def append_research_sources(text: str, research_result: dict[str, Any]) -> str:
    if not isinstance(research_result, dict) or not research_result.get("performed"):
        return text
    sources = research_result.get("sources")
    if not isinstance(sources, list) or not sources:
        return text
    lines = ["", "### Sources consulted"]
    cited, extra = [], []
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("id") or "").strip()
        title = str(source.get("title") or source.get("domain") or "Source").strip()
        url = str(source.get("url") or "").strip()
        if source_id and url:
            line = f"- [{source_id} — {title}]({url})"
            (extra if source.get("cited_in_research") is False else cited).append(line)
    if cited:
        lines.extend(["", "**Cited research evidence**", *cited])
    if extra:
        lines.extend(["", "**Additional search results — not cited as supporting evidence**", *extra])
    if not cited and not extra:
        return text
    return text.rstrip() + "\n" + "\n".join(lines)
