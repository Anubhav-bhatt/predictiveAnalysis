/**
 * Display formatting.
 *
 * One rule governs this module: **a missing value renders as "-", never as 0.**
 * The backend returns null when something was genuinely not measured, and showing
 * a zero there would invent data - which is exactly what a data-operations
 * console must not do.
 */

export const EMPTY = '-';

export function percent(value: string | number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || value === '') return EMPTY;
  const numeric = typeof value === 'string' ? Number.parseFloat(value) : value;
  if (Number.isNaN(numeric)) return EMPTY;
  return `${numeric.toFixed(digits)}%`;
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return EMPTY;
  return value.toLocaleString('en-US');
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return EMPTY;
  if (seconds < 60) return `${Math.round(seconds)}s`;

  const totalMinutes = Math.floor(seconds / 60);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`;
  return `${minutes}m`;
}

/** Timestamps arrive as UTC ISO strings; render them in the viewer's locale. */
export function timestamp(value: string | null | undefined): string {
  if (!value) return EMPTY;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return EMPTY;
  return parsed.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function timeOnly(value: string | null | undefined): string {
  if (!value) return EMPTY;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return EMPTY;
  return parsed.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

export function isoDate(value: string | null | undefined): string {
  if (!value) return EMPTY;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Ratio of detected to expected topology, e.g. "1 / 2". Never fabricates. */
export function ofExpected(
  detected: number | null | undefined,
  expected: number | null | undefined,
): string {
  if (detected === null || detected === undefined) return EMPTY;
  if (expected === null || expected === undefined) return count(detected);
  return `${detected} / ${expected}`;
}
