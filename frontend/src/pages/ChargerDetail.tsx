/**
 * Charger detail with the Coverage tab (section 37) and gap timeline (section 38).
 *
 * Only Phase 1C data is shown. There is no health score and no prediction here by
 * design - this page reports telemetry *delivery*, not charger condition.
 */

import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { GapTimeline } from '../components/GapTimeline';
import { FramesTab } from './FramesTab';
import { CompletenessPill, ArrivalPill, CoverageBar, SeverityPill } from '../components/status';
import { GapsTable } from '../components/tables';
import { api } from '../lib/api';
import { EMPTY, count, duration, isoDate, ofExpected, percent, timestamp, today } from '../lib/format';
import { useAsync } from '../lib/useAsync';

function daysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

export function ChargerDetail() {
  const { chargerId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const selectedDate = params.get('date') ?? today();
  const [rangeDays, setRangeDays] = useState(30);
  // Tab lives in the URL so a view is refreshable, bookmarkable and shareable.
  const tab = params.get('tab') === 'frames' ? 'frames' : 'coverage';
  const setTab = (value: 'coverage' | 'frames') => {
    const next = new URLSearchParams(params);
    next.set('tab', value);
    setParams(next, { replace: true });
  };

  const history = useAsync(
    () => api.coverageHistory(chargerId, daysAgo(rangeDays), today()),
    [chargerId, rangeDays],
  );
  const day = useAsync(() => api.chargerDay(chargerId, selectedDate), [chargerId, selectedDate]);

  const selectDate = (value: string) => {
    const next = new URLSearchParams(params);
    next.set('date', value);
    setParams(next, { replace: true });
  };

  const detail = day.data?.data ?? null;

  return (
    <div className="app">
      <div className="masthead">
        <div>
          <h1>{chargerId}</h1>
          <div className="sub">
            Telemetry coverage history. <Link to="/data-operations">Back to data operations</Link>
          </div>
        </div>
        <div className="controls">
          {[7, 30, 90].map((days) => (
            <button
              key={days}
              className={rangeDays === days ? 'active' : ''}
              onClick={() => setRangeDays(days)}
            >
              {days}d
            </button>
          ))}
          <input
            type="date"
            value={selectedDate}
            max={today()}
            onChange={(event) => selectDate(event.target.value)}
          />
        </div>
      </div>

      <div className="tabs">
        <button
          className={tab === 'coverage' ? 'active' : ''}
          onClick={() => setTab('coverage')}
        >
          Coverage
        </button>
        <button
          className={tab === 'frames' ? 'active' : ''}
          onClick={() => setTab('frames')}
        >
          Reconstruction
        </button>
      </div>

      {tab === 'frames' ? (
        <FramesTab chargerId={chargerId} businessDate={selectedDate} />
      ) : null}

      {/* ---- Coverage history (section 37) ---- */}
      {tab === 'coverage' ? (
      <section className="panel">
        <header>
          <h2>Coverage</h2>
          <span className="hint">Last {rangeDays} days · select a row to inspect its gaps</span>
        </header>
        {history.error ? (
          <div className="error">{history.error}</div>
        ) : history.loading && !history.data ? (
          <div className="loading">Loading coverage history…</div>
        ) : !history.data?.data?.length ? (
          <div className="empty">No coverage records in this range.</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th style={{ textAlign: 'right' }}>Coverage</th>
                  <th>Arrival</th>
                  <th>Completeness</th>
                  <th style={{ textAlign: 'right' }}>Gaps</th>
                  <th style={{ textAlign: 'right' }}>Largest gap</th>
                  <th style={{ textAlign: 'right' }}>Files</th>
                  <th style={{ textAlign: 'right' }}>Connectors</th>
                  <th style={{ textAlign: 'right' }}>SMRs</th>
                  <th style={{ textAlign: 'right' }}>File quality</th>
                </tr>
              </thead>
              <tbody>
                {history.data.data.map((row) => (
                  <tr
                    key={row.business_date}
                    onClick={() => selectDate(row.business_date)}
                    style={{
                      cursor: 'pointer',
                      background:
                        row.business_date === selectedDate ? 'var(--surface-2)' : undefined,
                    }}
                  >
                    <td>{isoDate(row.business_date)}</td>
                    <td className="num">
                      <CoverageBar value={row.coverage_percentage} />
                    </td>
                    <td>
                      <ArrivalPill status={row.arrival_status} />
                    </td>
                    <td>
                      <CompletenessPill status={row.completeness_status} />
                    </td>
                    <td className="num">{count(row.gap_count)}</td>
                    <td className="num">{duration(row.largest_gap_seconds)}</td>
                    <td className="num">{count(row.file_count)}</td>
                    <td className="num">
                      {ofExpected(row.connector_count_detected, row.expected_connector_count)}
                    </td>
                    <td className="num">
                      {ofExpected(row.smr_count_detected, row.expected_smr_count)}
                    </td>
                    <td className="num dim">{percent(row.quality_score, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      ) : null}

      {/* ---- Selected charger-day ---- */}
      {tab === 'coverage' ? (
      <section className="panel">
        <header>
          <h2>{isoDate(selectedDate)} · gap timeline</h2>
          <span className="hint">Gaps are drawn, never interpolated across</span>
        </header>
        {day.error ? (
          <div className="empty">No coverage record for this charger on {selectedDate}.</div>
        ) : day.loading && !detail ? (
          <div className="loading">Loading charger-day…</div>
        ) : detail ? (
          <>
            <GapTimeline coverage={detail.coverage} gaps={detail.gaps} />

            <div className="callout">
              {count(detail.coverage.unique_timestamp_count)} unique event timestamps of{' '}
              {count(detail.coverage.expected_timestamp_count)} expected ·{' '}
              span {percent(detail.coverage.span_coverage_percentage, 2)} · gap-adjusted{' '}
              {percent(detail.coverage.gap_adjusted_coverage_percentage, 2)} · sample{' '}
              {percent(detail.coverage.sample_coverage_percentage, 2)} (headline)
            </div>

            <GapsTable rows={detail.gaps} />
          </>
        ) : null}
      </section>
      ) : null}

      {/* ---- Contributing files (section 19) ---- */}
      {tab === 'coverage' && detail && detail.files.length > 0 ? (
        <section className="panel">
          <header>
            <h2>Contributing files</h2>
            <span className="hint">
              {detail.files.length > 1
                ? 'Several files combine into this charger-day'
                : 'One file contributed to this charger-day'}
            </span>
          </header>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Status</th>
                  <th>Received</th>
                  <th style={{ textAlign: 'right' }}>Unique timestamps</th>
                  <th style={{ textAlign: 'right' }}>Raw rows</th>
                  <th>Filename date</th>
                  <th style={{ textAlign: 'right' }}>Quality</th>
                </tr>
              </thead>
              <tbody>
                {detail.files.map((file) => (
                  <tr key={file.telemetry_file_id}>
                    <td>
                      <code>{file.original_filename}</code>
                    </td>
                    <td>{file.status}</td>
                    <td>{timestamp(file.received_at)}</td>
                    <td className="num">{count(file.unique_timestamp_count_for_date)}</td>
                    <td className="num dim">{count(file.row_count_for_date)}</td>
                    <td>
                      {file.filename_date === null ? (
                        <span className="dim">{EMPTY}</span>
                      ) : file.filename_date_matches_event_date ? (
                        isoDate(file.filename_date)
                      ) : (
                        <span title="The filename date disagrees with the telemetry; the event date is authoritative.">
                          {isoDate(file.filename_date)} <span className="pill warn">MISMATCH</span>
                        </span>
                      )}
                    </td>
                    <td className="num dim">{percent(file.quality_score, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="callout">
            Raw rows are shown for context only. Coverage is computed from unique event
            timestamps — the raw grain repeats each timestamp once per connector/SMR
            combination, so raw rows cannot measure coverage.
          </div>
        </section>
      ) : null}

      {/* ---- Charger-day findings ---- */}
      {tab === 'coverage' && detail && detail.findings.length > 0 ? (
        <section className="panel">
          <header>
            <h2>Charger-day findings</h2>
            <span className="hint">Day-scope only; file quality is reported per file above</span>
          </header>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Rule</th>
                  <th>Severity</th>
                  <th>Message</th>
                  <th style={{ textAlign: 'right' }}>Occurrences</th>
                </tr>
              </thead>
              <tbody>
                {detail.findings.map((finding) => (
                  <tr key={`${finding.rule_code}-${finding.detected_at}`}>
                    <td>
                      <code>{finding.rule_code}</code>
                    </td>
                    <td>
                      <SeverityPill severity={finding.severity} />
                    </td>
                    <td style={{ whiteSpace: 'normal' }}>{finding.message}</td>
                    <td className="num">{count(finding.occurrence_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
