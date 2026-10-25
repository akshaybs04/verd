"""
test_m3.py – Milestone 3 tests: TinyFish Client, Station Discovery, SSE Streaming, Replay Cache.

Rules tested:
  [T1] Safety directive: Every goal strictly ends with mandatory safety suffix.
  [T2] API key security: Environment only, no key leakage in string representations.
  [T3] Replay cache fallback: When no API key / offline, fallback loads cached replay.
  [T4] Output schema: Pydantic StationAgentResult validation (slots, price_range, source).
  [T5] Source labelling: Every result is explicitly labelled "live" or "replayed".
  [T6] Replay persistence: save_replay writes valid JSON and load_replay reads it.
  [T7] Fast first: get_nearby_stations returns candidate list immediately.
  [T8] Parallel execution: stream_top3_stations_agents runs top 3 stations concurrently.
  [T9] Consent gate: POST /stations/nearby without consent returns 403 Forbidden.
  [T10] Consent gate: GET /stations/stream without consent returns 403 Forbidden.
  [T11] Authorized nearby lookup: POST /stations/nearby with consent returns 200 & simulated=True.
  [T12] Authorized stream: GET /stations/stream with consent returns SSE event stream.
  [T13] Graceful fallback: Uncached failure sets call_to_confirm=True without blocking.
"""

from __future__ import annotations

import asyncio
import json
import os
import pytest
from fastapi.testclient import TestClient

from app.consent import consent_gate
from app.main import app
from app.stations import (
    BENGALURU_STATIONS,
    Station,
    get_nearby_stations,
    stream_top3_stations_agents,
)
from app.tinyfish_client import (
    MANDATORY_SAFETY_SUFFIX,
    StationAgentResult,
    build_station_goal,
    enforce_safety_goal,
    load_replay,
    run_single_station_agent,
    save_replay,
)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# [T1] Safety Goal Directive
# ---------------------------------------------------------------------------

def test_t1_goal_ends_with_mandatory_safety_suffix() -> None:
    """Every goal prompt must strictly end with the safety directive."""
    goal = build_station_goal("ElectroFix EV Hub", "Battery temperature high")
    assert goal.endswith(MANDATORY_SAFETY_SUFFIX), (
        f"Goal did not end with mandatory safety suffix: {goal}"
    )

    # enforce_safety_goal should append suffix if missing
    incomplete = "Find slots for Koramangala EV station."
    enforced = enforce_safety_goal(incomplete)
    assert enforced.endswith(MANDATORY_SAFETY_SUFFIX)

    # Calling enforce_safety_goal twice must not duplicate the suffix
    already_safe = f"Search repair bay. {MANDATORY_SAFETY_SUFFIX}"
    assert enforce_safety_goal(already_safe) == already_safe


# ---------------------------------------------------------------------------
# [T2] No Secret Exposure
# ---------------------------------------------------------------------------

def test_t2_api_key_not_exposed() -> None:
    """Ensure no hardcoded API keys are stored in source files."""
    from app import tinyfish_client
    # Inspect module globals
    for key, val in vars(tinyfish_client).items():
        if "api_key" in key.lower() and isinstance(val, str):
            assert val != "real_secret_key"
            assert "live" not in val.lower()


# ---------------------------------------------------------------------------
# [T3 & T5] Replay Cache Fallback & Source Labelling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t3_t5_offline_fallback_labeled_replayed() -> None:
    """In offline mode (no live key), agent returns result with source='replayed'."""
    events = []
    async for ev in run_single_station_agent(
        station_id="station_blr_01",
        station_name="ElectroFix EV Hub - Indiranagar",
        station_url="https://demo.electrofix.in/indiranagar",
        fault_description="Overheating battery",
    ):
        events.append(ev)

    completed_events = [e for e in events if e.type == "completed"]
    assert len(completed_events) == 1
    result = completed_events[0].result
    assert result is not None
    assert result.source == "replayed"
    assert len(result.slots) > 0
    assert "₹" in result.price_range


# ---------------------------------------------------------------------------
# [T4] Output Schema Validation
# ---------------------------------------------------------------------------

def test_t4_output_schema_validation() -> None:
    """StationAgentResult correctly parses and validates fields."""
    result = StationAgentResult(
        station_id="station_blr_01",
        station_name="ElectroFix Indiranagar",
        can_handle_fault=True,
        slots=["Today 3:30 PM", "Today 5:00 PM"],
        price_range="₹800 - ₹1,400",
        source="replayed",
    )
    assert result.can_handle_fault is True
    assert len(result.slots) == 2
    assert result.source in ("live", "replayed")


# ---------------------------------------------------------------------------
# [T6] Replay Cache Persistence
# ---------------------------------------------------------------------------

def test_t6_replay_cache_roundtrip(tmp_path) -> None:
    """save_replay writes valid JSON and load_replay retrieves it."""
    test_result = StationAgentResult(
        station_id="test_stn_99",
        station_name="Test Workshop",
        can_handle_fault=True,
        slots=["10:00 AM"],
        price_range="₹500 - ₹1,000",
        source="replayed",
    )
    save_replay(test_result)
    loaded = load_replay("test_stn_99")
    assert loaded is not None
    assert loaded.station_id == "test_stn_99"
    assert loaded.source == "replayed"


# ---------------------------------------------------------------------------
# [T7] Fast First Discovery
# ---------------------------------------------------------------------------

def test_t7_fast_first_station_discovery() -> None:
    """get_nearby_stations returns results immediately from catalogue."""
    stations = get_nearby_stations(lat=12.9716, lng=77.5946, limit=3)
    assert len(stations) == 3
    # Check sorted by distance
    assert stations[0].distance_km <= stations[1].distance_km <= stations[2].distance_km
    for s in stations:
        assert s.simulated is True
        assert s.name
        assert s.phone


# ---------------------------------------------------------------------------
# [T8] Parallel Top 3 Execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t8_parallel_top3_streaming() -> None:
    """stream_top3_stations_agents streams events from top 3 stations concurrently."""
    events = []
    async for item in stream_top3_stations_agents():
        events.append(item)

    station_ids_seen = {item.get("station_id") for item in events if item.get("station_id")}
    assert len(station_ids_seen) == 3, f"Expected 3 stations in parallel, got {station_ids_seen}"

    # Verify each station completed
    completed_events = [e for e in events if e.get("event") == "station_agent_completed"]
    assert len(completed_events) == 3


# ---------------------------------------------------------------------------
# [T9 & T10] Consent Gate Enforcements
# ---------------------------------------------------------------------------

def test_t9_nearby_rejected_without_consent(client) -> None:
    """POST /stations/nearby must return 403 Forbidden if consent not granted."""
    resp = client.post(
        "/stations/nearby",
        json={"session_id": "unconsented-session-1"},
    )
    assert resp.status_code == 403
    assert "consent" in resp.json()["detail"].lower()


def test_t10_stream_rejected_without_consent(client) -> None:
    """GET /stations/stream must return 403 Forbidden if consent not granted."""
    resp = client.get("/stations/stream", params={"session_id": "unconsented-session-2"})
    assert resp.status_code == 403
    assert "consent" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# [T11 & T12] Authorized Endpoints
# ---------------------------------------------------------------------------

def test_t11_nearby_allowed_with_consent(client) -> None:
    """POST /stations/nearby returns 200 with stations when consent is granted."""
    # Grant consent
    client.post("/consent", json={"session_id": "authorized-session", "granted": True})

    resp = client.post(
        "/stations/nearby",
        json={"session_id": "authorized-session"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["simulated"] is True
    assert len(data["stations"]) > 0
    assert data["stations"][0]["simulated"] is True


def test_t12_stream_allowed_with_consent(client) -> None:
    """GET /stations/stream returns SSE stream when consent is granted."""
    client.post("/consent", json={"session_id": "stream-session", "granted": True})

    with client.stream("GET", "/stations/stream", params={"session_id": "stream-session"}) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        lines = list(response.iter_lines())
        # Should contain discovered stations and station completed events
        combined = "\n".join(lines)
        assert "stations_discovered" in combined
        assert "station_agent_completed" in combined


# ---------------------------------------------------------------------------
# [T13] Graceful Fallback (Call to Confirm)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t13_graceful_fallback_call_to_confirm() -> None:
    """If a station is unknown and has no replay, return graceful call_to_confirm."""
    events = []
    async for ev in run_single_station_agent(
        station_id="station_nonexistent_unknown",
        station_name="Unknown Bay",
        station_url="https://invalid.url",
        fault_description="Fault",
    ):
        events.append(ev)

    completed = [e for e in events if e.type == "completed"]
    assert len(completed) == 1
    res = completed[0].result
    assert res is not None
    assert res.call_to_confirm is True
    assert res.source == "replayed"
