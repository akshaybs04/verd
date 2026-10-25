"""
causes.py – Fault cause catalogue for VERD.

Maps sensor triggers and OBD fault codes to structured FaultCause objects.
Each cause carries a plain-English explanation, confidence level, and
evidence tag so the UI can link every claim to its source.

Safety rules:
- advisory_only is always True; VERD never controls the car.
- show_112 is True for any CRITICAL cause.
- If no cause matches, confidence is LOW → UI must say "I cannot tell".
"""

from __future__ import annotations

from app.anomaly import Confidence, Severity
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class FaultCause(BaseModel):
    """A structured, human-readable cause for an anomaly."""

    sensor: str
    fault_code: str | None = None

    # Plain-language fields (shown directly in the UI)
    plain_title: str
    plain_explanation: str

    confidence: Confidence
    severity: Severity

    advisory_only: bool = True   # VERD never controls the car – always True
    show_112: bool = False       # True when severity is CRITICAL
    evidence_tag: str            # E.g. "battery_temp_c = 62.1 °C > limit 55 °C"


# ---------------------------------------------------------------------------
# Cause catalogue
# ---------------------------------------------------------------------------

# Each entry: (sensor, fault_code_prefix_or_None, title, explanation, confidence)
_CATALOGUE: list[tuple[str, str | None, str, str, Confidence]] = [
    (
        "battery_temp_c",
        "P0A1B",
        "Battery overheating",
        (
            "Your battery is much hotter than normal. "
            "This often happens in slow traffic on a hot day because the cooling "
            "system can't keep up. Stop safely when you can and let the car cool "
            "down before driving further."
        ),
        Confidence.HIGH,
    ),
    (
        "battery_temp_c",
        None,
        "Battery running hot",
        (
            "The battery temperature is higher than usual. "
            "This may be due to heavy use, warm weather, or a cooling issue. "
            "Monitor it closely; if it keeps rising, pull over safely."
        ),
        Confidence.MEDIUM,
    ),
    (
        "motor_temp_c",
        "P0B3F",
        "Motor overheating",
        (
            "The electric motor is running hotter than it should. "
            "Ease off the accelerator and reduce speed where safe. "
            "If the warning persists, stop the car and call a technician."
        ),
        Confidence.HIGH,
    ),
    (
        "motor_temp_c",
        None,
        "Motor running hot",
        (
            "Motor temperature is above the normal range. "
            "Reduce load on the drivetrain if possible."
        ),
        Confidence.MEDIUM,
    ),
    (
        "coolant_temp_c",
        None,
        "Coolant temperature high",
        (
            "The coolant is warmer than expected, which may indicate a cooling "
            "system issue. Watch for other warning signs and consider having the "
            "system checked at a service centre."
        ),
        Confidence.MEDIUM,
    ),
    (
        "battery_soc_pct",
        "P0AFA",
        "Battery charge very low",
        (
            "Your battery charge is critically low. "
            "Find a charging station as soon as possible to avoid being stranded."
        ),
        Confidence.HIGH,
    ),
    (
        "battery_soc_pct",
        None,
        "Battery charge low",
        (
            "The battery state of charge has dropped below the normal range. "
            "Plan a charging stop soon."
        ),
        Confidence.MEDIUM,
    ),
    (
        "voltage_v",
        None,
        "Pack voltage low",
        (
            "The high-voltage pack voltage is lower than expected. "
            "This can affect performance and range. A service check is advised."
        ),
        Confidence.MEDIUM,
    ),
    (
        "current_a",
        None,
        "Unusual current draw",
        (
            "The electrical current draw is higher than normal. "
            "This may be a temporary spike or a sign of an electrical fault."
        ),
        Confidence.MEDIUM,
    ),
]

# Index: (sensor, fault_code) → FaultCause
# We build two lookups: exact (sensor+code) and fallback (sensor only, code=None)
_EXACT: dict[tuple[str, str], FaultCause] = {}
_FALLBACK: dict[str, FaultCause] = {}

for _sensor, _code, _title, _explanation, _confidence in _CATALOGUE:
    _severity = (
        Severity.CRITICAL
        if _confidence == Confidence.HIGH and "overheat" in _title.lower()
        else Severity.WARNING
    )
    _cause = FaultCause(
        sensor=_sensor,
        fault_code=_code,
        plain_title=_title,
        plain_explanation=_explanation,
        confidence=_confidence,
        severity=_severity,
        advisory_only=True,
        show_112=(_severity == Severity.CRITICAL),
        evidence_tag="",  # filled in at lookup time with actual values
    )
    if _code is not None:
        _EXACT[(_sensor, _code)] = _cause
    elif _sensor not in _FALLBACK:
        _FALLBACK[_sensor] = _cause


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def lookup_cause(
    sensor: str,
    fault_code: str | None,
    evidence_tag: str,
    severity: Severity,
) -> FaultCause:
    """
    Return the best-matching FaultCause for a sensor + optional fault code.

    Falls back to a generic LOW-confidence cause if nothing matches,
    which will cause the UI to display "I cannot tell".
    """
    cause: FaultCause | None = None

    # 1. Exact match (sensor + fault code)
    if fault_code and (_key := (sensor, fault_code)) in _EXACT:
        cause = _EXACT[_key].model_copy()

    # 2. Sensor-only fallback
    if cause is None and sensor in _FALLBACK:
        cause = _FALLBACK[sensor].model_copy()

    # 3. Unknown – "I cannot tell"
    if cause is None:
        cause = FaultCause(
            sensor=sensor,
            fault_code=fault_code,
            plain_title="Unexpected sensor reading",
            plain_explanation=(
                "I cannot tell what is causing this reading. "
                "Please have the vehicle inspected by a qualified technician."
            ),
            confidence=Confidence.LOW,
            severity=severity,
            advisory_only=True,
            show_112=(severity == Severity.CRITICAL),
            evidence_tag=evidence_tag,
        )

    # Stamp evidence and severity from the live event
    cause = cause.model_copy(update={
        "evidence_tag": evidence_tag,
        "severity": severity,
        "show_112": (severity == Severity.CRITICAL),
    })
    return cause
