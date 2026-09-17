/**
 * Focused Discrete Operational Event Timeline View (Phase 8).
 *
 * Displays reconstructed charging sessions, contiguous alarm spans, hardware
 * protection faults, state transitions, and configuration change diffs with
 * zero data imputation, honest gap tracking, and recomputation triggers.
 */

import { useState } from 'react';
import { api } from '../lib/api';
import { timestamp, duration } from '../lib/format';
import type {
  EventReconstructionOutcome,
  EventType,
} from '../lib/types';
import { useAsync } from '../lib/useAsync';

interface EventTimelineTabProps {
  chargerId: string;
}

export function EventTimelineTab({ chargerId }: EventTimelineTabProps) {
  const [selectedType, setSelectedType] = useState<string>('ALL');
  const [limit, setLimit] = useState<number>(100);
  const [reconstructing, setReconstructing] = useState<boolean>(false);
  const [outcome, setOutcome] = useState<EventReconstructionOutcome | null>(null);
  const [reconstructError, setReconstructError] = useState<string | null>(null);

  // Query unified event timeline
  const timelineAsync = useAsync(
    () => api.eventTimeline(chargerId, { limit }),
    [chargerId, limit, outcome],
  );

  const timelineData = timelineAsync.data?.data?.events ?? [];

  // Query charging sessions for summary metrics
  const sessionsAsync = useAsync(
    () => api.sessions(chargerId, { limit: 100 }),
    [chargerId, outcome],
  );
  const sessions = sessionsAsync.data?.data?.sessions ?? [];

  // Query alarms for summary metrics
  const alarmsAsync = useAsync(
    () => api.alarms(chargerId, { limit: 100 }),
    [chargerId, outcome],
  );
  const alarms = alarmsAsync.data?.data?.alarms ?? [];

  const handleReconstruct = async () => {
    setReconstructing(true);
    setReconstructError(null);
    try {
      const resp = await api.reconstructEvents(chargerId);
      if (resp.data) {
        setOutcome(resp.data);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setReconstructError(msg);
    } finally {
      setReconstructing(false);
    }
  };

  // Metrics calculations
  const totalEnergy = sessions.reduce(
    (acc, s) => acc + (s.energy_delivered_kwh ?? 0),
    0,
  );
  const openAlarmsCount = alarms.filter((a) => a.is_open).length;

  // Filter events by selected type
  const filteredEvents = timelineData.filter((evt) => {
    if (selectedType === 'ALL') return true;
    return evt.event_type === selectedType;
  });

  const getCardTypeClass = (type: EventType) => {
    switch (type) {
      case 'CHARGING_SESSION':
        return 'type-session';
      case 'ALARM_EVENT':
        return 'type-alarm';
      case 'FAULT_EVENT':
        return 'type-fault';
      case 'CONFIGURATION_CHANGE':
        return 'type-config';
      case 'STATE_TRANSITION':
        return 'type-state';
      default:
        return '';
    }
  };

  const getTypeBadgeClass = (type: EventType) => {
    switch (type) {
      case 'CHARGING_SESSION':
        return 'session';
      case 'ALARM_EVENT':
        return 'alarm';
      case 'FAULT_EVENT':
        return 'fault';
      case 'CONFIGURATION_CHANGE':
        return 'config';
      case 'STATE_TRANSITION':
        return 'state';
      default:
        return '';
    }
  };

  const getTypeIcon = (type: EventType) => {
    switch (type) {
      case 'CHARGING_SESSION':
        return '⚡ Session';
      case 'ALARM_EVENT':
        return '⚠️ Alarm';
      case 'FAULT_EVENT':
        return '🛑 Fault';
      case 'CONFIGURATION_CHANGE':
        return '⚙️ Config';
      case 'STATE_TRANSITION':
        return '🔄 Transition';
      default:
        return type;
    }
  };

  return (
    <div className="tab-content event-timeline-container">
      {/* Header and Controls */}
      <section className="panel">
        <header>
          <div>
            <h2>Operational Event Reconstruction</h2>
            <span className="hint">
              Continuous Silver history transformed into discrete operational spans (sessions, alarms, faults, config diffs).
            </span>
          </div>
          <div className="controls">
            <button
              onClick={handleReconstruct}
              disabled={reconstructing}
              className="action-btn"
              title="Execute deterministic event reconstruction pipeline"
            >
              {reconstructing ? 'Reconstructing…' : '⚡ Reconstruct Events'}
            </button>
          </div>
        </header>

        {reconstructError ? (
          <div className="error" style={{ margin: '0 14px 14px' }}>
            Reconstruction failed: {reconstructError}
          </div>
        ) : null}

        {outcome ? (
          <div style={{ margin: '0 14px 14px' }}>
            <span className="reconstruct-status-pill">
              ✓ Reconstructed in {outcome.reconstruction_duration_ms.toFixed(1)} ms:{' '}
              {outcome.sessions_reconstructed} sessions, {outcome.alarms_reconstructed} alarms,{' '}
              {outcome.faults_reconstructed} faults, {outcome.configuration_changes_reconstructed} config changes
            </span>
          </div>
        ) : null}

        {/* High-level Summary Cards */}
        <div className="event-stats-grid">
          <div className="event-stat-card">
            <span className="label">Reconstructed Sessions</span>
            <span className="value">{sessions.length}</span>
            <span className="sub">Total Delivered: {totalEnergy.toFixed(1)} kWh</span>
          </div>
          <div className="event-stat-card">
            <span className="label">Active Alarms</span>
            <span className="value" style={{ color: openAlarmsCount > 0 ? 'var(--warn)' : 'var(--ok)' }}>
              {openAlarmsCount}
            </span>
            <span className="sub">Historical Total: {alarms.length}</span>
          </div>
          <div className="event-stat-card">
            <span className="label">Timeline Events</span>
            <span className="value">{timelineData.length}</span>
            <span className="sub">Latest Bounded Spans</span>
          </div>
          <div className="event-stat-card">
            <span className="label">Reconstruction Engine</span>
            <span className="value" style={{ fontSize: '15px' }}>v1.0 (Phase 8)</span>
            <span className="sub">Zero Telemetry Imputation</span>
          </div>
        </div>

        {/* Filters */}
        <div className="controls" style={{ borderTop: '1px solid var(--border)', paddingTop: '12px' }}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-faint)', fontWeight: 600 }}>FILTER:</span>
            {[
              { id: 'ALL', label: 'All Events' },
              { id: 'CHARGING_SESSION', label: '⚡ Sessions' },
              { id: 'ALARM_EVENT', label: '⚠️ Alarms' },
              { id: 'FAULT_EVENT', label: '🛑 Faults' },
              { id: 'CONFIGURATION_CHANGE', label: '⚙️ Config' },
            ].map((f) => (
              <button
                key={f.id}
                className={selectedType === f.id ? 'active' : ''}
                onClick={() => setSelectedType(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-faint)' }}>Limit:</span>
            {[50, 100, 200].map((lim) => (
              <button
                key={lim}
                className={limit === lim ? 'active' : ''}
                onClick={() => setLimit(lim)}
              >
                {lim}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Chronological Event Stream */}
      <section className="panel">
        <header>
          <h3>Unified Event Stream ({filteredEvents.length})</h3>
          <span className="hint">Strict chronological order (event_time ASC, frame_sequence ASC)</span>
        </header>

        {timelineAsync.loading && !timelineData.length ? (
          <div className="loading">Loading operational events…</div>
        ) : timelineAsync.error ? (
          <div className="error">{timelineAsync.error}</div>
        ) : filteredEvents.length === 0 ? (
          <div className="empty">
            No operational events match the current filter. Click "Reconstruct Events" to process Silver history.
          </div>
        ) : (
          <div className="timeline-stream">
            {filteredEvents.map((evt) => (
              <div
                key={evt.event_id}
                className={`timeline-event-card ${getCardTypeClass(evt.event_type)}`}
              >
                <div className="event-header">
                  <div className="event-title-group">
                    <span className={`event-type-badge ${getTypeBadgeClass(evt.event_type)}`}>
                      {getTypeIcon(evt.event_type)}
                    </span>
                    <span className="event-title">{evt.title}</span>
                  </div>
                  <span className="event-time">
                    {timestamp(evt.event_time)}
                    {evt.end_time ? ` → ${timestamp(evt.end_time)}` : evt.is_open ? ' (Active / Open)' : ''}
                  </span>
                </div>

                <div className="event-body">{evt.description}</div>

                <div className="event-tags">
                  <span className="tag-badge">Component: {evt.component}</span>
                  {evt.duration_seconds !== null ? (
                    <span className="tag-badge">Duration: {duration(evt.duration_seconds)}</span>
                  ) : null}
                  {evt.severity ? (
                    <span
                      className="tag-badge"
                      style={{
                        color:
                          evt.severity === 'CRITICAL'
                            ? 'var(--bad)'
                            : evt.severity === 'MAJOR'
                            ? 'var(--warn)'
                            : 'var(--text-dim)',
                      }}
                    >
                      Severity: {evt.severity}
                    </span>
                  ) : null}
                  {evt.is_open ? (
                    <span className="tag-badge open-pulse">ACTIVE OPEN SPAN</span>
                  ) : null}
                  {evt.has_gap ? (
                    <span className="tag-badge gap-warning" title="Event duration crosses a known telemetry outage">
                      ⚠️ Crosses Telemetry Gap
                    </span>
                  ) : null}
                  <span
                    className={`tag-badge ${
                      evt.confidence === 'HIGH'
                        ? 'conf-high'
                        : evt.confidence === 'MEDIUM'
                        ? 'conf-med'
                        : 'conf-low'
                    }`}
                  >
                    Confidence: {evt.confidence}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
