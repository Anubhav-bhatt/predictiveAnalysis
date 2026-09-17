/**
 * Fleet Research & Pattern Discovery Lab Page (Phase 9).
 *
 * Provides fleet-wide exploratory data analysis (EDA), data readiness
 * assessment for future ML phases, and per-charger pattern discovery navigation.
 */

import { Link } from 'react-router-dom';
import { research } from '../lib/api';
import { count, percent, timestamp } from '../lib/format';
import { useAsync } from '../lib/useAsync';

export function FleetResearchPage() {
  const readinessAsync = useAsync(() => research.dataReadiness(), []);
  const fleetEdaAsync = useAsync(() => research.fleetEda(), []);

  const readiness = readinessAsync.data?.data ?? null;
  const eda = fleetEdaAsync.data?.data ?? null;

  const reloadAll = () => {
    readinessAsync.reload();
    fleetEdaAsync.reload();
  };

  const getReadinessColor = (status: string) => {
    switch (status?.toUpperCase()) {
      case 'READY':
        return '#10b981';
      case 'ADEQUATE':
        return '#38bdf8';
      case 'MARGINAL':
        return '#f59e0b';
      default:
        return '#ef4444';
    }
  };

  return (
    <div className="app">
      <div className="masthead">
        <div>
          <h1>Fleet Research & Exploratory Data Analysis</h1>
          <div className="sub">
            Phase 9 Scientific Pattern Discovery & Analytical Dataset Construction.{' '}
            <Link to="/data-operations">Back to Data Operations</Link>
          </div>
        </div>
        <div className="controls">
          <button onClick={reloadAll}>Reload</button>
          <Link className="btn-link" to="/data-operations">
            Daily Operations
          </Link>
          <Link className="btn-link" to="/data-operations/uploads">
            Upload History
          </Link>
        </div>
      </div>

      {/* Data Readiness Assessment */}
      <section className="panel" style={{ marginBottom: 24 }}>
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2>Data Readiness for Predictive ML</h2>
            <span className="hint">Scientific gating criteria before training predictive models</span>
          </div>
          {readiness ? (
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 14px',
                borderRadius: 999,
                fontWeight: 700,
                fontSize: 13,
                border: `1px solid ${getReadinessColor(readiness.overall_readiness)}`,
                color: getReadinessColor(readiness.overall_readiness),
                background: 'var(--surface-2)',
              }}
            >
              <span>READINESS:</span>
              <span>{readiness.overall_readiness}</span>
            </div>
          ) : null}
        </header>

        {readinessAsync.loading && !readiness ? (
          <div className="loading" style={{ padding: 24 }}>Assessing dataset readiness…</div>
        ) : readiness ? (
          <div style={{ marginTop: 16 }}>
            {/* Readiness KPI Grid */}
            <div className="event-kpi-grid" style={{ marginBottom: 16 }}>
              <div className="event-kpi-card">
                <div className="kpi-label">Active Chargers</div>
                <div className="kpi-val">{readiness.charger_count}</div>
                <div className="kpi-sub">Continuous Silver telemetry</div>
              </div>
              <div className="event-kpi-card">
                <div className="kpi-label">Continuous Observations</div>
                <div className="kpi-val">{count(readiness.observation_count)}</div>
                <div className="kpi-sub">{readiness.temporal_depth} temporal depth</div>
              </div>
              <div className="event-kpi-card">
                <div className="kpi-label">Temporal Span</div>
                <div className="kpi-val">{readiness.temporal_span_days.toFixed(1)}d</div>
                <div className="kpi-sub">Total historical timeline</div>
              </div>
              <div className="event-kpi-card">
                <div className="kpi-label">Signal Coverage</div>
                <div className="kpi-val">{percent(readiness.signal_coverage_rate)}</div>
                <div className="kpi-sub">Non-null Silver rate</div>
              </div>
              <div className="event-kpi-card">
                <div className="kpi-label">Discovered Patterns</div>
                <div className="kpi-val" style={{ color: '#38bdf8' }}>{readiness.pattern_candidate_count}</div>
                <div className="kpi-sub">Candidate precursors</div>
              </div>
              <div className="event-kpi-card">
                <div className="kpi-label">Telemetry Gap Rate</div>
                <div className="kpi-val" style={{ color: readiness.gap_rate > 0.05 ? '#f59e0b' : '#10b981' }}>
                  {percent(readiness.gap_rate)}
                </div>
                <div className="kpi-sub">Honest gap awareness</div>
              </div>
            </div>

            {/* Blockers & Recommendations */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: 16 }}>
              {readiness.blockers.length > 0 ? (
                <div style={{ background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: 6, padding: 16 }}>
                  <div style={{ fontWeight: 600, color: '#ef4444', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span>⚠ Predictive Model Blockers</span>
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 20, color: 'var(--text)', fontSize: 13 }}>
                    {readiness.blockers.map((b, i) => (
                      <li key={i} style={{ marginBottom: 4 }}>{b}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {readiness.recommendations.length > 0 ? (
                <div style={{ background: 'rgba(56, 189, 248, 0.08)', border: '1px solid rgba(56, 189, 248, 0.25)', borderRadius: 6, padding: 16 }}>
                  <div style={{ fontWeight: 600, color: '#38bdf8', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span>ℹ Scientific Next Steps</span>
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 20, color: 'var(--text)', fontSize: 13 }}>
                    {readiness.recommendations.map((r, i) => (
                      <li key={i} style={{ marginBottom: 4 }}>{r}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </section>

      {/* Fleet EDA Summary */}
      <section className="panel" style={{ marginBottom: 24 }}>
        <header>
          <h2>Fleet-Wide Exploratory Data Analysis (EDA)</h2>
          <span className="hint">Aggregated statistics across all monitored charging assets</span>
        </header>

        {fleetEdaAsync.loading && !eda ? (
          <div className="loading" style={{ padding: 24 }}>Computing fleet EDA metrics…</div>
        ) : eda ? (
          <div style={{ marginTop: 16 }}>
            <div className="event-kpi-grid" style={{ marginBottom: 20 }}>
              <div className="event-kpi-card">
                <div className="kpi-label">Reconstructed Sessions</div>
                <div className="kpi-val">{eda.total_sessions}</div>
                <div className="kpi-sub">Continuous operational sessions</div>
              </div>
              <div className="event-kpi-card">
                <div className="kpi-label">Total Alarms & Faults</div>
                <div className="kpi-val">{eda.total_alarms + eda.total_faults}</div>
                <div className="kpi-sub">{eda.total_alarms} alarms · {eda.total_faults} hardware faults</div>
              </div>
              <div className="event-kpi-card">
                <div className="kpi-label">Monitored Signals</div>
                <div className="kpi-val">{eda.signal_count}</div>
                <div className="kpi-sub">Standardized Silver signals</div>
              </div>
              <div className="event-kpi-card">
                <div className="kpi-label">Fleet Missing Rate</div>
                <div className="kpi-val">{percent(eda.fleet_missing_rate)}</div>
                <div className="kpi-sub">Telemetry integrity score</div>
              </div>
            </div>

            {eda.temporal_span_start ? (
              <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 16, fontFamily: 'var(--mono)' }}>
                Temporal Coverage Span: {timestamp(eda.temporal_span_start)} → {timestamp(eda.temporal_span_end ?? '')}
              </div>
            ) : null}

            {/* Per-Charger Breakdown Table */}
            {eda.charger_summaries.length > 0 ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Charger ID</th>
                      <th>Observations</th>
                      <th>Sessions</th>
                      <th>Alarms</th>
                      <th>Gaps</th>
                      <th>Missing Rate</th>
                      <th>Patterns Found</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {eda.charger_summaries.map((cs) => (
                      <tr key={cs.charger_id}>
                        <td>
                          <Link
                            to={`/chargers/${encodeURIComponent(cs.charger_id)}?tab=research`}
                            style={{ fontWeight: 600, fontFamily: 'var(--mono)' }}
                          >
                            {cs.charger_id}
                          </Link>
                        </td>
                        <td>{cs.observation_count ?? 0}</td>
                        <td>{cs.session_count ?? 0}</td>
                        <td>{cs.alarm_count ?? 0}</td>
                        <td>{cs.gap_count ?? 0}</td>
                        <td>{percent(cs.missing_rate ?? 0)}</td>
                        <td>
                          <span style={{ fontWeight: 600, color: (cs.pattern_count ?? 0) > 0 ? '#38bdf8' : 'var(--text-dim)' }}>
                            {cs.pattern_count ?? 0}
                          </span>
                        </td>
                        <td>
                          <Link
                            className="btn-link"
                            to={`/chargers/${encodeURIComponent(cs.charger_id)}?tab=research`}
                            style={{ fontSize: 11, padding: '2px 8px' }}
                          >
                            Open Research Lab →
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty" style={{ padding: 24 }}>No chargers with Silver data available yet.</div>
            )}
          </div>
        ) : null}
      </section>
    </div>
  );
}
