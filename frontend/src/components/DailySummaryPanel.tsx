/**
 * The section 31 headline block, section 32 pipeline stages and section 36 fleet
 * distribution.
 *
 * Every figure is taken straight from the API. Nothing is derived here, including
 * the percentages - the backend is the single authority for them.
 */

import { count, duration, percent } from '../lib/format';
import type { DailySummary } from '../lib/types';

function Tile({
  label,
  value,
  note,
  tone,
  wide,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: 'ok' | 'warn' | 'bad';
  wide?: boolean;
}) {
  return (
    <div className={`tile${tone ? ` ${tone}` : ''}${wide ? ' wide' : ''}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note ? <div className="note">{note}</div> : null}
    </div>
  );
}

/** Tone thresholds mirror the backend completeness bands. */
function coverageTone(value: number): 'ok' | 'warn' | 'bad' {
  if (value >= 95) return 'ok';
  if (value >= 50) return 'warn';
  return 'bad';
}

export function SummaryTiles({ summary }: { summary: DailySummary }) {
  return (
    <div className="tiles">
      <Tile label="Expected" value={count(summary.expected)} note="chargers" />
      <Tile
        label="Received"
        value={count(summary.received)}
        note={percent(summary.fleet_delivery_rate)}
        tone={summary.received === summary.expected ? 'ok' : undefined}
      />
      <Tile label="Complete" value={count(summary.complete)} tone="ok" />
      <Tile
        label="Partial"
        value={count(summary.partial)}
        tone={summary.partial > 0 ? 'warn' : undefined}
      />
      <Tile
        label="Severe"
        value={count(summary.severely_incomplete)}
        note="severely incomplete"
        tone={summary.severely_incomplete > 0 ? 'bad' : undefined}
      />
      <Tile
        label="Late"
        value={count(summary.late)}
        tone={summary.late > 0 ? 'warn' : undefined}
      />
      <Tile
        label="Missing"
        value={count(summary.missing)}
        tone={summary.missing > 0 ? 'bad' : undefined}
      />
      <Tile
        label="Failed"
        value={count(summary.failed)}
        note="files"
        tone={summary.failed > 0 ? 'bad' : undefined}
      />
      <Tile
        label="Quarantined"
        value={count(summary.quarantined)}
        note="files"
        tone={summary.quarantined > 0 ? 'warn' : undefined}
      />
      <Tile
        label="Unexpected"
        value={count(summary.unexpected)}
        note="not in registry"
        tone={summary.unexpected > 0 ? 'warn' : undefined}
      />
      <Tile
        label="Fleet coverage"
        value={percent(summary.fleet_coverage_percentage, 2)}
        note="mean over expected charger-days; missing = 0%"
        tone={coverageTone(summary.fleet_coverage_percentage)}
        wide
      />
      <Tile
        label="Coverage p50 / p95"
        value={`${percent(summary.p50_coverage_percentage, 1)} / ${percent(
          summary.p95_coverage_percentage,
          1,
        )}`}
        note="nearest-rank"
        wide
      />
      <Tile
        label="Gaps"
        value={count(summary.total_gap_count)}
        note={`largest ${duration(summary.largest_gap_seconds)}`}
      />
      <Tile
        label="p95 largest gap"
        value={duration(summary.p95_largest_gap_seconds)}
      />
    </div>
  );
}

export function ProcessingStages({ summary }: { summary: DailySummary }) {
  return (
    <section className="panel">
      <header>
        <h2>Daily processing status</h2>
        <span className="hint">Derived from the ingestion runs that delivered this date</span>
      </header>
      <div className="stages">
        {summary.stages.map((stage) => {
          const tone =
            stage.status === 'COMPLETED'
              ? 'done'
              : stage.status === 'COMPLETED_WITH_WARNINGS'
                ? 'warn'
                : 'pending';
          return (
            <div key={stage.stage} className={`stage ${tone}`}>
              <div className="name">{stage.stage}</div>
              <div className="meta">
                {stage.status.replace(/_/g, ' ').toLowerCase()}
                {stage.count !== null ? ` · ${count(stage.count)}` : ''}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

interface Segment {
  key: string;
  label: string;
  value: number;
  colour: string;
}

export function FleetDistribution({ summary }: { summary: DailySummary }) {
  // Complete/Partial/Severe/Missing partition the expected charger-days; Late is
  // an arrival property that overlaps them, so it is reported separately below
  // rather than as a slice that would double-count.
  const segments: Segment[] = [
    { key: 'complete', label: 'Complete', value: summary.complete, colour: 'var(--ok)' },
    { key: 'partial', label: 'Partial', value: summary.partial, colour: 'var(--warn)' },
    {
      key: 'severe',
      label: 'Severely incomplete',
      value: summary.severely_incomplete,
      colour: '#b35c00',
    },
    { key: 'missing', label: 'Missing', value: summary.missing, colour: 'var(--bad)' },
  ];

  const total = segments.reduce((sum, segment) => sum + segment.value, 0);

  return (
    <section className="panel">
      <header>
        <h2>Fleet coverage distribution</h2>
        <span className="hint">{count(total)} charger-days</span>
      </header>
      <div style={{ padding: 14 }}>
        {total === 0 ? (
          <div className="empty">No charger-days evaluated for this date.</div>
        ) : (
          <>
            <div
              className="distribution"
              role="img"
              aria-label={segments
                .map((segment) => `${segment.label}: ${segment.value}`)
                .join(', ')}
            >
              {segments
                .filter((segment) => segment.value > 0)
                .map((segment) => {
                  const share = (segment.value / total) * 100;
                  return (
                    <div
                      key={segment.key}
                      style={{ width: `${share}%`, background: segment.colour }}
                      title={`${segment.label}: ${segment.value} (${share.toFixed(1)}%)`}
                    >
                      {share > 7 ? segment.value : ''}
                    </div>
                  );
                })}
            </div>
            <div className="legend">
              {segments.map((segment) => (
                <span key={segment.key}>
                  <span className="swatch" style={{ background: segment.colour }} />
                  {segment.label} {count(segment.value)}
                </span>
              ))}
              <span>
                <span className="swatch" style={{ background: 'var(--info)' }} />
                Late {count(summary.late)} (arrival timing, overlaps the above)
              </span>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

export function DailyFindings({ summary }: { summary: DailySummary }) {
  const entries = Object.entries(summary.daily_rule_counts).sort(
    (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
  );
  if (entries.length === 0) return null;

  return (
    <section className="panel">
      <header>
        <h2>Charger-day findings</h2>
        <span className="hint">Day-scope rules; file-level quality is reported separately</span>
      </header>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Rule</th>
              <th style={{ textAlign: 'right' }}>Charger-days</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([rule, total]) => (
              <tr key={rule}>
                <td>
                  <code>{rule}</code>
                </td>
                <td className="num">{count(total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
