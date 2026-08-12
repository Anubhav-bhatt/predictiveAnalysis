/**
 * The single boundary to the backend.
 *
 * Every figure the UI shows comes from here. Nothing is computed client-side: a
 * percentage recalculated in the browser could disagree with the same percentage
 * in the daily report, and there would be no way to tell which one was wrong.
 */

import type {
  ChargerDayDetail,
  CoverageRow,
  DailySummary,
  Envelope,
  GapRow,
  IngestionRun,
  LateFileRow,
  MissingChargerRow,
  PaginatedEnvelope,
} from './types';

const BASE = '/api/v1';

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = 'ApiRequestError';
  }
}

async function request<T>(path: string, params?: Record<string, string | number | undefined>) {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== '') url.searchParams.set(key, String(value));
  }

  const response = await fetch(url.toString(), {
    headers: { Accept: 'application/json' },
  });

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiRequestError(
      `${response.status} ${response.statusText}`,
      response.status,
    );
  }

  // The backend uses one envelope shape for successes and failures alike, so the
  // error path is read from the same place rather than guessed from the status.
  const envelope = body as { error?: { message: string; code: string } | null };
  if (!response.ok || envelope?.error) {
    throw new ApiRequestError(
      envelope?.error?.message ?? `${response.status} ${response.statusText}`,
      response.status,
      envelope?.error?.code,
    );
  }
  return body as T;
}

export const api = {
  dailySummary: (date: string) =>
    request<Envelope<DailySummary>>('/data-operations/daily', { date }),

  chargersForDay: (
    date: string,
    options: {
      arrival_status?: string;
      completeness_status?: string;
      site?: string;
      charger?: string;
      page?: number;
      page_size?: number;
    } = {},
  ) =>
    request<PaginatedEnvelope<CoverageRow>>(
      `/data-operations/daily/${date}/chargers`,
      options,
    ),

  missingChargers: (date: string, page = 1, pageSize = 50) =>
    request<PaginatedEnvelope<MissingChargerRow>>(
      `/data-operations/daily/${date}/missing`,
      { page, page_size: pageSize },
    ),

  lateArrivals: (date: string, page = 1, pageSize = 50) =>
    request<PaginatedEnvelope<LateFileRow>>(`/data-operations/daily/${date}/late`, {
      page,
      page_size: pageSize,
    }),

  runs: (page = 1, pageSize = 20) =>
    request<PaginatedEnvelope<IngestionRun>>('/data-operations/runs', {
      page,
      page_size: pageSize,
    }),

  coverageHistory: (chargerId: string, from: string, to: string) =>
    request<Envelope<CoverageRow[]>>(
      `/chargers/${encodeURIComponent(chargerId)}/coverage`,
      { from, to },
    ),

  chargerDay: (chargerId: string, date: string) =>
    request<Envelope<ChargerDayDetail>>(
      `/chargers/${encodeURIComponent(chargerId)}/coverage/${date}`,
    ),

  chargerGaps: (chargerId: string, from?: string, to?: string) =>
    request<PaginatedEnvelope<GapRow>>(
      `/chargers/${encodeURIComponent(chargerId)}/gaps`,
      { from, to },
    ),
};
