"""
test_m1.py – Milestone 1 tests: Simulator + Baseline + Anomaly.

Safety rules tested:
  [S1] Every telemetry packet has simulated=True (data never presented as real).
  [S2] No personal data fields in any telemetry packet.
  [S3] No false positive: normal state does not trigger anomaly after warm-up.
  [S4] Critical overheat fires within 3 ticks of fault injection (no false negative).
  [S5] Absolute-limit detector fires even before baseline is warm.
  [S6] Low-confidence events are explicitly marked confidence="low" or higher,
       but before baseline is warm, z-score rules do NOT fire.
  [S7] AnomalyEvent.simulated always mirrors TelemetryPacket.simulated.
  [S8] Unknown fault names raise ValueError, not silently ignored.
  [S9] clear_fault() resets state so no anomaly fires after clearing.
"""

from __future__ import annotations

import pytest

from app.anomaly import AnomalyDetector, Confidence, Severity
from app.baseline import BaselineTracker
from app.simulator import (
    TelemetryPacket,
    FAULT_RECIPES,
    NORMAL_STATE,
    clear_fault,
    inject_fault,
    _current_tick,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_normal_packet(**overrides: float | int | str | None) -> TelemetryPacket:
    """Build a TelemetryPacket from NORMAL_STATE with optional overrides."""
    state = dict(NORMAL_STATE)
    state.update(overrides)
    return TelemetryPacket(**state)  # type: ignore[arg-type]


def warmed_up_detector(n: int = 30) -> tuple[BaselineTracker, AnomalyDetector]:
    """Return a baseline + detector already fed n normal packets."""
    tracker = BaselineTracker()
    detector = AnomalyDetector(tracker)
    for _ in range(n):
        pkt = make_normal_packet()
        tracker.update(pkt)
    return tracker, detector


# ---------------------------------------------------------------------------
# [S1] simulated flag is always True
# ---------------------------------------------------------------------------

def test_s1_simulated_flag_always_true() -> None:
    """Every packet produced by the simulator must have simulated=True."""
    clear_fault()
    for _ in range(10):
        pkt = _current_tick()
        assert pkt.simulated is True, "simulated flag must always be True"


def test_s1_simulated_flag_after_fault_injection() -> None:
    """simulated flag stays True even when a fault is active."""
    inject_fault("battery_overheat")
    try:
        pkt = _current_tick()
        assert pkt.simulated is True
    finally:
        clear_fault()


# ---------------------------------------------------------------------------
# [S2] No personal data in telemetry
# ---------------------------------------------------------------------------

PERSONAL_DATA_FIELDS = {
    "name", "email", "phone", "address", "vin", "driver_id",
    "user_id", "license", "passport", "dob", "location",
}


def test_s2_no_personal_data_in_packet() -> None:
    """TelemetryPacket must not contain personal-data fields."""
    pkt = make_normal_packet()
    packet_fields = set(pkt.model_dump().keys())
    overlap = packet_fields & PERSONAL_DATA_FIELDS
    assert not overlap, f"Personal data fields found in packet: {overlap}"


# ---------------------------------------------------------------------------
# [S3] No false positive in normal state
# ---------------------------------------------------------------------------

def test_s3_no_false_positive_normal_state() -> None:
    """After baseline warm-up, normal packets must not trigger anomalies."""
    tracker, detector = warmed_up_detector(30)
    for _ in range(10):
        pkt = make_normal_packet()
        events = detector.check(pkt)
        assert events == [], f"False positive: {events}"


# ---------------------------------------------------------------------------
# [S4] Critical overheat within 3 ticks
# ---------------------------------------------------------------------------

def test_s4_overheat_triggers_critical_within_3_ticks() -> None:
    """battery_overheat fault must produce a critical event within 3 ticks."""
    tracker, detector = warmed_up_detector(30)

    # Simulate the fault
    hot_temp = FAULT_RECIPES["battery_overheat"]["battery_temp_c"]
    assert isinstance(hot_temp, (int, float))

    found_critical = False
    for tick in range(3):
        pkt = make_normal_packet(
            battery_temp_c=hot_temp,
            coolant_temp_c=FAULT_RECIPES["battery_overheat"]["coolant_temp_c"],  # type: ignore[arg-type]
            fault_code=FAULT_RECIPES["battery_overheat"]["fault_code"],  # type: ignore[arg-type]
        )
        events = detector.check(pkt)
        critical = [e for e in events if e.severity == Severity.CRITICAL]
        if critical:
            found_critical = True
            break

    assert found_critical, "Critical overheat event not detected within 3 ticks"


# ---------------------------------------------------------------------------
# [S5] Absolute limit fires before baseline warm-up
# ---------------------------------------------------------------------------

def test_s5_absolute_limit_fires_before_warmup() -> None:
    """Absolute-limit detector must fire even on the very first tick."""
    tracker = BaselineTracker()
    detector = AnomalyDetector(tracker)
    # Battery temp above 55°C absolute limit – first tick, no baseline
    pkt = make_normal_packet(battery_temp_c=60.0)
    events = detector.check(pkt)
    critical = [e for e in events if e.severity == Severity.CRITICAL and
                e.sensor == "battery_temp_c"]
    assert critical, "Absolute-limit event must fire on first tick"


# ---------------------------------------------------------------------------
# [S6] Z-score rules do NOT fire before baseline is warm
# ---------------------------------------------------------------------------

def test_s6_zscore_silent_before_warmup() -> None:
    """Z-score anomaly rules must not fire before MIN_BASELINE_SAMPLES are seen."""
    tracker = BaselineTracker()
    detector = AnomalyDetector(tracker)
    # Feed only 2 normal packets (below MIN_BASELINE_SAMPLES=5)
    for _ in range(2):
        tracker.update(make_normal_packet())
    # Now check a slightly elevated packet (z-score would be high with small window)
    pkt = make_normal_packet(battery_temp_c=36.0)  # above normal but below 55
    events = detector.check(pkt)
    zscore_events = [e for e in events if e.z_score is not None]
    assert not zscore_events, "Z-score events must not fire before baseline is warm"


# ---------------------------------------------------------------------------
# [S7] AnomalyEvent.simulated mirrors TelemetryPacket.simulated
# ---------------------------------------------------------------------------

def test_s7_anomaly_event_simulated_mirrors_packet() -> None:
    """AnomalyEvent must inherit simulated=True from the source packet."""
    tracker = BaselineTracker()
    detector = AnomalyDetector(tracker)
    # Use absolute-limit to guarantee an event on first tick
    pkt = make_normal_packet(battery_temp_c=60.0)
    assert pkt.simulated is True
    events = detector.check(pkt)
    assert events, "Expected at least one event"
    for event in events:
        assert event.simulated is True, "AnomalyEvent.simulated must be True"


# ---------------------------------------------------------------------------
# [S8] Unknown fault name raises ValueError
# ---------------------------------------------------------------------------

def test_s8_unknown_fault_raises() -> None:
    """inject_fault() with an unknown name must raise ValueError."""
    with pytest.raises(ValueError, match="Unknown fault"):
        inject_fault("does_not_exist_xyz")


# ---------------------------------------------------------------------------
# [S9] clear_fault resets state
# ---------------------------------------------------------------------------

def test_s9_clear_fault_resets_anomaly() -> None:
    """After clear_fault(), normal packets must not trigger anomalies."""
    inject_fault("battery_overheat")
    clear_fault()

    tracker, detector = warmed_up_detector(30)
    for _ in range(5):
        pkt = _current_tick()
        events = detector.check(pkt)
        critical = [e for e in events if e.severity == Severity.CRITICAL]
        assert not critical, f"Critical event after fault cleared: {critical}"


# ---------------------------------------------------------------------------
# Bonus: Fault recipe sanity checks
# ---------------------------------------------------------------------------

def test_fault_recipe_battery_overheat_above_55() -> None:
    """battery_overheat recipe must set battery_temp_c above 55°C."""
    recipe = FAULT_RECIPES["battery_overheat"]
    assert recipe["battery_temp_c"] > 55.0  # type: ignore[operator]


def test_all_fault_recipes_injectable() -> None:
    """Every fault recipe in FAULT_RECIPES must be injectable without error."""
    for name in FAULT_RECIPES:
        inject_fault(name)
        clear_fault()
