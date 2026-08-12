/**
 * Gap timeline for one charger-day (section 38).
 *
 *   00:00 ─────────────────────────── 24:00
 *   ███████████      █████████████████████
 *              GAP
 *
 * Two absence kinds are drawn differently on purpose:
 *
 * - **Gaps** (red) are holes *between* observations.
 * - **Leading/trailing absence** (grey) is time before the first or after the last
 *   observation. That is not an inter-sample gap, and colouring it the same would
 *   conflate "stopped reporting mid-day" with "started reporting late".
 *
 * Nothing is interpolated across a gap.
 */

import { duration, timeOnly } from '../lib/format';
import type { CoverageRow, GapRow } from '../lib/types';

const DAY_SECONDS = 86_400;

/** Seconds from the start of the charger-day's local date, clamped to the day. */
function offsetWithinDay(iso: string, dayStart: number): number {
  const seconds = (new Date(iso).getTime() - dayStart) / 1000;
  return Math.max(0, Math.min(DAY_SECONDS, seconds));
}

export function GapTimeline({
  coverage,
  gaps,
}: {
  coverage: CoverageRow;
  gaps: GapRow[];
}) {
  if (!coverage.first_event_at || !coverage.last_event_at) {
    return (
      <div className="empty">
        No telemetry for this charger-day, so there is no timeline to draw.
      </div>
    );
  }

  // Anchor the track to local midnight of the first observation, which is the
  // charger's own day boundary.
  const first = new Date(coverage.first_event_at);
  const dayStart = new Date(
    first.getFullYear(),
    first.getMonth(),
    first.getDate(),
  ).getTime();

  const firstOffset = offsetWithinDay(coverage.first_event_at, dayStart);
  const lastOffset = offsetWithinDay(coverage.last_event_at, dayStart);

  const pct = (seconds: number) => `${(seconds / DAY_SECONDS) * 100}%`;

  return (
    <div className="timeline">
      <div
        className="timeline-track"
        role="img"
        aria-label={
          `Telemetry from ${timeOnly(coverage.first_event_at)} to ` +
          `${timeOnly(coverage.last_event_at)} with ${gaps.length} gap(s)`
        }
      >
        {/* Absence before the first observation. */}
        {firstOffset > 0 ? (
          <div
            className="timeline-absent"
            style={{ left: 0, width: pct(firstOffset) }}
            title={`No telemetry before ${timeOnly(coverage.first_event_at)}`}
          />
        ) : null}

        {/* Absence after the last observation. */}
        {lastOffset < DAY_SECONDS ? (
          <div
            className="timeline-absent"
            style={{ left: pct(lastOffset), width: pct(DAY_SECONDS - lastOffset) }}
            title={`No telemetry after ${timeOnly(coverage.last_event_at)}`}
          />
        ) : null}

        {/* Inter-sample gaps. */}
        {gaps.map((gap) => {
          const start = offsetWithinDay(gap.start_event_at, dayStart);
          const end = offsetWithinDay(gap.end_event_at, dayStart);
          const width = Math.max(end - start, DAY_SECONDS / 400); // keep thin gaps visible
          return (
            <div
              key={`${gap.start_event_at}-${gap.end_event_at}`}
              className="timeline-gap"
              style={{ left: pct(start), width: pct(width) }}
              title={
                `${gap.severity} gap: ${timeOnly(gap.start_event_at)} to ` +
                `${timeOnly(gap.end_event_at)} (${duration(gap.duration_seconds)})`
              }
            />
          );
        })}
      </div>

      <div className="timeline-axis">
        {['00:00', '06:00', '12:00', '18:00', '24:00'].map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>

      <div className="legend">
        <span>
          <span className="swatch" style={{ background: 'var(--ok)' }} />
          Telemetry present
        </span>
        <span>
          <span className="swatch" style={{ background: 'var(--bad)' }} />
          Gap between samples ({gaps.length})
        </span>
        <span>
          <span className="swatch" style={{ background: 'var(--surface-2)' }} />
          Before first / after last sample
        </span>
      </div>
    </div>
  );
}
