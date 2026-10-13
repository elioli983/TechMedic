from __future__ import annotations

import json
import time
from typing import Any

from openai import OpenAI

from .models import normalize_diagnostic_state
from .prompts import ANALYST_INSTRUCTIONS, RESEARCH_INTEGRATION_INSTRUCTIONS, RESPONDER_INSTRUCTIONS


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key)
        self.last_update_state_time_ms: float | None = None
        self.last_integrate_research_time_ms: float | None = None
        self.last_compose_response_time_ms: float | None = None
        self.last_integrate_research_raw: str = ""

    def update_state(
        self,
        *,
        latest_user_text: str,
        previous_state: dict[str, Any] | None,
        case_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "case_context": case_context or {},
            "previous_state": previous_state or {},
            "latest_user_text": latest_user_text,
        }
        started = time.perf_counter()
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=ANALYST_INSTRUCTIONS,
                input=json.dumps(payload, ensure_ascii=False),
            )
            self.last_update_state_time_ms = (time.perf_counter() - started) * 1000
            parsed = _load_json_object(response.output_text)
            return normalize_diagnostic_state(parsed)
        except Exception as exc:
            self.last_update_state_time_ms = (time.perf_counter() - started) * 1000
            raise LLMError(f"OpenAI diagnostic-state analysis failed: {exc}") from exc

    def integrate_research(
        self,
        *,
        diagnostic_state: dict[str, Any],
        research_result: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "diagnostic_state": diagnostic_state,
            "research_result": research_result,
        }
        started = time.perf_counter()
        self.last_integrate_research_raw = ""
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=RESEARCH_INTEGRATION_INSTRUCTIONS,
                input=json.dumps(payload, ensure_ascii=False),
            )
            self.last_integrate_research_time_ms = (time.perf_counter() - started) * 1000
            self.last_integrate_research_raw = response.output_text or ""
            parsed = _load_json_object(response.output_text)
            return parsed
        except Exception as exc:
            self.last_integrate_research_time_ms = (time.perf_counter() - started) * 1000
            raise LLMError(f"OpenAI research integration failed: {exc}") from exc

    def repair_research_delta(
        self, *, diagnostic_state: dict[str, Any], research_result: dict[str, Any],
        errors: list[str], invalid_preview: str,
    ) -> dict[str, Any]:
        """One constrained repair attempt; NEVER relax the normal validator."""
        payload = {
            "diagnostic_state": diagnostic_state, "research_result": research_result,
            "validation_errors": errors, "rejected_preview": invalid_preview[:1500],
        }
        started = time.perf_counter()
        self.last_integrate_research_raw = ""
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=RESEARCH_INTEGRATION_INSTRUCTIONS + "\nYour prior response FAILED validation. Return ONLY the required research_delta_v1 object. No prose, wrappers, or markdown.",
                input=json.dumps(payload, ensure_ascii=False),
            )
            self.last_integrate_research_time_ms = (time.perf_counter() - started) * 1000
            self.last_integrate_research_raw = response.output_text or ""
            return _load_json_object(response.output_text)
        except Exception as exc:
            self.last_integrate_research_time_ms = (time.perf_counter() - started) * 1000
            raise LLMError(f"Research delta repair failed: {type(exc).__name__}") from exc

    def compose_response(
        self,
        *,
        diagnostic_state: dict[str, Any],
        jev_result: dict[str, Any],
        safety: dict[str, Any],
        research_result: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "diagnostic_state": diagnostic_state,
            "jev_result": jev_result,
            "safety_screen": safety,
            "research_result": research_result or {},
        }
        started = time.perf_counter()
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=RESPONDER_INSTRUCTIONS,
                input=json.dumps(payload, ensure_ascii=False),
            )
            self.last_compose_response_time_ms = (time.perf_counter() - started) * 1000
            text = (response.output_text or "").strip()
            if not text:
                raise ValueError("empty model response")
            return text
        except Exception as exc:
            self.last_compose_response_time_ms = (time.perf_counter() - started) * 1000
            raise LLMError(f"OpenAI response composition failed: {exc}") from exc


def _load_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(raw[start : end + 1])

    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value
