from __future__ import annotations

from typing import Any


# This is a deliberately conservative MVP safety screen. It is not a substitute
# for domain-specific safety engineering.
BLOCK_PATTERNS = {
    "high voltage": "High-voltage work is outside the v1.x scope.",
    "mains voltage": "Mains-voltage work is outside the v1.x scope.",
    "open the power supply": "Opening a power supply can expose hazardous stored energy.",
    "disassemble the power supply": "Opening a power supply can expose hazardous stored energy.",
    "lithium battery": "Damaged or opened lithium batteries can create fire and chemical hazards.",
}

WARNING_PATTERNS = {
    "format disk": "This action may destroy data. Confirm backups and target selection first.",
    "format the disk": "This action may destroy data. Confirm backups and target selection first.",
    "delete partition": "This action may destroy data.",
    "factory reset": "A factory reset can erase settings or local data.",
    "flash firmware": "Firmware flashing can make a device unusable if interrupted or incorrect.",
    "update bios": "BIOS/UEFI updates carry recovery risk and require model-specific instructions.",
    "registry": "Registry changes can affect system stability; backup and precise scope are required.",
    "rm -rf": "This command can irreversibly delete files.",
    "diskpart clean": "This command can erase partition information and data.",
}


def assess_candidate_tests(state: dict[str, Any]) -> dict[str, Any]:
    text_parts: list[str] = []
    for test in state.get("candidate_next_tests", []):
        if isinstance(test, dict):
            text_parts.extend(str(test.get(key, "")) for key in ("name", "instructions", "purpose"))
    text = "\n".join(text_parts).lower()

    blocked_reasons = [reason for pattern, reason in BLOCK_PATTERNS.items() if pattern in text]
    warnings = [reason for pattern, reason in WARNING_PATTERNS.items() if pattern in text]

    return {
        "blocked": bool(blocked_reasons),
        "risk_level": "high" if blocked_reasons else ("moderate" if warnings else "low"),
        "blocked_reasons": blocked_reasons,
        "warnings": warnings,
    }
