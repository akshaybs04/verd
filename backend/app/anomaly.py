"""
anomaly.py – Z-score anomaly detector for VERD.

Compares each incoming telemetry tick against the rolling baseline.
Emits AnomalyEvent Pydantic models; never mutates sensor data.

Safety rules enforced here:
- simulated flag is always forwarded from the source packet.
- If confidence is low (baseline not ready), severity is capped at "warning".
- "I cannot tell" is expressed as confidence="low" in the event.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import NamedTuple

from pydantic import BaseModel, Field

from app.baseline import BaselineTracker, TRACKED_SENSORS
from app.simulator import TelemetryPacket


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# (sensor, z-score threshold, severity)
SENSOR_RULES: list[tuple[str, float, str]] = [
    ("battery_temp_c", 2.5, "critical"),   # primary demo fault
    ("motor_temp_c",   2.5, "critical"),
    ("coolant_temp_c", 2.5, "warning"),
    ("battery_soc_pct", -2.5, "warning"),  # negative: low is bad
    ("voltage_v",      -2.5, "warning"),
    ("current_a",       3.0, "warning"),
]

# Absolute safety floors (no baseline needed – always critical)
ABSOLUTE_LIMITS: list[tuple[str, float, str, str]] = [
    # (sensor, threshold, direction, severity)
    ("battery_temp_c", 55.0, "above", "critical"),
    ("motor_temp_c",   85.0, "above", "critical"),
    ("battery_soc_pct", 5.0, "below", "warning"),
]

MIN_BASELINE_SAMPLES = 5  # Need at least this many ticks before z-score is reliable


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"  # → UI says "I cannot tell"


class AnomalyEvent(BaseModel):
    """An anomaly detected in one telemetry tick."""

    timestamp: float = Field(default_factory=time.time)
    simulated: bool = True  # Always forwarded from source packet

    sensor: str
    current_value: float
    baseline_mean: float | None
    baseline_std: float | None
    z_score: float | None

    severity: Severity
    confidence: Confidence
    fault_code: str | None = None

    # Human-readable trigger description (used by explainer.py)
    trigger: str  # e.g. "battery_temp_c above absolute limit 55.0°C"


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """Stateless detector: call check(packet) each tick."""

    def __init__(self, tracker: BaselineTracker) -> None:
        self._tracker = tracker

    def check(self, packet: TelemetryPacket) -> list[AnomalyEvent]:
        """Return a list of AnomalyEvents (may be empty) for this tick."""
        events: list[AnomalyEvent] = []
        data = packet.model_dump()

        # 1. Absolute limits (no baseline needed, always fire)
        for sensor, threshold, direction, severity in ABSOLUTE_LIMITS:
            value = data.get(sensor)
            if not isinstance(value, (int, float)):
                continue
            triggered = (
                (direction == "above" and value > threshold)
                or (direction == "below" and value < threshold)
            )
            if triggered:
                events.append(AnomalyEvent(
                    simulated=packet.simulated,
                    sensor=sensor,
                    current_value=float(value),
                    baseline_mean=None,
                    baseline_std=None,
                    z_score=None,
                    severity=Severity(severity),
                    confidence=Confidence.HIGH,
                    fault_code=packet.fault_code,
                    trigger=(
                        f"{sensor} {direction} absolute limit {threshold} "
                        f"(value={value:.1f})"
                    ),
                ))

        # 2. Z-score rules (require baseline)
        for sensor, z_threshold, severity in SENSOR_RULES:
            value = data.get(sensor)
            if not isinstance(value, (int, float)):
                continue
            stats = self._tracker.get_stats(sensor)
            if stats is None or not stats.ready:
                # Baseline not ready → cannot tell, skip z-score
                continue

            mean = stats.mean
            std = stats.std
            if std < 1e-9:
                continue  # All readings identical → no meaningful z-score

            z = (float(value) - mean) / std

            # For negative-direction sensors (soc, voltage) threshold is negative
            triggered = (z_threshold > 0 and z > z_threshold) or (
                z_threshold < 0 and z < z_threshold
            )
            if triggered:
                # Don't duplicate absolute-limit events for same sensor
                already = any(e.sensor == sensor for e in events)
                if already:
                    continue
                confidence = (
                    Confidence.HIGH
                    if len(stats.window) >= stats.maxlen // 2
                    else Confidence.MEDIUM
                )
                events.append(AnomalyEvent(
                    simulated=packet.simulated,
                    sensor=sensor,
                    current_value=float(value),
                    baseline_mean=mean,
                    baseline_std=std,
                    z_score=round(z, 2),
                    severity=Severity(severity),
                    confidence=confidence,
                    fault_code=packet.fault_code,
                    trigger=(
                        f"{sensor} z-score={z:.2f} (threshold={z_threshold:+.1f}, "
                        f"mean={mean:.1f}, std={std:.2f})"
                    ),
                ))

        # Sort: critical first
        events.sort(key=lambda e: (e.severity != Severity.CRITICAL, e.sensor))
        return events
