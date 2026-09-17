/**
 * Focused Historical Continuity & Time-Series Timeline View (Phase 7).
 *
 * Displays empirical multi-day continuity, sampling interval distribution,
 * detected gaps without imputation, honest 1-point snapshot alerts, and
 * interactive component/signal telemetry timelines.
 */

import { useState } from 'react';
import { api } from '../lib/api';
import { timestamp, duration } from '../lib/format';
import { useAsync } from '../lib/useAsync';

interface HistoryTabProps {
  chargerId: string;
}

const CABINET_SIGNALS = [
  { id: 'cabinet_temperature', name: 'Cabinet Temperature (°C)' },
  { id: 'l1_n_voltage', name: 'L1-N Voltage (V)' },
  { id: 'line_1_input_current', name: 'Line 1 Current (A)' },
  { id: 'frequency', name: 'Grid Frequency (Hz)' },
  { id: 'power_factor', name: 'Power Factor' },
];

const CONNECTOR_SIGNALS = [
  { id: 'gun_temp_dc_positive', name: 'Gun Temp DC+ (°C)' },
  { id: 'gun_temp_dc_negative', name: 'Gun Temp DC- (°C)' },
  { id: 'gun_voltage', name: 'Gun Voltage (V)' },
  { id: 'connector_status', name: 'Connector Status' },
];

const SMR_SIGNALS = [
  { id: 'smr_dc_dc_temperature', name: 'SMR DC-DC Temp (°C)' },
  { id: 'smr_pfc_temperature', name: 'SMR PFC Temp (°C)' },
  { id: 'output_voltage', name: 'Output Voltage (V)' },
  { id: 'output_current', name: 'Output Current (A)' },
];

const RECTIFIER_SIGNALS = [
  { id: 'rectifier_internal_temp', name: 'Rectifier Internal Temp (°C)' },
  { id: 'rect_max_temperature', name: 'Rectifier Max Temp (°C)' },
];

export function HistoryTab({ chargerId }: HistoryTabProps) {
  const summaryAsync = useAsync(() => api.chargerContinuitySummary(chargerId), [chargerId]);
  const summary = summaryAsync.data?.data ?? null;

  // Interactive component and signal selector state
  const [componentType, setComponentType] = useState<'cabinet' | 'connector' | 'smr' | 'rectifier'>('cabinet');
  const [componentId, setComponentId] = useState<number>(1);
  const [selectedSignal, setSelectedSignal] = useState<string>('cabinet_temperature');

  // Query raw observations for chosen signal
  const signalAsync = useAsync(() => {
    if (!chargerId) return Promise.resolve({ data: null, meta: {}, error: null });
    const cType = componentType === 'cabinet' ? undefined : componentType;
    const cId = componentType === 'cabinet' ? undefined : componentId;
    return api.signalHistory(chargerId, selectedSignal, {
      component_type: cType,
      component_id: cId,
      limit: 500,
    });
  }, [chargerId, componentType, componentId, selectedSignal]);

  const signalData = signalAsync.data?.data ?? null;

  const handleComponentTypeChange = (type: 'cabinet' | 'connector' | 'smr' | 'rectifier') => {
    setComponentType(type);
    if (type === 'cabinet') {
      setSelectedSignal('cabinet_temperature');
    } else if (type === 'connector') {
      setSelectedSignal('gun_temp_dc_positive');
    } else if (type === 'smr') {
      setSelectedSignal('smr_dc_dc_temperature');
    } else if (type === 'rectifier') {
      setSelectedSignal('rectifier_internal_temp');
    }
  };

  const getAvailableSignals = () => {
    switch (componentType) {
      case 'connector':
        return CONNECTOR_SIGNALS;
      case 'smr':
        return SMR_SIGNALS;
      case 'rectifier':
        return RECTIFIER_SIGNALS;
      default:
        return CABINET_SIGNALS;
    }
  };

  return (
    <div className="tab-content">
      {summaryAsync.loading ? <div className="loading">Loading historical timeline...</div> : null}

      {summary ? (
        <>
          {/* Section 39: Snapshot Honesty Banner */}
          {summary.history_depth_status === 'SINGLE_OBSERVATION' ? (
            <div
              className="alert-box"
              style={{
                background: 'rgba(234, 179, 8, 0.1)',
                border: '1px solid rgba(234, 179, 8, 0.3)',
                padding: '1rem',
                borderRadius: '8px',
                marginBottom: '1.5rem',
              }}
            >
              <h4 style={{ margin: 0, color: '#eab308' }}>
                Only 1 Historical Observation Available (Fleet Snapshot)
              </h4>
              <p style={{ margin: '0.5rem 0 0 0', color: '#cbd5e1', fontSize: '0.9rem' }}>
                This charger only contains a single point-in-time snapshot.
                <strong> Temporal pattern analysis is not yet possible</strong> without multi-day historical files.
                Zero artificial trend lines or interpolations are shown.
              </p>
            </div>
          ) : null}

          {/* Headline Summary Tiles */}
          <div className="stats-grid" style={{ marginBottom: '1.5rem' }}>
            <div className="stat-card">
              <span className="label">Observed Span</span>
              <span className="value">
                {summary.observed_days} {summary.observed_days === 1 ? 'day' : 'days'}
              </span>
              <span className="desc">
                {summary.first_seen ? timestamp(summary.first_seen) : 'None'} to{' '}
                {summary.last_seen ? timestamp(summary.last_seen) : 'None'}
              </span>
            </div>

            <div className="stat-card">
              <span className="label">Total Observations</span>
              <span className="value">{summary.observation_count.toLocaleString()}</span>
              <span className="desc">{summary.distinct_timestamps.toLocaleString()} unique timestamps</span>
            </div>

            <div className="stat-card">
              <span className="label">Median Sampling Interval</span>
              <span className="value">
                {summary.sampling_profile.median_interval_seconds != null
                  ? `${summary.sampling_profile.median_interval_seconds}s`
                  : 'N/A'}
              </span>
              <span className="desc">
                {summary.sampling_profile.expected_interval_seconds != null
                  ? `Expected cadence: ~${summary.sampling_profile.expected_interval_seconds}s`
                  : 'Insufficient data to infer cadence'}
              </span>
            </div>

            <div className="stat-card">
              <span className="label">Telemetry Gaps</span>
              <span className="value">{summary.gaps.length}</span>
              <span className="desc">
                {summary.gaps.length > 0 ? 'Unobserved periods detected' : 'No abnormal gaps'}
              </span>
            </div>

            <div className="stat-card">
              <span className="label">Pattern Research Ready</span>
              <span
                className="value"
                style={{
                  color: summary.pattern_eligibility.pattern_research_ready ? '#10b981' : '#f59e0b',
                  fontSize: '1.1rem',
                }}
              >
                {summary.pattern_eligibility.pattern_research_ready ? 'ELIGIBLE' : 'NOT YET ELIGIBLE'}
              </span>
              <span className="desc" style={{ fontSize: '0.75rem' }}>
                {summary.pattern_eligibility.reason}
              </span>
            </div>
          </div>

          {/* Interactive Component & Signal Selector */}
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            <div className="card-header">
              <h3>Signal History Explorer</h3>
              <span className="sub">Inspect exact chronological observations without synthetic grid snapping</span>
            </div>

            <div className="controls" style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', padding: '1rem 0' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#94a3b8', marginBottom: '0.25rem' }}>
                  Component Layer
                </label>
                <select
                  value={componentType}
                  onChange={(e) =>
                    handleComponentTypeChange(
                      e.target.value as 'cabinet' | 'connector' | 'smr' | 'rectifier',
                    )
                  }
                  style={{ background: '#1e293b', color: '#f8fafc', padding: '0.4rem 0.8rem', borderRadius: '4px' }}
                >
                  <option value="cabinet">Cabinet / Grid</option>
                  <option value="connector">Connectors ({summary.connectors_observed.length || 2})</option>
                  <option value="smr">SMR Power Modules ({summary.smrs_observed.length || 4})</option>
                  <option value="rectifier">Rectifiers ({summary.rectifiers_observed.length || 2})</option>
                </select>
              </div>

              {componentType !== 'cabinet' ? (
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: '#94a3b8', marginBottom: '0.25rem' }}>
                    Component ID
                  </label>
                  <select
                    value={componentId}
                    onChange={(e) => setComponentId(Number(e.target.value))}
                    style={{ background: '#1e293b', color: '#f8fafc', padding: '0.4rem 0.8rem', borderRadius: '4px' }}
                  >
                    {(componentType === 'connector'
                      ? summary.connectors_observed.length ? summary.connectors_observed : [1, 2]
                      : componentType === 'smr'
                      ? summary.smrs_observed.length ? summary.smrs_observed : [1, 2, 3, 4, 5, 6]
                      : summary.rectifiers_observed.length ? summary.rectifiers_observed : [1, 2]
                    ).map((id) => (
                      <option key={id} value={id}>
                        {componentType.toUpperCase()} #{id}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#94a3b8', marginBottom: '0.25rem' }}>
                  Canonical Signal
                </label>
                <select
                  value={selectedSignal}
                  onChange={(e) => setSelectedSignal(e.target.value)}
                  style={{ background: '#1e293b', color: '#f8fafc', padding: '0.4rem 0.8rem', borderRadius: '4px' }}
                >
                  {getAvailableSignals().map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Observations Stream */}
            {signalAsync.loading ? (
              <div className="loading" style={{ padding: '2rem', textAlign: 'center' }}>
                Fetching signal observations...
              </div>
            ) : signalData && signalData.observations.length > 0 ? (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Event Time (UTC)</th>
                      <th>Frame Seq</th>
                      <th>Normalized Value</th>
                      <th>Raw CSV Value</th>
                      <th>Sentinel Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signalData.observations.slice(0, 50).map((o, idx) => (
                      <tr key={`${o.event_time}_${o.frame_sequence}_${idx}`}>
                        <td>{timestamp(o.event_time)}</td>
                        <td>{o.frame_sequence}</td>
                        <td style={{ fontWeight: 600 }}>
                          {o.value !== null && o.value !== undefined ? String(o.value) : <span style={{ color: '#64748b' }}>NULL</span>}
                        </td>
                        <td style={{ color: '#94a3b8', fontFamily: 'monospace' }}>{o.raw_value ?? '—'}</td>
                        <td>
                          {o.masked_sentinel ? (
                            <span className="pill" style={{ background: '#7f1d1d', color: '#fca5a5' }}>
                              SENTINEL MASKED
                            </span>
                          ) : (
                            <span className="pill" style={{ background: '#14532d', color: '#86efac' }}>
                              VALID
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {signalData.observations.length > 50 ? (
                  <div style={{ padding: '0.75rem', textAlign: 'center', color: '#94a3b8', fontSize: '0.85rem' }}>
                    Showing first 50 of {signalData.observations.length} observations.
                  </div>
                ) : null}
              </div>
            ) : (
              <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
                No telemetry observations found for this signal and component combination.
              </div>
            )}
          </div>

          {/* Section 37: Data Gaps Discontinuity Explorer */}
          {summary.gaps.length > 0 ? (
            <div className="card">
              <div className="card-header">
                <h3>Observed Data Gaps</h3>
                <span className="sub">
                  Absences relative to normal sampling interval ({summary.sampling_profile.median_interval_seconds}s). No synthetic interpolation applied.
                </span>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Gap Window Start</th>
                      <th>Gap Window End</th>
                      <th>Duration</th>
                      <th>Cadence Multiple</th>
                      <th>Integrity Property</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.gaps.map((g, idx) => (
                      <tr key={idx}>
                        <td>{timestamp(g.gap_start)}</td>
                        <td>{timestamp(g.gap_end)}</td>
                        <td style={{ fontWeight: 600, color: '#f87171' }}>{duration(g.gap_duration_seconds)}</td>
                        <td>{g.gap_multiple ? `${g.gap_multiple}x cadence` : '—'}</td>
                        <td>
                          <span className="pill" style={{ background: '#374151', color: '#d1d5db' }}>
                            UNOBSERVED ABSENCE (NO SYNTHETIC DATA)
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
