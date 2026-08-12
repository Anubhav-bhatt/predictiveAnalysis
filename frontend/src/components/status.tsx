/**
 * Status rendering primitives.
 *
 * Every status carries a text label as well as colour, so meaning survives
 * greyscale printing and colour-vision differences.
 */

import type {
  ArrivalStatus,
  CompletenessStatus,
  GapSeverity,
  QualitySeverity,
} from '../lib/types';
import { EMPTY, percent } from '../lib/format';

type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'neutral';

const ARRIVAL_TONE: Record<ArrivalStatus, Tone> = {
  RECEIVED: 'ok',
  LATE: 'warn',
  MISSING: 'bad',
  UNEXPECTED: 'info',
  EXPECTED: 'neutral',
};

const COMPLETENESS_TONE: Record<CompletenessStatus, Tone> = {
  COMPLETE: 'ok',
  PARTIAL: 'warn',
  SEVERELY_INCOMPLETE: 'bad',
  NO_DATA: 'bad',
  UNKNOWN: 'neutral',
};

const GAP_TONE: Record<GapSeverity, Tone> = {
  MINOR: 'neutral',
  MODERATE: 'warn',
  MAJOR: 'bad',
  CRITICAL: 'bad',
};

const SEVERITY_TONE: Record<QualitySeverity, Tone> = {
  INFO: 'info',
  WARNING: 'warn',
  ERROR: 'bad',
  CRITICAL: 'bad',
};

export function Pill({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

export function ArrivalPill({ status }: { status: ArrivalStatus }) {
  return <Pill tone={ARRIVAL_TONE[status] ?? 'neutral'}>{status}</Pill>;
}

export function CompletenessPill({ status }: { status: CompletenessStatus }) {
  // SEVERELY_INCOMPLETE is long; abbreviate in the pill but keep it in the title.
  const label = status === 'SEVERELY_INCOMPLETE' ? 'SEVERE' : status;
  return (
    <span className={`pill ${COMPLETENESS_TONE[status] ?? 'neutral'}`} title={status}>
      {label}
    </span>
  );
}

export function GapSeverityPill({ severity }: { severity: GapSeverity }) {
  return <Pill tone={GAP_TONE[severity] ?? 'neutral'}>{severity}</Pill>;
}

export function SeverityPill({ severity }: { severity: QualitySeverity }) {
  return <Pill tone={SEVERITY_TONE[severity] ?? 'neutral'}>{severity}</Pill>;
}

/** Colour follows the completeness bands, so the bar and the pill never disagree. */
function coverageColour(value: number): string {
  if (value >= 95) return 'var(--ok)';
  if (value >= 50) return 'var(--warn)';
  return 'var(--bad)';
}

export function CoverageBar({ value }: { value: string | number | null }) {
  if (value === null || value === '') {
    return <span className="dim">{EMPTY}</span>;
  }
  const numeric = typeof value === 'string' ? Number.parseFloat(value) : value;
  if (Number.isNaN(numeric)) return <span className="dim">{EMPTY}</span>;

  const clamped = Math.max(0, Math.min(100, numeric));
  return (
    <span className="coverage-cell">
      <span>{percent(numeric, 2)}</span>
      <span
        className="bar"
        role="img"
        aria-label={`${clamped.toFixed(1)} percent coverage`}
      >
        <span style={{ width: `${clamped}%`, background: coverageColour(clamped) }} />
      </span>
    </span>
  );
}
