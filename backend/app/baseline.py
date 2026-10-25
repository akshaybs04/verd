"""
baseline.py – Rolling-window baseline statistics for VERD anomaly detection.

Maintains a per-sensor circular buffer of recent readings.
Computes mean and standard deviation over the window without storing PII.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from app.simulator import TelemetryPacket

# Sensors we track for anomaly detection
TRACKED_SENSORS: list[str] = [
    "battery_temp_c",
    "battery_soc_pct",
    "motor_rpm",
    "motor_temp_c",
    "coolant_temp_c",
    "speed_kmh",
    "voltage_v",
    "current_a",
]

DEFAULT_WINDOW = 30  # ticks (≈30 seconds at 1 Hz)


@dataclass
class SensorStats:
    """Running stats for one sensor."""

    window: Deque[float] = field(default_factory=deque)
    maxlen: int = DEFAULT_WINDOW

    def push(self, value: float) -> None:
        if len(self.window) >= self.maxlen:
            self.window.popleft()
        self.window.append(value)

    @property
    def mean(self) -> float:
        if not self.window:
            return 0.0
        return sum(self.window) / len(self.window)

    @property
    def std(self) -> float:
        n = len(self.window)
        if n < 2:
            return 0.0
        m = self.mean
        variance = sum((x - m) ** 2 for x in self.window) / (n - 1)
        return variance ** 0.5

    @property
    def ready(self) -> bool:
        """True once we have enough data to be statistically meaningful."""
        return len(self.window) >= max(5, self.maxlen // 6)


class BaselineTracker:
    """Tracks rolling baselines for all TRACKED_SENSORS."""

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        self._stats: dict[str, SensorStats] = {
            sensor: SensorStats(maxlen=window) for sensor in TRACKED_SENSORS
        }

    def update(self, packet: TelemetryPacket) -> None:
        """Push one telemetry packet into all sensor buffers."""
        data = packet.model_dump()
        for sensor in TRACKED_SENSORS:
            value = data.get(sensor)
            if isinstance(value, (int, float)):
                self._stats[sensor].push(float(value))

    def get_stats(self, sensor: str) -> SensorStats | None:
        return self._stats.get(sensor)

    def snapshot(self) -> dict[str, dict[str, float]]:
        """Return mean/std for all sensors (for debugging / UI)."""
        return {
            sensor: {
                "mean": stats.mean,
                "std": stats.std,
                "n": len(stats.window),
            }
            for sensor, stats in self._stats.items()
        }
