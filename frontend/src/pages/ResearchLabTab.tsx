/**
 * Scientific Research & Pattern Discovery Tab (Phase 9).
 *
 * Provides analytical dataset inspection, signal statistics, cross-signal
 * correlations, and candidate pattern discovery with evidence levels and
 * confidence scoring.
 */

import { useState } from 'react';
import { research } from '../lib/api';
import { timestamp, percent } from '../lib/format';
import type {
  AnalyticalDatasetSummary,
  PatternScanOutcome,
  PatternEvidenceLevel,
} from '../lib/types';
import { useAsync } from '../lib/useAsync';

interface ResearchLabTabProps {
  chargerId: string;
}

export function ResearchLabTab({ chargerId }: ResearchLabTabProps) {
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');
  const [selectedEvidence, setSelectedEvidence] = useState<string>('ALL');
  const [scanning, setScanning] = useState<boolean>(false);
  const [buildingDataset, setBuildingDataset] = useState<boolean>(false);
  const [scanOutcome, setScanOutcome] = useState<PatternScanOutcome | null>(null);
  const [datasetOutcome, setDatasetOutcome] = useState<AnalyticalDatasetSummary | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [expandedPatternId, setExpandedPatternId] = useState<string | null>(null);

  // Queries
  const statsAsync = useAsync(
    () => research.signalStats(chargerId),
    [chargerId],
  );
  const stats = statsAsync.data?.data ?? [];

  const correlationsAsync = useAsync(
    () => research.correlations(chargerId),
    [chargerId],
  );
  const correlationEntries = correlationsAsync.data?.data?.entries ?? [];

  const patternsAsync = useAsync(
    () =>
      research.patterns(chargerId, {
        pattern_category: selectedCategory !== 'ALL' ? selectedCategory : undefined,
        evidence_level: selectedEvidence !== 'ALL' ? selectedEvidence : undefined,
        limit: 200,
      }),
    [chargerId, selectedCategory, selectedEvidence, scanOutcome],
  );
  const patterns = patternsAsync.data?.data ?? [];

  const handleScan = async () => {
    setScanning(true);
    setActionError(null);
    try {
      const resp = await research.scanPatterns(chargerId);
      if (resp.data) {
        setScanOutcome(resp.data);
      }
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setScanning(false);
    }
  };

  const handleBuildDataset = async () => {
    setBuildingDataset(true);
    setActionError(null);
    try {
      const resp = await research.buildDataset(chargerId, 'CHARGER_TIME');
      if (resp.data) {
        setDatasetOutcome(resp.data);
      }
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBuildingDataset(false);
    }
  };

  // Metrics
  const highConfidenceCount = patterns.filter((p) => p.confidence_score >= 0.7).length;
  const avgMissingRate =
    stats.length > 0
      ? stats.reduce((acc, s) => acc + s.missing_rate, 0) / stats.length
      : 0;

  const getEvidenceBadgeClass = (level: PatternEvidenceLevel) => {
    switch (level) {
      case 'CONFIRMED_PRECURSOR':
        return 'evidence-pill precursor';
      case 'STRONG_CANDIDATE':
        return 'evidence-pill strong';
      case 'MODERATE_CANDIDATE':
        return 'evidence-pill moderate';
      case 'WEAK_CANDIDATE':
        return 'evidence-pill weak';
      default:
        return 'evidence-pill observation';
    }
  };

  return (
    <div className="research-tab">
      {/* Action Header Banner */}
      <section className="panel" style={{ marginBottom: 16 }}>
        <div className="event-tab-header">
          <div>
            <h2 style={{ margin: 0 }}>Scientific Research & Pattern Discovery</h2>
            <div className="sub" style={{ marginTop: 4 }}>
              Empirical pattern scanning across continuous Silver timelines, session boundaries, and alarm intervals.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button
              onClick={handleBuildDataset}
              disabled={buildingDataset}
              className="action-btn"
            >
              {buildingDataset ? 'Building Dataset…' : 'Build Analytical Dataset'}
            </button>
            <button
              onClick={handleScan}
              disabled={scanning}
              className="action-btn primary"
            >
              {scanning ? 'Scanning Timelines…' : 'Scan Candidate Patterns'}
            </button>
          </div>
        </div>

        {actionError ? (
          <div className="error" style={{ marginTop: 12 }}>
            {actionError}
          </div>
        ) : null}

        {scanOutcome ? (
          <div className="reconstruct-banner" style={{ marginTop: 12 }}>
            <span className="reconstruct-status-pill">✓ Pattern Scan Complete</span>
            <span>
              Discovered <strong>{scanOutcome.candidates_found}</strong> candidates (
              <strong>{scanOutcome.candidates_persisted}</strong> persisted) across{' '}
              {scanOutcome.signals_scanned} signals and {scanOutcome.records_analyzed} records in{' '}
              {scanOutcome.scan_duration_ms}ms (v{scanOutcome.scan_version}).
            </span>
          </div>
        ) : null}

        {datasetOutcome ? (
          <div className="reconstruct-banner" style={{ marginTop: 12 }}>
            <span className="reconstruct-status-pill">✓ Dataset Ready</span>
            <span>
              Constructed <strong>{datasetOutcome.record_count}</strong> aligned records across{' '}
              {datasetOutcome.signal_count} signals with {datasetOutcome.gap_count} gaps ({percent(datasetOutcome.missing_rate)} missing rate) in{' '}
              {datasetOutcome.build_duration_ms}ms.
            </span>
          </div>
        ) : null}
      </section>

      {/* KPI Cards */}
      <div className="event-kpi-grid" style={{ marginBottom: 20 }}>
        <div className="event-kpi-card">
          <div className="kpi-label">Discovered Patterns</div>
          <div className="kpi-val">{patterns.length}</div>
          <div className="kpi-sub">Total candidate patterns</div>
        </div>
        <div className="event-kpi-card">
          <div className="kpi-label">High Confidence</div>
          <div className="kpi-val" style={{ color: '#10b981' }}>{highConfidenceCount}</div>
          <div className="kpi-sub">Confidence score ≥ 70%</div>
        </div>
        <div className="event-kpi-card">
          <div className="kpi-label">Signals Evaluated</div>
          <div className="kpi-val">{stats.length}</div>
          <div className="kpi-sub">Continuous Silver telemetry</div>
        </div>
        <div className="event-kpi-card">
          <div className="kpi-label">Average Missing Rate</div>
          <div className="kpi-val">{percent(avgMissingRate)}</div>
          <div className="kpi-sub">Silver null + sentinel rate</div>
        </div>
      </div>

      {/* Pattern Candidates List */}
      <section className="panel" style={{ marginBottom: 20 }}>
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
          <div>
            <h2 style={{ margin: 0 }}>Candidate Patterns</h2>
            <span className="hint">Empirically discovered precursor patterns & anomalies</span>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              style={{ background: 'var(--surface-2)', color: 'var(--text)', border: '1px solid var(--border)', padding: '4px 8px', borderRadius: 4 }}
            >
              <option value="ALL">All Categories</option>
              <option value="THERMAL_DRIFT">Thermal Drift</option>
              <option value="VOLTAGE_ANOMALY">Voltage Anomaly</option>
              <option value="CURRENT_IMBALANCE">Current Imbalance</option>
              <option value="SESSION_DEGRADATION">Session Degradation</option>
              <option value="ALARM_CLUSTERING">Alarm Clustering</option>
              <option value="FAULT_RECURRENCE">Fault Recurrence</option>
              <option value="EFFICIENCY_DECLINE">Efficiency Decline</option>
              <option value="COMPONENT_DIVERGENCE">Component Divergence</option>
              <option value="OPERATIONAL_PATTERN">Operational Pattern</option>
            </select>
            <select
              value={selectedEvidence}
              onChange={(e) => setSelectedEvidence(e.target.value)}
              style={{ background: 'var(--surface-2)', color: 'var(--text)', border: '1px solid var(--border)', padding: '4px 8px', borderRadius: 4 }}
            >
              <option value="ALL">All Evidence Levels</option>
              <option value="CONFIRMED_PRECURSOR">Confirmed Precursor</option>
              <option value="STRONG_CANDIDATE">Strong Candidate</option>
              <option value="MODERATE_CANDIDATE">Moderate Candidate</option>
              <option value="WEAK_CANDIDATE">Weak Candidate</option>
              <option value="OBSERVATION">Observation</option>
            </select>
          </div>
        </header>

        {patternsAsync.loading && !patterns.length ? (
          <div className="loading" style={{ padding: 24 }}>Analyzing candidate patterns…</div>
        ) : patterns.length === 0 ? (
          <div className="empty" style={{ padding: 24 }}>
            No pattern candidates match the current filters. Click "Scan Candidate Patterns" above to run discovery.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '16px 0' }}>
            {patterns.map((p, idx) => {
              const pKey = p.id || `pat-${idx}`;
              const isExpanded = expandedPatternId === pKey;
              return (
                <div
                  key={pKey}
                  className="pattern-card"
                  style={{
                    background: 'var(--surface-2)',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    padding: 16,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
                    <div>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                        <span className={getEvidenceBadgeClass(p.evidence_level)}>
                          {p.evidence_level.replace('_', ' ')}
                        </span>
                        <span className="tag-badge">{p.pattern_category}</span>
                        {p.analytical_grain ? <span className="tag-badge">{p.analytical_grain}</span> : null}
                      </div>
                      <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>
                        {p.title}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 18, fontWeight: 700, color: p.confidence_score >= 0.7 ? '#10b981' : p.confidence_score >= 0.4 ? '#f59e0b' : '#8b98a5' }}>
                        {(p.confidence_score * 100).toFixed(0)}%
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Confidence</div>
                    </div>
                  </div>

                  <p style={{ margin: '8px 0', fontSize: 13, color: 'var(--text-dim)' }}>
                    {p.description}
                  </p>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginTop: 12, fontSize: 12 }}>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                      <span style={{ color: 'var(--text-faint)' }}>Signals:</span>
                      {p.affected_signals.map((sig) => (
                        <span key={sig} className="tag-badge" style={{ color: '#38bdf8' }}>{sig}</span>
                      ))}
                      {p.affected_components.length > 0 ? (
                        <>
                          <span style={{ color: 'var(--text-faint)', marginLeft: 6 }}>Components:</span>
                          {p.affected_components.map((c) => (
                            <span key={c} className="tag-badge">{c}</span>
                          ))}
                        </>
                      ) : null}
                    </div>

                    <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                      {p.observation_window_start ? (
                        <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-faint)' }}>
                          {timestamp(p.observation_window_start)}
                          {p.observation_window_end ? ` → ${timestamp(p.observation_window_end)}` : ''}
                        </span>
                      ) : null}
                      <button
                        onClick={() => setExpandedPatternId(isExpanded ? null : pKey)}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--info)',
                          cursor: 'pointer',
                          fontSize: 12,
                          padding: '2px 6px',
                        }}
                      >
                        {isExpanded ? 'Hide Evidence ▲' : 'Show Evidence ▼'}
                      </button>
                    </div>
                  </div>

                  {isExpanded && p.supporting_evidence.length > 0 ? (
                    <div style={{ marginTop: 12, padding: 12, background: 'var(--surface)', borderRadius: 4, border: '1px solid var(--border)' }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-dim)', marginBottom: 6 }}>SUPPORTING SCIENTIFIC EVIDENCE:</div>
                      <pre style={{ margin: 0, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--text)', whiteSpace: 'pre-wrap', overflowX: 'auto' }}>
                        {JSON.stringify(p.supporting_evidence, null, 2)}
                      </pre>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Cross-Signal Correlations */}
      <section className="panel" style={{ marginBottom: 20 }}>
        <header>
          <h2>Cross-Signal Correlations</h2>
          <span className="hint">Pairwise Pearson r and Spearman rank correlations</span>
        </header>

        {correlationsAsync.loading && !correlationEntries.length ? (
          <div className="loading" style={{ padding: 24 }}>Calculating correlations…</div>
        ) : correlationEntries.length === 0 ? (
          <div className="empty" style={{ padding: 24 }}>
            No pairwise correlation entries available (signals may be constant, singular, or sparse).
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Signal A</th>
                  <th>Signal B</th>
                  <th>Pearson r</th>
                  <th>Spearman ρ</th>
                  <th>Sample Count</th>
                  <th>Interpretation</th>
                </tr>
              </thead>
              <tbody>
                {correlationEntries.map((e, idx) => {
                  const r = e.pearson_r;
                  const rStr = r !== null ? r.toFixed(3) : '—';
                  const rhoStr = e.spearman_rho !== null ? e.spearman_rho.toFixed(3) : '—';
                  const absR = r !== null ? Math.abs(r) : 0;
                  const rColor =
                    r === null
                      ? 'var(--text-dim)'
                      : r > 0.6
                      ? '#10b981'
                      : r < -0.6
                      ? '#f59e0b'
                      : 'var(--text)';

                  let interpretation = 'No linear relationship';
                  if (absR >= 0.8) interpretation = r! > 0 ? 'Strong positive co-movement' : 'Strong negative co-movement';
                  else if (absR >= 0.5) interpretation = r! > 0 ? 'Moderate positive correlation' : 'Moderate negative correlation';
                  else if (absR >= 0.3) interpretation = 'Weak correlation';

                  return (
                    <tr key={`${e.signal_a}-${e.signal_b}-${idx}`}>
                      <td style={{ fontFamily: 'var(--mono)', fontWeight: 600, color: '#38bdf8' }}>{e.signal_a}</td>
                      <td style={{ fontFamily: 'var(--mono)', fontWeight: 600, color: '#818cf8' }}>{e.signal_b}</td>
                      <td style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: rColor }}>{rStr}</td>
                      <td style={{ fontFamily: 'var(--mono)' }}>{rhoStr}</td>
                      <td>{e.sample_count}</td>
                      <td style={{ color: 'var(--text-dim)', fontSize: 12 }}>{interpretation}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Descriptive Signal Statistics */}
      <section className="panel">
        <header>
          <h2>Descriptive Signal Statistics</h2>
          <span className="hint">Empirical distributions, valid counts, sentinels, and missing rates</span>
        </header>

        {statsAsync.loading && !stats.length ? (
          <div className="loading" style={{ padding: 24 }}>Loading signal statistics…</div>
        ) : stats.length === 0 ? (
          <div className="empty" style={{ padding: 24 }}>No normalized Silver signals found for this charger.</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Signal</th>
                  <th>Non-Null</th>
                  <th>Null</th>
                  <th>Sentinels</th>
                  <th>Min</th>
                  <th>Max</th>
                  <th>Mean ± Std</th>
                  <th>Median (P50)</th>
                  <th>P95</th>
                  <th>Missing Rate</th>
                </tr>
              </thead>
              <tbody>
                {stats.map((s) => {
                  const meanStr = s.mean !== null ? s.mean.toFixed(2) : '—';
                  const stdStr = s.std !== null ? `± ${s.std.toFixed(2)}` : '';
                  const minStr = s.min_val !== null ? s.min_val.toFixed(2) : '—';
                  const maxStr = s.max_val !== null ? s.max_val.toFixed(2) : '—';
                  const p50Str = s.p50 !== null ? s.p50.toFixed(2) : '—';
                  const p95Str = s.p95 !== null ? s.p95.toFixed(2) : '—';

                  return (
                    <tr key={s.signal_name}>
                      <td style={{ fontFamily: 'var(--mono)', fontWeight: 600 }}>{s.signal_name}</td>
                      <td>{s.non_null_count}</td>
                      <td>{s.null_count}</td>
                      <td style={{ color: s.sentinel_count > 0 ? '#ef4444' : 'var(--text-dim)' }}>
                        {s.sentinel_count}
                      </td>
                      <td style={{ fontFamily: 'var(--mono)' }}>{minStr}</td>
                      <td style={{ fontFamily: 'var(--mono)' }}>{maxStr}</td>
                      <td style={{ fontFamily: 'var(--mono)' }}>{meanStr} {stdStr}</td>
                      <td style={{ fontFamily: 'var(--mono)' }}>{p50Str}</td>
                      <td style={{ fontFamily: 'var(--mono)' }}>{p95Str}</td>
                      <td>
                        <span style={{
                          color: s.missing_rate > 0.1 ? '#f59e0b' : '#10b981',
                          fontWeight: 600,
                        }}>
                          {percent(s.missing_rate)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
