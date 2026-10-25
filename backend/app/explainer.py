"""
explainer.py – Plain-language explanation engine for VERD.

Takes a list of AnomalyEvents from the detector, enriches them with
FaultCauses from the catalogue, and produces an ExplainerResult that
the driver UI renders directly.

Safety rules enforced here:
- simulated is always True (forwarded from source events).
- advisory_only is always True; VERD never controls the car.
- cannot_tell is True when top-cause confidence is LOW.
- show_112 is True for any CRITICAL severity.
- consent_required is always True; outbound calls need driver approval.
- No personal data is included in any field.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from app.anomaly import AnomalyEvent, Confidence, Severity
from app.causes import FaultCause, lookup_cause


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class ExplainerResult(BaseModel):
    """Human-readable explanation of the current vehicle state."""

    timestamp: float = Field(default_factory=time.time)
    simulated: bool = True       # Always True – never presented as real data
    advisory_only: bool = True   # VERD never controls the car – always True
    consent_required: bool = True  # Outbound call always needs driver consent

    # Headline shown at the top of the alert card
    headline: str
    # 2–3 sentence plain-English body
    body: str

    severity: Severity
    confidence: Confidence
    cannot_tell: bool            # True → UI shows "I cannot tell"
    show_112: bool               # True → 112 button shown FIRST (Critical)

    # Evidence links (each string is a raw trigger description from the detector)
    evidence: list[str]

    # All matched causes, sorted critical-first
    causes: list[FaultCause]

    # True when there are no anomalies (normal state)
    all_clear: bool = False


# ---------------------------------------------------------------------------
# Explainer
# ---------------------------------------------------------------------------

_ALL_CLEAR_RESULT = ExplainerResult(
    simulated=True,
    advisory_only=True,
    consent_required=True,
    headline="Everything looks fine",
    body=(
        "All sensors are within normal range. "
        "Keep driving safely. (SIMULATED data – not from a real vehicle.)"
    ),
    severity=Severity.INFO,
    confidence=Confidence.HIGH,
    cannot_tell=False,
    show_112=False,
    evidence=[],
    causes=[],
    all_clear=True,
)


def explain(events: list[AnomalyEvent]) -> ExplainerResult:
    """
    Produce a plain-language ExplainerResult from a list of AnomalyEvents.

    If events is empty, returns a friendly all-clear result.
    The worst-severity event drives the headline and show_112 flag.
    """
    if not events:
        return _ALL_CLEAR_RESULT

    causes: list[FaultCause] = []
    evidence: list[str] = []

    for event in events:
        cause = lookup_cause(
            sensor=event.sensor,
            fault_code=event.fault_code,
            evidence_tag=event.trigger,
            severity=event.severity,
        )
        causes.append(cause)
        evidence.append(event.trigger)

    # Worst event drives top-level fields
    worst = events[0]  # already sorted critical-first by detector
    top_cause = causes[0]

    cannot_tell = top_cause.confidence == Confidence.LOW
    show_112 = worst.severity == Severity.CRITICAL

    # Build headline
    if cannot_tell:
        headline = "I cannot tell what is wrong"
    else:
        headline = top_cause.plain_title

    # Build body
    simulated_note = " (SIMULATED data – not from a real vehicle.)"
    if cannot_tell:
        body = (
            "One or more sensor readings are outside the expected range, but I "
            "cannot determine the exact cause with confidence. "
            "Please have the vehicle inspected by a qualified technician."
            + simulated_note
        )
    elif len(causes) > 1:
        secondary_titles = ", ".join(c.plain_title for c in causes[1:3])
        body = (
            top_cause.plain_explanation
            + f" Additional issues detected: {secondary_titles}."
            + simulated_note
        )
    else:
        body = top_cause.plain_explanation + simulated_note

    return ExplainerResult(
        simulated=True,
        advisory_only=True,
        consent_required=True,
        headline=headline,
        body=body,
        severity=worst.severity,
        confidence=top_cause.confidence,
        cannot_tell=cannot_tell,
        show_112=show_112,
        evidence=evidence,
        causes=causes,
        all_clear=False,
    )
