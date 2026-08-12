/**
 * The three operational tables: missing (section 33), partial coverage
 * (section 34) and late arrivals (section 35).
 *
 * Rule applied throughout: a field the backend returned as null renders as "-".
 * No column is populated with a fabricated value to keep the table looking full.
 */

import { Link } from 'react-router-dom';

import { EMPTY, count, duration, isoDate, ofExpected, percent, timeOnly, timestamp } from '../lib/format';
import type { CoverageRow, GapRow, LateFileRow, MissingChargerRow } from '../lib/types';
import { ArrivalPill, CompletenessPill, CoverageBar, GapSeverityPill } from './status';

function ChargerLink({ chargerId, date }: { chargerId: string; date: string }) {
  return (
    <Link to={`/chargers/${encodeURIComponent(chargerId)}?date=${date}`}>{chargerId}</Link>
  );
}

export function MissingChargersTable({
  rows,
  date,
}: {
  rows: MissingChargerRow[];
  date: string;
}) {
  return (
    <section className="panel">
      <header>
        <h2>Missing chargers</h2>
        <span className="hint">
          Expected for this date, delivered no usable telemetry
        </span>
      </header>
      {rows.length === 0 ? (
        <div className="empty">No expected charger is missing telemetry for this date.</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Charger</th>
                <th>Site</th>
                <th>Expected since</th>
                <th>Last successful data</th>
                <th>Last seen</th>
                <th style={{ textAlign: 'right' }}>Previous day coverage</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.charger_id}>
                  <td>
                    <ChargerLink chargerId={row.charger_id} date={date} />
                  </td>
                  <td className={row.site_code ? '' : 'dim'}>{row.site_code ?? EMPTY}</td>
                  <td className={row.expected_since ? '' : 'dim'}>
                    {row.expected_since ? isoDate(row.expected_since) : EMPTY}
                  </td>
                  <td className={row.last_successful_date ? '' : 'dim'}>
                    {row.last_successful_date
                      ? `${isoDate(row.last_successful_date)} (${percent(
                          row.last_successful_coverage_percentage,
                        )})`
                      : EMPTY}
                  </td>
                  <td className={row.last_seen_at ? '' : 'dim'}>
                    {timestamp(row.last_seen_at)}
                  </td>
                  <td className="num">{percent(row.previous_day_coverage_percentage)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function CoverageTable({
  rows,
  date,
  title,
  hint,
}: {
  rows: CoverageRow[];
  date: string;
  title: string;
  hint?: string;
}) {
  return (
    <section className="panel">
      <header>
        <h2>{title}</h2>
        <span className="hint">{hint ?? 'Worst coverage first'}</span>
      </header>
      {rows.length === 0 ? (
        <div className="empty">No charger-days match the current filters.</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Charger</th>
                <th>Site</th>
                <th>Arrival</th>
                <th>Completeness</th>
                <th style={{ textAlign: 'right' }}>Coverage</th>
                <th>First sample</th>
                <th>Last sample</th>
                <th style={{ textAlign: 'right' }}>Unique</th>
                <th style={{ textAlign: 'right' }}>Expected</th>
                <th style={{ textAlign: 'right' }}>Largest gap</th>
                <th style={{ textAlign: 'right' }}>Gaps</th>
                <th style={{ textAlign: 'right' }}>Connectors</th>
                <th style={{ textAlign: 'right' }}>SMRs</th>
                <th style={{ textAlign: 'right' }}>Files</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.charger_id}-${row.business_date}`}>
                  <td>
                    <ChargerLink chargerId={row.charger_id} date={date} />
                  </td>
                  <td className={row.site_code ? '' : 'dim'}>{row.site_code ?? EMPTY}</td>
                  <td>
                    <ArrivalPill status={row.arrival_status} />
                  </td>
                  <td>
                    <CompletenessPill status={row.completeness_status} />
                  </td>
                  <td className="num">
                    <CoverageBar value={row.coverage_percentage} />
                  </td>
                  <td>{timeOnly(row.first_event_at)}</td>
                  <td>{timeOnly(row.last_event_at)}</td>
                  <td className="num">{count(row.unique_timestamp_count)}</td>
                  <td className="num dim">{count(row.expected_timestamp_count)}</td>
                  <td className="num">{duration(row.largest_gap_seconds)}</td>
                  <td className="num">{count(row.gap_count)}</td>
                  <td className="num">
                    {ofExpected(row.connector_count_detected, row.expected_connector_count)}
                  </td>
                  <td className="num">
                    {ofExpected(row.smr_count_detected, row.expected_smr_count)}
                  </td>
                  <td className="num">{count(row.file_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function LateArrivalsTable({ rows, date }: { rows: LateFileRow[]; date: string }) {
  return (
    <section className="panel">
      <header>
        <h2>Late arrivals</h2>
        <span className="hint">
          Measured from receipt time against the configured cutoff, never processing time
        </span>
      </header>
      {rows.length === 0 ? (
        <div className="empty">No telemetry arrived late for this date.</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Charger</th>
                <th>Telemetry date</th>
                <th>Received at</th>
                <th style={{ textAlign: 'right' }}>Delay</th>
                <th style={{ textAlign: 'right' }}>Coverage</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.charger_id}>
                  <td>
                    <ChargerLink chargerId={row.charger_id} date={date} />
                  </td>
                  <td>{isoDate(row.business_date)}</td>
                  <td>{timestamp(row.received_at)}</td>
                  <td className="num">{duration(row.late_by_seconds)}</td>
                  <td className="num">
                    <CoverageBar value={row.coverage_percentage} />
                  </td>
                  <td>
                    <CompletenessPill status={row.completeness_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function GapsTable({ rows }: { rows: GapRow[] }) {
  if (rows.length === 0) {
    return <div className="empty">No telemetry gaps detected.</div>;
  }
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Gap start</th>
            <th>Gap end</th>
            <th style={{ textAlign: 'right' }}>Duration</th>
            <th style={{ textAlign: 'right' }}>Missing samples (est.)</th>
            <th>Severity</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.business_date}-${row.start_event_at}-${row.end_event_at}`}>
              <td>{isoDate(row.business_date)}</td>
              <td>{timestamp(row.start_event_at)}</td>
              <td>{timestamp(row.end_event_at)}</td>
              <td className="num">{duration(row.duration_seconds)}</td>
              <td className="num dim">{count(row.estimated_missing_samples)}</td>
              <td>
                <GapSeverityPill severity={row.severity} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
