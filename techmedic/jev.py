from __future__ import annotations

from typing import Any
import time
from urllib.parse import urlsplit

import requests


class JevError(RuntimeError):
    pass


HOSTED_ENDPOINT = "https://jevtypesafeai.com/api/v1/decide"
OFFICIAL_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
OFFICIAL_MODELS_ENDPOINT = "https://api.typesafe.ai/v1/models"


def validate_jev_endpoint(url: str) -> str:
    """Credentials and case data may only be sent to an explicit HTTPS host."""
    url = url.strip()
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme.lower() == 'https' and bool(parsed.hostname)
                 and parsed.username is None and parsed.password is None
                 and not parsed.fragment and not any(c.isspace() for c in url)
                 and not any(ord(c) < 32 for c in url) and '\\' not in url)
        parsed.port  # reject malformed/out-of-range ports
    except ValueError:
        valid = False
    if not valid:
        raise JevError('Jev endpoint must be an HTTPS URL with a host, without embedded credentials or a fragment.')
    return url.rstrip('/')


def resolve_jev_endpoint(api_key: str, explicit_url: str = "") -> str:
    """Choose the Jev endpoint from explicit config or key type."""
    if explicit_url.strip():
        return validate_jev_endpoint(explicit_url)
    if api_key.strip().startswith("jv_live_"):
        return HOSTED_ENDPOINT
    return OFFICIAL_ENDPOINT


class JevClient:
    def __init__(
        self,
        api_key: str,
        model: str = "jev-latest",
        endpoint: str = "",
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.endpoint = resolve_jev_endpoint(self.api_key, endpoint)
        self.timeout = timeout

    @property
    def route_name(self) -> str:
        if self.endpoint == HOSTED_ENDPOINT:
            return "Hosted Jev gateway"
        if self.endpoint == OFFICIAL_ENDPOINT:
            return "Official TypeSafe API"
        return "Custom Jev endpoint"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def get_models(self) -> dict[str, Any]:
        try:
            response = requests.get(
                OFFICIAL_MODELS_ENDPOINT,
                headers=self._headers(),
                timeout=self.timeout,
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise JevError('Jev redirects are not allowed; configure the final HTTPS endpoint.')
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise JevError(f"Jev model lookup failed: {exc}") from exc

    @staticmethod
    def build_payload(state: dict[str, Any], model: str = "jev-latest") -> dict[str, Any]:
        return {
            "state": state,
            "model": model,
            "questions": {
                "fault_domain": {
                    "type": "choice",
                    "instructions": "Which technical domain most likely contains the primary cause of the reported problem, given only the current evidence? Be conservative when evidence is sparse: prefer 'unknown' when symptoms do not yet distinguish application, configuration, driver/runtime, or hardware. Do not infer a specific domain merely because an application reports the symptom.",
                    "criteria": {
                        "hardware": "A physical component, cable, connector, power, thermal, display, storage, or other hardware fault is the leading explanation.",
                        "operating_system": "The operating system itself, an OS service, permission, update, or system component is the leading explanation.",
                        "driver_runtime": "Evidence specifically points to a device driver, GPU/runtime layer such as CUDA or ROCm/HIP, firmware interface, or hardware enablement stack.",
                        "application": "Evidence specifically points to an application, package, dependency, virtual environment, or application-level configuration; the application merely reporting a hardware/runtime symptom is not enough by itself.",
                        "network": "Networking, DNS, routing, Wi-Fi, LAN, firewall, VPN, or connectivity is the leading explanation.",
                        "configuration": "A user/system configuration choice is the leading explanation and does not fit a more specific category above.",
                        "peripheral": "An attached peripheral or accessory is the leading explanation.",
                        "unknown": "The evidence is too incomplete, ambiguous, or non-discriminating to prefer another category.",
                    },
                },
                "evidence_sufficient": {
                    "type": "noul",
                    "instructions": "Given the current evidence, is there enough specific support to state a likely diagnostic cause or demonstrated failing component/subsystem/configuration/service/path that explains the reported symptom, rather than merely list possibilities? This does not require identifying the deepest underlying mechanism.",
                },
                "diagnosis_established": {
                    "type": "noul",
                    "instructions": "Has a diagnostic cause been established strongly enough by direct or discriminating evidence that TechMedic can state it as the diagnosis at a useful troubleshooting level? A demonstrated failing component, subsystem, configuration, service, or path that explains the reported symptom is sufficient; do not require identification of the deepest underlying mechanism. Current official documentation research may support this judgment when it directly applies, but documentation alone does not prove the user's local configuration. The exact corrective procedure may still need compatibility, policy, or implementation verification.",
                },
                "remediation_identified": {
                    "type": "noul",
                    "instructions": "Has a specific, actionable, technically appropriate and sufficiently supported corrective path been identified, with essential compatibility requirements accounted for? A general strategy like 'replace the CPU-only package' is NOT an identified remediation if the actual compatible version/build/platform or other prerequisites remain unverified. If remediation.selection_ready=false or remediation.blocking_requirements is nonempty, give low remediation confidence even if the diagnosis is established. Current official documentation research can establish support requirements but cannot establish a user's local configuration.",
                },
                "resolution_verified": {
                    "type": "noul",
                    "instructions": "Has the user supplied post-remediation evidence showing that the original symptom is actually resolved, rather than merely reporting that a fix was attempted?",
                },
                "hardware_failure_likely": {
                    "type": "noul",
                    "instructions": "Given the current evidence, is a physical hardware failure likely to be the primary cause?",
                },
                "professional_service_needed": {
                    "type": "noul",
                    "instructions": "Given the current state, should the user stop routine troubleshooting and seek qualified professional service because further work is unsafe, requires specialized equipment, or likely exceeds normal end-user procedures?",
                },
                "urgency": {
                    "type": "score",
                    "instructions": "Rate the urgency of the technical problem based on safety, data-loss risk, and operational impact.",
                    "criteria": [
                        "Low: inconvenience only; no meaningful safety, data-loss, or operational risk.",
                        "Moderate: degraded function or recurring failure, but no immediate safety or serious data-loss concern.",
                        "High: significant operational impact, credible data-loss risk, overheating, repeated crashes, or worsening failure.",
                        "Critical: immediate safety concern, active data destruction, smoke/fire/electrical hazard, or severe security impact requiring prompt action.",
                    ],
                },
                "next_action": {
                    "type": "choice",
                    "instructions": "What should TechMedic do next to make the most useful progress while minimizing risk? Distinguish diagnosis from remediation and verification. Do not keep choosing diagnostic tests solely to discover a deeper underlying mechanism after a symptom-explaining diagnostic cause has already been established; move to identifying or validating the corrective path when appropriate. If post-remediation evidence verifies the original symptom is resolved, choose finish_diagnosis rather than asking for non-blocking background information. If a corrective action has been performed but the original symptom has not yet been retested, choose verify_resolution. The choice 'escalate' is a workflow action only; it must not be interpreted as a diagnostic lifecycle state.",
                    "criteria": {
                        "ask_for_information": "Ask the user for one missing fact, symptom, version, model, or error message that does not require a system command or inspection.",
                        "collect_system_information": "Collect low-risk device, OS, driver, package, version, configuration, or environment information needed to understand the system.",
                        "run_diagnostic_test": "Have the user perform one low-risk test whose result discriminates among still-meaningful competing causes at the current diagnostic level; do not use this merely to excavate a deeper mechanism after a sufficient diagnosis is established.",
                        "verify_compatibility": "Check current version, hardware, driver, firmware, package, or platform compatibility before recommending a change. If controlled documentation research is available and identifiers are sufficient, use that evidence rather than asking the user to browse manually.",
                        "recommend_configuration_change": "Evidence supports a low-risk reversible setting or configuration correction.",
                        "recommend_software_repair": "A SPECIFIC software repair is supported and ready to recommend; not merely a generic repair direction that still needs compatibility checks.",
                        "recommend_hardware_inspection": "A safe external hardware, cable, connector, or visible-condition inspection is appropriate.",
                        "verify_resolution": "A corrective action has been performed; now test whether the original symptom is actually resolved.",
                        "finish_diagnosis": "The case can be closed because the diagnostic objective is complete; especially use this after resolution is verified. Non-blocking caveats can be stated without reopening information gathering.",
                        "escalate": "Stop normal troubleshooting and recommend qualified service or a specialist.",
                    },
                },
            },
        }

    def test_connection(self) -> dict[str, Any]:
        payload = {
            "state": "TechMedic Jev connectivity test.",
            "model": self.model,
            "questions": {
                "connected": {
                    "type": "noul",
                    "instructions": "Is this input explicitly a TechMedic Jev connectivity test?",
                }
            },
        }
        return self._post(payload)

    @staticmethod
    def _validate_lifecycle_scores(result: dict[str, Any]) -> None:
        """Reject malformed model-derived probabilities before lifecycle processing."""
        import math
        answers = result.get("answers") if isinstance(result, dict) else None
        if not isinstance(answers, dict):
            raise JevError("Jev response has no valid answers object")
        # Preserve legacy fallback only when the dedicated field is absent.
        for field in ("diagnosis_established", "remediation_identified", "resolution_verified"):
            if field not in answers and field == "diagnosis_established" and "evidence_sufficient" in answers:
                continue
            if field not in answers:
                raise JevError(f"Jev response missing {field}")
        for name in ("evidence_sufficient", "diagnosis_established", "remediation_identified",
                     "resolution_verified", "hardware_failure_likely", "professional_service_needed"):
            if name not in answers:
                continue
            record = answers[name]
            if not isinstance(record, dict) or record.get("type") != "noul":
                raise JevError(f"Invalid Jev {name} answer shape")
            value = record.get("noul")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise JevError(f"Invalid Jev {name} probability")

    def evaluate(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = self.build_payload(state, self.model)
        return self._post(payload)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            endpoint = validate_jev_endpoint(self.endpoint)
            started = time.perf_counter()
            response = requests.post(
                endpoint,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if 300 <= response.status_code < 400:
                raise JevError('Jev redirects are not allowed; configure the final HTTPS endpoint.')
            if response.status_code >= 400:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text
                request_id = response.headers.get("x-typesafe-request-id")
                request_suffix = f"; request_id={request_id}" if request_id else ""
                raise JevError(
                    f"Jev API HTTP {response.status_code} at {self.endpoint}: {detail}{request_suffix}"
                )

            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
                raise JevError(f"Jev API returned an unexpected response shape: {data!r}")
            data["_techmedic"] = {
                "jev_response_time_ms": round(elapsed_ms, 1),
                "endpoint": self.endpoint,
                "route": self.route_name,
            }
            return data
        except JevError:
            raise
        except requests.RequestException as exc:
            raise JevError(f"Jev API request failed at {self.endpoint}: {exc}") from exc
        except ValueError as exc:
            raise JevError(f"Jev API returned invalid JSON from {self.endpoint}: {exc}") from exc
