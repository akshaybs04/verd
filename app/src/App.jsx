import React, { useState, useEffect, useRef } from 'react';

function getSessionId() {
  let sid = sessionStorage.getItem('verd_session_id');
  if (!sid) {
    sid = 'session_' + Math.random().toString(36).substring(2, 10);
    sessionStorage.setItem('verd_session_id', sid);
  }
  return sid;
}

export default function App() {
  const [sessionId] = useState(getSessionId);
  const [role, setRole] = useState('driver'); // 'driver' | 'owner' | 'fleet' | 'privacy'
  const [telemetry, setTelemetry] = useState({
    speed_kmh: 36.0,
    soc_pct: 74.0,
    battery_temp_c: 34.0,
    coolant_temp_c: 40.0,
    ambient_temp_c: 32.0,
    fault_code: null,
  });
  const [alertData, setAlertData] = useState({
    simulated: true,
    count: 0,
    events: [],
    explanation: {
      headline: "All vehicle systems operating nominally.",
      body: "Battery thermal loop and cooling systems are within expected operational bounds.",
      severity: "INFO",
      cannot_tell: false,
      all_clear: true,
      show_112: false,
      advisory_only: true,
      consent_required: true,
      evidence: [],
    },
  });
  const [consentStatus, setConsentStatus] = useState('pending');
  const [stations, setStations] = useState([]);
  const [stationAgentResults, setStationAgentResults] = useState({});
  const [agentProgress, setAgentProgress] = useState({});
  const [bookedTicket, setBookedTicket] = useState(null);
  const [showEvidence, setShowEvidence] = useState(false);
  const [activeStreamingUrl, setActiveStreamingUrl] = useState(null);
  const [isInjecting, setIsInjecting] = useState(false);
  const [emergencyAlertModal, setEmergencyAlertModal] = useState(false);

  // Crash State
  const [crashState, setCrashState] = useState({
    active: false,
    countdown_seconds: 0,
    status: 'normal',
    dispatch_result: null,
    hospital_tow_info: null,
  });

  // Owner & Fleet data
  const [batteryHealth, setBatteryHealth] = useState(null);
  const [recallsData, setRecallsData] = useState(null);
  const [chargingPlan, setChargingPlan] = useState(null);
  const [ownerRepairApproved, setOwnerRepairApproved] = useState(false);
  const [ownerPhoneLocked, setOwnerPhoneLocked] = useState(false);
  const [privacyDeletedMessage, setPrivacyDeletedMessage] = useState(null);

  const eventSourceRef = useRef(null);
  const stationsEventSourceRef = useRef(null);
  const emergencyEventSourceRef = useRef(null);

  // 1. Connect to live telemetry stream
  useEffect(() => {
    const sse = new EventSource('/telemetry/stream');
    sse.onmessage = (e) => {
      try {
        setTelemetry(JSON.parse(e.data));
      } catch (err) {}
    };
    eventSourceRef.current = sse;
    return () => sse.close();
  }, []);

  // 2. Poll /alerts/current
  const fetchCurrentAlert = async () => {
    try {
      const res = await fetch('/alerts/current');
      if (res.ok) {
        setAlertData(await res.json());
      }
    } catch (err) {}
  };

  useEffect(() => {
    fetchCurrentAlert();
    const interval = setInterval(fetchCurrentAlert, 2000);
    return () => clearInterval(interval);
  }, []);

  // 3. Connect to /emergency/stream for live crash countdown
  useEffect(() => {
    const sse = new EventSource('/emergency/stream');
    sse.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        setCrashState(data);
      } catch (err) {}
    };
    emergencyEventSourceRef.current = sse;
    return () => sse.close();
  }, []);

  // 4. Fetch Owner & Recall data
  useEffect(() => {
    fetch('/ev/health')
      .then(r => r.json())
      .then(setBatteryHealth)
      .catch(() => {});

    fetch('/recalls')
      .then(r => r.json())
      .then(setRecallsData)
      .catch(() => {});
  }, []);

  // Consent
  const handleConsent = async (granted) => {
    try {
      const res = await fetch('/consent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, granted }),
      });
      const data = await res.json();
      setConsentStatus(data.status);
      if (granted) triggerNearbyStations();
      else {
        setStations([]);
        setStationAgentResults({});
      }
    } catch (err) {}
  };

  const triggerNearbyStations = async () => {
    try {
      const res = await fetch('/stations/nearby', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      });
      if (res.ok) {
        const data = await res.json();
        setStations(data.stations || []);
        startStationsStream();
      }
    } catch (err) {}
  };

  const startStationsStream = () => {
    if (stationsEventSourceRef.current) stationsEventSourceRef.current.close();
    const sse = new EventSource(`/stations/stream?session_id=${sessionId}`);
    stationsEventSourceRef.current = sse;

    sse.addEventListener('stations_discovered', (e) => {
      try {
        setStations(JSON.parse(e.data).stations || []);
      } catch (err) {}
    });

    sse.addEventListener('station_agent_progress', (e) => {
      try {
        const p = JSON.parse(e.data);
        setAgentProgress(prev => ({ ...prev, [p.station_id]: p.purpose }));
      } catch (err) {}
    });

    sse.addEventListener('station_agent_streaming_url', (e) => {
      try {
        const p = JSON.parse(e.data);
        if (p.streaming_url) {
          setStationAgentResults(prev => ({
            ...prev,
            [p.station_id]: { ...(prev[p.station_id] || {}), streaming_url: p.streaming_url },
          }));
        }
      } catch (err) {}
    });

    sse.addEventListener('station_agent_completed', (e) => {
      try {
        const p = JSON.parse(e.data);
        if (p.result) {
          setStationAgentResults(prev => ({ ...prev, [p.station_id]: p.result }));
          setAgentProgress(prev => {
            const next = { ...prev };
            delete next[p.station_id];
            return next;
          });
        }
      } catch (err) {}
    });

    sse.addEventListener('done', () => sse.close());
  };

  // Workshop Ticket Booking
  const handleBookTicket = async (station) => {
    const res = stationAgentResults[station.id] || {};
    const slot = (res.slots && res.slots[0]) || "Today 3:30 PM";
    try {
      const ticketRes = await fetch('/tickets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          station_id: station.id,
          station_name: station.name,
          station_address: station.address,
          station_phone: station.phone,
          selected_slot: slot,
          price_range: res.price_range || "₹850 - ₹1,400",
          fault_headline: alertData.explanation?.headline || "Battery thermal loop reduced circulation",
          fault_body: alertData.explanation?.body || "Overheating in dense Bengaluru traffic.",
          telemetry_snapshot: telemetry,
          source: res.source || "replayed",
        }),
      });
      if (ticketRes.ok) {
        const data = await ticketRes.json();
        setBookedTicket(data);
      }
    } catch (err) {}
  };

  // Fault Injections
  const handleInjectFault = async (faultName) => {
    setIsInjecting(true);
    try {
      await fetch('/faults/inject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fault: faultName }),
      });
      setTimeout(fetchCurrentAlert, 600);
    } finally {
      setIsInjecting(false);
    }
  };

  const handleClearFault = async () => {
    setIsInjecting(true);
    try {
      await fetch('/faults/inject', { method: 'DELETE' });
      setConsentStatus('pending');
      setStations([]);
      setStationAgentResults({});
      setBookedTicket(null);
      setTimeout(fetchCurrentAlert, 600);
    } finally {
      setIsInjecting(false);
    }
  };

  // Crash Simulation
  const handleSimulateCrash = async () => {
    await fetch('/crash/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ impact_g: 5.4 }),
    });
  };

  const handleCancelCrash = async () => {
    await fetch('/emergency/cancel', { method: 'POST' });
  };

  const handleDispatchCrashNow = async () => {
    await fetch('/emergency/dispatch', { method: 'POST' });
  };

  // Charging Plan
  const handleRequestChargingPlan = async () => {
    const res = await fetch('/ev/charging/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, current_soc_pct: telemetry.soc_pct }),
    });
    if (res.ok) {
      setChargingPlan(await res.json());
    }
  };

  // Privacy: Delete My Data
  const handleDeleteMyData = async () => {
    const res = await fetch(`/me/data?session_id=${sessionId}`, { method: 'DELETE' });
    if (res.ok) {
      const data = await res.json();
      setConsentStatus('pending');
      setStations([]);
      setBookedTicket(null);
      setPrivacyDeletedMessage(data.message);
      setTimeout(() => setPrivacyDeletedMessage(null), 4000);
    }
  };

  const explanation = alertData.explanation || {};
  const isCritical = explanation.severity === 'CRITICAL';
  const isWarning = explanation.severity === 'WARNING';
  const hasActiveAlert = !explanation.all_clear;

  return (
    <div className="verd-app">
      {/* 1. Header */}
      <header className="top-nav">
        <div className="brand-badge">
          <span className="brand-title">VERD</span>
          <span className="sim-pill">SIMULATED</span>
        </div>
        <button 
          className={`btn-112 ${isCritical || explanation.show_112 ? 'pulse' : ''}`}
          onClick={() => setEmergencyAlertModal(true)}
        >
          <span>🚨</span> 112 SOS
        </button>
      </header>

      {/* 2. Role Switcher Tabs */}
      <nav className="role-tabs" aria-label="Role Switcher">
        <button 
          className={`role-tab-btn ${role === 'driver' ? 'active' : ''}`}
          onClick={() => setRole('driver')}
        >
          Driver
        </button>
        <button 
          className={`role-tab-btn ${role === 'owner' ? 'active' : ''}`}
          onClick={() => setRole('owner')}
        >
          Owner
        </button>
        <button 
          className={`role-tab-btn ${role === 'fleet' ? 'active' : ''}`}
          onClick={() => setRole('fleet')}
        >
          Fleet Manager
        </button>
        <button 
          className={`role-tab-btn ${role === 'privacy' ? 'active' : ''}`}
          onClick={() => setRole('privacy')}
        >
          Privacy
        </button>
      </nav>

      {/* 3. Live HUD Strip */}
      <section className="glass-panel hud-strip">
        <div className="hud-item">
          <span className="hud-label">Speed</span>
          <span className="hud-value">{Math.round(telemetry.speed_kmh)} <small style={{fontSize: '0.65rem'}}>km/h</small></span>
        </div>
        <div className="hud-item">
          <span className="hud-label">SOC</span>
          <span className="hud-value ok">{Math.round(telemetry.soc_pct)}%</span>
        </div>
        <div className="hud-item">
          <span className="hud-label">Battery</span>
          <span className={`hud-value ${telemetry.battery_temp_c > 55 ? 'danger' : telemetry.battery_temp_c > 45 ? 'warn' : 'ok'}`}>
            {telemetry.battery_temp_c.toFixed(1)}°C
          </span>
        </div>
        <div className="hud-item">
          <span className="hud-label">Coolant</span>
          <span className={`hud-value ${telemetry.coolant_temp_c > 48 ? 'warn' : 'ok'}`}>
            {telemetry.coolant_temp_c.toFixed(1)}°C
          </span>
        </div>
      </section>

      {/* ==================== ROLE 1: DRIVER VIEW ==================== */}
      {role === 'driver' && (
        <>
          {/* Alert Explainer Card */}
          <section className={`glass-panel alert-card ${isCritical ? 'critical' : isWarning ? 'warning' : 'nominal'}`}>
            <div className="alert-header">
              <span className={`severity-pill ${isCritical ? 'critical' : isWarning ? 'warning' : 'info'}`}>
                {explanation.severity || 'INFO'}
              </span>
              <span className="alert-time">Live Vehicle AI Reasoning</span>
            </div>

            <h2 className="alert-headline">
              {explanation.headline || "Checking vehicle systems..."}
            </h2>

            <p className="alert-body">
              {explanation.body || "Monitoring onboard sensors and CAN bus baselines."}
            </p>

            <div className="alert-advisory">
              <span>ℹ️</span> VERD advises only and never controls the car. Always call 112 in emergencies.
            </div>

            {explanation.evidence && explanation.evidence.length > 0 && (
              <div>
                <button 
                  className="evidence-toggle"
                  onClick={() => setShowEvidence(!showEvidence)}
                >
                  <span>{showEvidence ? '▾' : '▸'}</span>
                  <span>{showEvidence ? 'Hide Sensor Evidence' : 'View Sensor Evidence & Telemetry'}</span>
                </button>

                {showEvidence && (
                  <div className="evidence-box">
                    {explanation.evidence.map((ev, idx) => (
                      <div key={idx} className="evidence-row">
                        <span>{ev.sensor}</span>
                        <strong>{ev.reading} {ev.z_score ? `(z=${ev.z_score.toFixed(1)})` : ''}</strong>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Consent Gate */}
          {hasActiveAlert && (
            <section className="glass-panel consent-card">
              <div className="consent-title">Driver Consent Gate</div>
              <p className="consent-desc">
                {consentStatus === 'granted' 
                  ? "Consent granted. TinyFish web agents have checked repair bays and prices."
                  : consentStatus === 'denied'
                  ? "Outbound lookup denied. No diagnostic data has left this car."
                  : "Allow VERD to research nearby repair stations and slots? Only vehicle diagnostics and city location leave the device — zero personal identity data."}
              </p>

              {consentStatus === 'pending' && (
                <div className="consent-actions">
                  <button className="btn-approve" onClick={() => handleConsent(true)}>
                    Approve Assistance
                  </button>
                  <button className="btn-deny" onClick={() => handleConsent(false)}>
                    Dismiss
                  </button>
                </div>
              )}

              {consentStatus === 'granted' && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.8rem', color: 'var(--emerald-success)', fontWeight: 600 }}>
                    ✓ Outbound Search Approved
                  </span>
                  <button className="btn-deny" style={{ padding: '4px 10px', fontSize: '0.75rem' }} onClick={() => handleConsent(false)}>
                    Revoke
                  </button>
                </div>
              )}
            </section>
          )}

          {/* Booked Ticket Banner */}
          {bookedTicket && (
            <section className="glass-panel" style={{ padding: '16px', marginBottom: '16px', borderColor: 'var(--emerald-success)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ color: 'var(--emerald-success)', fontWeight: 700, fontFamily: 'var(--font-display)' }}>
                  ✓ Workshop Ticket Dispatched
                </span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>{bookedTicket.ticket_id}</span>
              </div>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '12px' }}>
                Confirmed at <b>{bookedTicket.station_name}</b> for slot <b>{bookedTicket.selected_slot}</b>.
              </p>
              <a 
                href={`/tickets/${bookedTicket.ticket_id}/pdf`}
                target="_blank"
                rel="noreferrer"
                className="btn-approve"
                style={{ display: 'inline-block', textDecoration: 'none', textAlign: 'center', width: '100%' }}
              >
                📄 View Workshop Storyboard PDF
              </a>
            </section>
          )}

          {/* Nearby Stations */}
          <section>
            <div className="section-header">
              <h3 className="section-title">Nearby Service Stations</h3>
              {consentStatus === 'granted' && (
                <span className="status-badge live">Parallel Agent Search</span>
              )}
            </div>

            {consentStatus !== 'granted' ? (
              <div className="glass-panel" style={{ padding: '24px 16px', textAlign: 'center' }}>
                <p style={{ color: 'var(--text-dim)', fontSize: '0.86rem' }}>
                  {consentStatus === 'denied' 
                    ? "Outbound lookup disabled. Tap 'Approve Assistance' above to search."
                    : "Awaiting driver approval to locate specialized EV service stations."}
                </p>
              </div>
            ) : stations.length === 0 ? (
              <div className="glass-panel" style={{ padding: '24px 16px', textAlign: 'center' }}>
                <p style={{ color: 'var(--cyan-primary)', fontSize: '0.88rem' }}>Searching Bengaluru EV diagnostic stations...</p>
              </div>
            ) : (
              <div className="stations-list">
                {stations.map(stn => {
                  const result = stationAgentResults[stn.id];
                  const progress = agentProgress[stn.id];
                  return (
                    <div key={stn.id} className="glass-panel station-card">
                      <div className="station-top">
                        <div>
                          <h4 className="station-name">{stn.name}</h4>
                          <p className="station-address">{stn.address}</p>
                        </div>
                        <span className="station-distance">{stn.distance_km} km</span>
                      </div>

                      <div className="station-agent-box">
                        <div className="agent-status-line">
                          <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>TinyFish Web Agent:</span>
                          {progress ? (
                            <span className="agent-pill running">Searching...</span>
                          ) : result ? (
                            <span className={`status-badge ${result.source === 'live' ? 'live' : 'replayed'}`}>
                              {result.source === 'live' ? 'LIVE AGENT' : 'CACHED REPLAY'}
                            </span>
                          ) : (
                            <span className="agent-pill">Pending</span>
                          )}
                        </div>

                        {progress && (
                          <p style={{ fontSize: '0.76rem', color: 'var(--cyan-primary)', marginBottom: '8px' }}>
                            {progress}
                          </p>
                        )}

                        {result && (
                          <>
                            <div className="agent-slots">
                              {(result.slots || []).map((slot, sIdx) => (
                                <span key={sIdx} className="slot-tag">{slot}</span>
                              ))}
                            </div>

                            <div className="station-price-row">
                              <div>
                                <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)', display: 'block' }}>ESTIMATE</span>
                                <span className="station-price">{result.price_range}</span>
                              </div>

                              <div style={{ display: 'flex', gap: '6px' }}>
                                {result.streaming_url && (
                                  <button 
                                    className="btn-watch-agent"
                                    onClick={() => setActiveStreamingUrl(result.streaming_url)}
                                  >
                                    Watch
                                  </button>
                                )}
                                <button 
                                  className="btn-approve"
                                  style={{ padding: '4px 10px', fontSize: '0.72rem' }}
                                  onClick={() => handleBookTicket(stn)}
                                >
                                  Book Bay
                                </button>
                              </div>
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}

      {/* ==================== ROLE 2: OWNER VIEW ==================== */}
      {role === 'owner' && (
        <section className="glass-panel" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.15rem' }}>Vehicle Owner Dashboard</h3>
            <button 
              className={`btn-deny ${ownerPhoneLocked ? 'active' : ''}`}
              style={{ fontSize: '0.75rem', padding: '4px 10px' }}
              onClick={() => setOwnerPhoneLocked(!ownerPhoneLocked)}
            >
              {ownerPhoneLocked ? '🔒 Remote Lock: Active' : '🔓 Remote Lock: Off'}
            </button>
          </div>

          <div style={{ background: 'rgba(0,0,0,0.3)', padding: '12px', borderRadius: '8px', marginBottom: '14px' }}>
            <h4 style={{ fontSize: '0.85rem', color: 'var(--cyan-primary)', marginBottom: '6px' }}>
              High Voltage Battery State of Health
            </h4>
            {batteryHealth && (
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                <p>Health: <strong style={{ color: 'var(--emerald-success)' }}>{batteryHealth.state_of_health_pct}%</strong> (Verified Supported Data)</p>
                <p>Capacity: {batteryHealth.battery_capacity_kwh} kWh | Cycles: {batteryHealth.cycle_count}</p>
                <p>Cooling System: {batteryHealth.cooling_health}</p>
              </div>
            )}
          </div>

          <div style={{ background: 'rgba(0,0,0,0.3)', padding: '12px', borderRadius: '8px', marginBottom: '14px' }}>
            <h4 style={{ fontSize: '0.85rem', color: 'var(--amber-warning)', marginBottom: '6px' }}>
              Warranty & Active Recalls
            </h4>
            {recallsData && (
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                <p>Warranty: <strong>{recallsData.warranty.warranty_period_years} yr / {recallsData.warranty.kilometers_limit.toLocaleString()} km</strong></p>
                <p>{recallsData.warranty.plain_terms}</p>
                <div style={{ marginTop: '8px', padding: '6px', background: 'rgba(245, 158, 11, 0.1)', borderRadius: '6px' }}>
                  <strong>{recallsData.recalls[0]?.component}:</strong> {recallsData.recalls[0]?.description}
                </div>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block' }}>Owner Repair Approval</span>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Authorize workshop to flush coolant loop</span>
            </div>
            <button 
              className={ownerRepairApproved ? 'btn-approve' : 'btn-deny'}
              onClick={() => setOwnerRepairApproved(!ownerRepairApproved)}
              style={{ fontSize: '0.8rem', padding: '6px 14px' }}
            >
              {ownerRepairApproved ? '✓ Approved' : 'Approve Repair'}
            </button>
          </div>
        </section>
      )}

      {/* ==================== ROLE 3: FLEET MANAGER ==================== */}
      {role === 'fleet' && (
        <section className="glass-panel" style={{ padding: '16px' }}>
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.15rem', marginBottom: '8px' }}>
            Fleet Telematics & Rental Control
          </h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginBottom: '14px' }}>
            Downtown Bengaluru EV Fleet Operations (3 active vehicles)
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '16px' }}>
            <div style={{ background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.3)', padding: '10px', borderRadius: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <strong>KA-01-EV-1001 (This Vehicle)</strong>
                <span className="severity-pill critical">CRITICAL FAULT</span>
              </div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Location: Indiranagar 100ft Rd | Booking: Renter Active</p>
              <p style={{ fontSize: '0.75rem', color: 'var(--amber-warning)', marginTop: '4px' }}>
                ⚠️ Estimated revenue loss: ~₹1,500/day during downtime (Estimate)
              </p>
            </div>

            <div style={{ background: 'rgba(0,0,0,0.3)', padding: '10px', borderRadius: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <strong>KA-03-EV-2042</strong>
                <span className="severity-pill info">NOMINAL</span>
              </div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Location: Whitefield Main Rd | SOC: 88%</p>
            </div>

            <div style={{ background: 'rgba(0,0,0,0.3)', padding: '10px', borderRadius: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <strong>KA-05-EV-3099</strong>
                <span className="severity-pill warning">SCHEDULED</span>
              </div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Location: Koramangala Hub | BMS Inspection Booked</p>
            </div>
          </div>
        </section>
      )}

      {/* ==================== ROLE 4: PRIVACY AUDIT ==================== */}
      {role === 'privacy' && (
        <section className="glass-panel" style={{ padding: '16px' }}>
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.15rem', marginBottom: '8px' }}>
            Privacy by Design Audit (GDPR Compliance)
          </h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '14px', lineHeight: 1.4 }}>
            VERD is built on strict data minimization. Outbound web lookups only occur after explicit driver consent.
          </p>

          <table style={{ width: '100%', fontSize: '0.75rem', textAlign: 'left', marginBottom: '16px', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-dim)' }}>
                <th style={{ paddingBottom: '6px' }}>Data Category</th>
                <th style={{ paddingBottom: '6px' }}>Shared?</th>
                <th style={{ paddingBottom: '6px' }}>Purpose</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '6px 0' }}>Battery / CAN Telemetry</td>
                <td style={{ color: 'var(--emerald-success)' }}>YES (Consented)</td>
                <td>Diagnosis</td>
              </tr>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '6px 0' }}>Driver Name & Identity</td>
                <td style={{ color: 'var(--crimson-danger)' }}>NEVER</td>
                <td>Privacy</td>
              </tr>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '6px 0' }}>Credit Card / Payments</td>
                <td style={{ color: 'var(--crimson-danger)' }}>NEVER</td>
                <td>Safety</td>
              </tr>
            </tbody>
          </table>

          {privacyDeletedMessage && (
            <div style={{ background: 'rgba(16, 185, 129, 0.2)', color: 'var(--emerald-success)', padding: '8px', borderRadius: '6px', fontSize: '0.78rem', marginBottom: '10px' }}>
              ✓ {privacyDeletedMessage}
            </div>
          )}

          <button 
            className="btn-deny"
            style={{ width: '100%', borderColor: 'var(--crimson-danger)', color: 'var(--crimson-danger)' }}
            onClick={handleDeleteMyData}
          >
            🗑️ Delete All My Session Data
          </button>
        </section>
      )}

      {/* Floating Pitch Bar */}
      <footer className="pitch-bar">
        <div className="pitch-bar-content">
          <button 
            className="btn-pitch inject"
            disabled={isInjecting}
            onClick={() => handleInjectFault('battery_overheat')}
          >
            🔥 Overheat
          </button>
          <button 
            className="btn-pitch"
            style={{ background: 'linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)', color: '#fff' }}
            onClick={handleSimulateCrash}
          >
            💥 Crash (20s)
          </button>
          <button 
            className="btn-pitch clear"
            disabled={isInjecting}
            onClick={handleClearFault}
          >
            ↺ Reset
          </button>
        </div>
      </footer>

      {/* Crash Emergency Modal (20-Second Countdown & Non-Blocking Lookups) */}
      {(crashState.active || crashState.status === 'countdown' || crashState.status === 'dispatched') && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ borderColor: 'var(--crimson-danger)', maxWidth: '460px' }}>
            <div style={{ textAlign: 'center', marginBottom: '12px' }}>
              <div style={{ fontSize: '2.5rem', animation: 'pulse-op 1s infinite' }}>🚨</div>
              <h2 style={{ fontFamily: 'var(--font-display)', color: 'var(--crimson-danger)', fontSize: '1.4rem' }}>
                {crashState.status === 'dispatched' ? "Emergency Dispatched" : "CRASH DETECTED – ARE YOU OK?"}
              </h2>
            </div>

            {crashState.status === 'countdown' && (
              <>
                <p style={{ textAlign: 'center', fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: '12px' }}>
                  High impact detected ({crashState.impact_g}G). Requesting ambulance in:
                </p>
                <div style={{ fontSize: '2.5rem', fontWeight: 800, textAlign: 'center', color: '#fff', fontFamily: 'var(--font-display)', marginBottom: '16px' }}>
                  {crashState.countdown_seconds}s
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                  <button 
                    className="btn-approve"
                    style={{ background: 'var(--emerald-success)' }}
                    onClick={handleCancelCrash}
                  >
                    I'm OK (Cancel)
                  </button>
                  <button 
                    className="btn-112"
                    style={{ justifyContent: 'center' }}
                    onClick={handleDispatchCrashNow}
                  >
                    Dispatch Now
                  </button>
                </div>
              </>
            )}

            {crashState.status === 'dispatched' && (
              <div>
                <div style={{ background: 'rgba(239, 68, 68, 0.15)', padding: '10px', borderRadius: '8px', marginBottom: '12px', fontSize: '0.8rem' }}>
                  <p><strong>Status:</strong> {crashState.dispatch_result?.ambulance_status}</p>
                  <p><strong>Channel:</strong> {crashState.dispatch_result?.channel}</p>
                  <p style={{ marginTop: '4px', fontSize: '0.72rem', color: 'var(--amber-warning)' }}>
                    {crashState.dispatch_result?.advisory}
                  </p>
                </div>

                {crashState.hospital_tow_info && (
                  <div style={{ background: 'rgba(0,0,0,0.3)', padding: '10px', borderRadius: '8px', fontSize: '0.75rem' }}>
                    <p style={{ fontWeight: 700, color: 'var(--cyan-primary)', marginBottom: '4px' }}>
                      Parallel Agent Lookup (Non-Blocking):
                    </p>
                    <p>🏥 {crashState.hospital_tow_info.hospitals[0]?.name} ({crashState.hospital_tow_info.hospitals[0]?.distance_km} km)</p>
                    <p>🚜 {crashState.hospital_tow_info.tow_services[0]?.name} (ETA {crashState.hospital_tow_info.tow_services[0]?.eta_mins} mins)</p>
                  </div>
                )}

                <button 
                  className="btn-deny"
                  style={{ width: '100%', marginTop: '12px' }}
                  onClick={handleCancelCrash}
                >
                  Close Emergency Overlay
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 112 Confirmation Modal */}
      {emergencyAlertModal && (
        <div className="modal-overlay" onClick={() => setEmergencyAlertModal(false)}>
          <div className="glass-panel modal-content" style={{ borderColor: 'var(--crimson-danger)' }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h4 style={{ color: 'var(--crimson-danger)', fontFamily: 'var(--font-display)' }}>
                🚨 National Emergency Call (112)
              </h4>
              <button className="btn-close" onClick={() => setEmergencyAlertModal(false)}>✕</button>
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '14px', lineHeight: 1.4 }}>
              VERD advises on vehicle health only and never replaces calling 112 directly. In an emergency or severe accident, contact national emergency services immediately.
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
              <a 
                href="tel:112"
                className="btn-112"
                style={{ textDecoration: 'none', justifyContent: 'center' }}
                onClick={() => setEmergencyAlertModal(false)}
              >
                Call 112
              </a>
              <button className="btn-deny" onClick={() => setEmergencyAlertModal(false)}>
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Live Agent Streaming Modal */}
      {activeStreamingUrl && (
        <div className="modal-overlay" onClick={() => setActiveStreamingUrl(null)}>
          <div className="glass-panel modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h4 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem' }}>TinyFish Web Agent Browser</h4>
              <button className="btn-close" onClick={() => setActiveStreamingUrl(null)}>✕</button>
            </div>
            <div style={{
              background: '#050811',
              borderRadius: '8px',
              padding: '16px',
              textAlign: 'center'
            }}>
              <div style={{ fontSize: '2rem', marginBottom: '8px' }}>🌐</div>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-main)', marginBottom: '6px' }}>
                TinyFish Autonomous Agent Stream
              </p>
              <p style={{ fontSize: '0.72rem', color: 'var(--text-dim)', wordBreak: 'break-all', marginBottom: '12px' }}>
                {activeStreamingUrl}
              </p>
              <a 
                href={activeStreamingUrl}
                target="_blank"
                rel="noreferrer"
                className="btn-approve"
                style={{ textDecoration: 'none', display: 'inline-block', fontSize: '0.78rem', padding: '6px 12px' }}
              >
                Open Full Browser ↗
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
