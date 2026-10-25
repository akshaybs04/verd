"""
test_m2.py – Milestone 2 tests: Explainer + Consent Gate.

Safety rules tested:
  [E1] ExplainerResult.simulated is always True.
  [E2] ExplainerResult.advisory_only is always True.
  [E3] ExplainerResult.consent_required is always True.
  [E4] When confidence is LOW, cannot_tell=True and headline says "cannot tell".
  [E5] CRITICAL anomaly → show_112=True in result.
  [E6] Non-critical anomaly → show_112=False.
  [E7] Empty events list → all_clear=True, headline is friendly.
  [E8] Plain explanation for battery_overheat is human-readable (no codes).
  [E9] Evidence list is non-empty when events exist.
  [E10] Multiple events: all causes are included, worst drives headline.

  [C1] New session starts PENDING → can_call_outbound=False.
  [C2] PENDING consent blocks outbound call.
  [C3] grant() → GRANTED → can_call_outbound=True.
  [C4] deny() → DENIED → can_call_outbound=False (permanently for session).
  [C5] After deny(), a second grant() call must NOT flip to granted
       (denied is terminal for a session – re-grant requires new session).
  [C6] revoke() resets consent to PENDING for a fresh session.
  [C7] Two different session IDs are completely independent.
  [C8] No personal data is stored in ConsentState.

  [I1] POST /consent granted=True returns status=granted, can_call_outbound=True.
  [I2] POST /consent granted=False returns status=denied, can_call_outbound=False.
  [I3] GET /alerts/current includes explanation with simulated=True.
  [I4] DELETE /me/data resets consent to pending.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.anomaly import AnomalyDetector, AnomalyEvent, Confidence, Severity
from app.baseline import BaselineTracker
from app.causes import lookup_cause
from app.consent import ConsentGate, ConsentStatus
from app.explainer import explain
from app.main import app
from app.simulator import (
    FAULT_RECIPES,
    NORMAL_STATE,
    TelemetryPacket,
    clear_fault,
    inject_fault,
    _current_tick,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_normal_packet(**overrides) -> TelemetryPacket:
    state = dict(NORMAL_STATE)
    state.update(overrides)
    return TelemetryPacket(**state)  # type: ignore[arg-type]


def make_critical_events() -> list[AnomalyEvent]:
    """Produce a critical battery_temp_c event directly."""
    tracker = BaselineTracker()
    detector = AnomalyDetector(tracker)
    pkt = make_normal_packet(
        battery_temp_c=62.0,
        fault_code="P0A1B",
    )
    return detector.check(pkt)


def make_unknown_sensor_event() -> list[AnomalyEvent]:
    """Produce an event for a sensor not in the catalogue → LOW confidence."""
    event = AnomalyEvent(
        simulated=True,
        sensor="unknown_sensor_xyz",
        current_value=999.0,
        baseline_mean=None,
        baseline_std=None,
        z_score=None,
        severity=Severity.WARNING,
        confidence=Confidence.LOW,
        fault_code=None,
        trigger="unknown_sensor_xyz above threshold (value=999.0)",
    )
    return [event]


# ---------------------------------------------------------------------------
# [E] Explainer tests
# ---------------------------------------------------------------------------

def test_e1_simulated_always_true() -> None:
    """ExplainerResult.simulated must always be True."""
    result = explain(make_critical_events())
    assert result.simulated is True

    result_clear = explain([])
    assert result_clear.simulated is True


def test_e2_advisory_only_always_true() -> None:
    """ExplainerResult.advisory_only must always be True."""
    result = explain(make_critical_events())
    assert result.advisory_only is True

    result_clear = explain([])
    assert result_clear.advisory_only is True


def test_e3_consent_required_always_true() -> None:
    """ExplainerResult.consent_required must always be True."""
    result = explain(make_critical_events())
    assert result.consent_required is True

    result_clear = explain([])
    assert result_clear.consent_required is True


def test_e4_low_confidence_sets_cannot_tell() -> None:
    """When top cause confidence is LOW, cannot_tell=True and headline mentions 'cannot tell'."""
    events = make_unknown_sensor_event()
    result = explain(events)
    assert result.cannot_tell is True
    assert "cannot tell" in result.headline.lower()


def test_e5_critical_anomaly_shows_112() -> None:
    """CRITICAL anomaly must set show_112=True."""
    events = make_critical_events()
    assert events, "Expected at least one critical event"
    critical = [e for e in events if e.severity == Severity.CRITICAL]
    assert critical, "Expected critical event"
    result = explain(events)
    assert result.show_112 is True


def test_e6_non_critical_no_112() -> None:
    """WARNING-only anomaly must not set show_112=True."""
    event = AnomalyEvent(
        simulated=True,
        sensor="coolant_temp_c",
        current_value=50.0,
        baseline_mean=40.0,
        baseline_std=2.0,
        z_score=5.0,
        severity=Severity.WARNING,
        confidence=Confidence.MEDIUM,
        fault_code=None,
        trigger="coolant_temp_c z-score=5.0",
    )
    result = explain([event])
    assert result.show_112 is False


def test_e7_empty_events_all_clear() -> None:
    """Empty event list must produce all_clear=True with a friendly headline."""
    result = explain([])
    assert result.all_clear is True
    assert result.show_112 is False
    assert result.severity == Severity.INFO
    assert len(result.headline) > 0


def test_e8_battery_overheat_human_readable() -> None:
    """Battery overheat explanation must be plain English, not raw sensor codes."""
    events = make_critical_events()
    result = explain(events)
    body_lower = result.body.lower()
    # Should contain friendly words
    assert any(word in body_lower for word in ["battery", "cool", "traffic", "overheat"]), \
        f"Explanation body not human-readable: {result.body}"
    # Should NOT contain raw OBD code in body (code may appear in evidence but not body)
    assert "p0a1b" not in result.body.lower(), "Raw fault code in body text"


def test_e9_evidence_nonempty_when_events_exist() -> None:
    """Evidence list must have entries when events are present."""
    events = make_critical_events()
    result = explain(events)
    assert len(result.evidence) > 0


def test_e10_multiple_events_all_causes_included() -> None:
    """All event causes are included in the result; worst drives headline."""
    tracker = BaselineTracker()
    # Feed 30 normal ticks so baseline is warm
    for _ in range(30):
        tracker.update(make_normal_packet())
    detector = AnomalyDetector(tracker)

    # Two simultaneous faults
    pkt = make_normal_packet(
        battery_temp_c=62.0,
        motor_temp_c=91.0,
        fault_code="P0A1B",
    )
    events = detector.check(pkt)
    result = explain(events)

    assert len(result.causes) == len(events)
    # Worst (critical) drives the headline
    assert result.severity == Severity.CRITICAL


# ---------------------------------------------------------------------------
# [C] Consent gate tests
# ---------------------------------------------------------------------------

def test_c1_new_session_is_pending() -> None:
    """A fresh session must start in PENDING state."""
    gate = ConsentGate()
    state = gate.get("session-new")
    assert state.status == ConsentStatus.PENDING
    assert state.can_call_outbound is False


def test_c2_pending_blocks_outbound() -> None:
    """PENDING consent must block outbound calls."""
    gate = ConsentGate()
    assert gate.can_call_outbound("session-pending") is False


def test_c3_grant_enables_outbound() -> None:
    """grant() must set GRANTED and allow outbound calls."""
    gate = ConsentGate()
    state = gate.grant("session-grant")
    assert state.status == ConsentStatus.GRANTED
    assert state.can_call_outbound is True
    assert gate.can_call_outbound("session-grant") is True


def test_c4_deny_blocks_outbound() -> None:
    """deny() must set DENIED and block outbound calls."""
    gate = ConsentGate()
    state = gate.deny("session-deny")
    assert state.status == ConsentStatus.DENIED
    assert state.can_call_outbound is False
    assert gate.can_call_outbound("session-deny") is False


def test_c5_denied_cannot_be_regranted() -> None:
    """
    Once denied, a grant() call for the same session must NOT re-enable outbound.
    Denied is terminal; the driver must start a new session.
    """
    gate = ConsentGate()
    gate.deny("session-terminal")
    # Attempt to grant after denial
    gate.grant("session-terminal")
    # The grant should have overwritten the denial in memory.
    # Per VERD safety rule: denied is terminal for a session.
    # We enforce this by checking that after deny, grant should NOT be allowed
    # to silently override. Let's enforce the invariant in the gate itself.
    # For now the test documents the expected behaviour: denied sessions
    # should not silently flip back to granted without a fresh session.
    # The ConsentGate enforces this by refusing grant() after deny().
    # ---- This will FAIL until we add the guard. Let's assert it. ----
    assert gate.can_call_outbound("session-terminal") is False, (
        "Denied session must not become grantable without a new session_id"
    )


def test_c6_revoke_resets_to_pending() -> None:
    """revoke() must reset consent so the session starts fresh (PENDING)."""
    gate = ConsentGate()
    gate.grant("session-revoke")
    assert gate.can_call_outbound("session-revoke") is True
    gate.revoke("session-revoke")
    assert gate.can_call_outbound("session-revoke") is False
    assert gate.get("session-revoke").status == ConsentStatus.PENDING


def test_c7_sessions_are_independent() -> None:
    """Two sessions must not affect each other."""
    gate = ConsentGate()
    gate.grant("session-A")
    gate.deny("session-B")
    assert gate.can_call_outbound("session-A") is True
    assert gate.can_call_outbound("session-B") is False


def test_c8_no_personal_data_in_consent_state() -> None:
    """ConsentState must not contain any personal-data fields."""
    PERSONAL_FIELDS = {
        "name", "email", "phone", "address", "vin",
        "driver_id", "user_id", "license", "location",
    }
    gate = ConsentGate()
    state = gate.grant("session-pii-check")
    state_fields = set(state.model_dump().keys())
    overlap = state_fields & PERSONAL_FIELDS
    assert not overlap, f"Personal data fields in ConsentState: {overlap}"


# ---------------------------------------------------------------------------
# [I] Integration tests via TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_i1_post_consent_granted(client) -> None:
    """POST /consent with granted=True must return status=granted."""
    resp = client.post(
        "/consent",
        json={"session_id": "integ-grant", "granted": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "granted"
    assert data["can_call_outbound"] is True


def test_i2_post_consent_denied(client) -> None:
    """POST /consent with granted=False must return status=denied."""
    resp = client.post(
        "/consent",
        json={"session_id": "integ-deny", "granted": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "denied"
    assert data["can_call_outbound"] is False


def test_i3_alerts_current_has_explanation(client) -> None:
    """GET /alerts/current must include explanation with simulated=True."""
    resp = client.get("/alerts/current")
    assert resp.status_code == 200
    data = resp.json()
    assert data["simulated"] is True
    assert "explanation" in data
    assert data["explanation"]["simulated"] is True
    assert data["explanation"]["advisory_only"] is True
    assert data["explanation"]["consent_required"] is True


def test_i4_delete_me_data_resets_consent(client) -> None:
    """DELETE /me/data must reset consent to pending for the session."""
    # Grant first
    client.post("/consent", json={"session_id": "del-session", "granted": True})
    resp_check = client.get("/consent/del-session")
    assert resp_check.json()["status"] == "granted"

    # Delete
    resp_del = client.delete("/me/data", params={"session_id": "del-session"})
    assert resp_del.status_code == 200
    assert resp_del.json()["ok"] is True

    # Should be pending now
    resp_after = client.get("/consent/del-session")
    assert resp_after.json()["status"] == "pending"
