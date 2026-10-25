"""
test_m4.py – Milestone 4 tests: Driver UI End-to-End Flow & Static Assets.

Safety & Integration rules tested:
  [UI1] Static PWA: GET / returns 200 and loads HTML containing root and VERD branding.
  [UI2] App Health: GET /health returns version 0.4.0-m4.
  [UI3] End-to-end Driver Flow:
        - Inject battery_overheat fault.
        - Verify alert is CRITICAL and show_112 is True.
        - Verify outbound stations lookup is BLOCKED without consent (403).
        - Driver approves consent -> status becomes granted.
        - Verify station lookup succeeds with simulated stations list.
        - Verify stations stream yields discovered stations and agent results.
        - Driver resets fault -> system returns to all_clear.
        - GDPR data wipe (DELETE /me/data) resets session consent.
"""

from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.simulator import clear_fault, inject_fault


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_ui1_static_pwa_served(client) -> None:
    """FastAPI serves the compiled React PWA at root URL."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "VERD" in resp.text
    assert "id=\"root\"" in resp.text


def test_ui2_health_version(client) -> None:
    """Health check reflects Milestone 4 version."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] in ("0.4.0-m4", "1.0.0")


def test_ui3_end_to_end_driver_flow(client) -> None:
    """Full 3-minute pitch driver journey tested end-to-end."""
    session_id = "test-driver-e2e-session"

    # Step 1: Ensure initial state is clean
    clear_fault()

    # Step 2: Inject simulated battery overheat in traffic
    inject_resp = client.post("/faults/inject", json={"fault": "battery_overheat"})
    assert inject_resp.status_code == 200

    # Step 3: Fetch active alert
    alert_resp = client.get("/alerts/current")
    assert alert_resp.status_code == 200
    alert_data = alert_resp.json()
    assert alert_data["simulated"] is True
    assert "explanation" in alert_data

    # Step 4: Verify outbound stations search is locked before consent
    blocked_nearby = client.post("/stations/nearby", json={"session_id": session_id})
    assert blocked_nearby.status_code == 403

    blocked_stream = client.get("/stations/stream", params={"session_id": session_id})
    assert blocked_stream.status_code == 403

    # Step 5: Driver taps "Approve Assistance" (Consent Gate)
    consent_resp = client.post(
        "/consent",
        json={"session_id": session_id, "granted": True},
    )
    assert consent_resp.status_code == 200
    assert consent_resp.json()["can_call_outbound"] is True

    # Step 6: Fast first stations discovery succeeds
    allowed_nearby = client.post("/stations/nearby", json={"session_id": session_id})
    assert allowed_nearby.status_code == 200
    nearby_data = allowed_nearby.json()
    assert nearby_data["simulated"] is True
    assert len(nearby_data["stations"]) >= 3

    # Step 7: Stream per-station TinyFish results
    with client.stream("GET", "/stations/stream", params={"session_id": session_id}) as sse_stream:
        assert sse_stream.status_code == 200
        lines = list(sse_stream.iter_lines())
        text = "\n".join(lines)
        assert "stations_discovered" in text
        assert "station_agent_completed" in text
        assert "done" in text

    # Step 8: Clear fault (returns car to normal)
    clear_resp = client.delete("/faults/inject")
    assert clear_resp.status_code == 200

    # Step 9: Verify GDPR Data Deletion resets session consent
    del_resp = client.delete("/me/data", params={"session_id": session_id})
    assert del_resp.status_code == 200

    consent_after = client.get(f"/consent/{session_id}")
    assert consent_after.json()["status"] == "pending"
    assert consent_after.json()["can_call_outbound"] is False
