/**
 * The single boundary to the backend.
 *
 * Every figure the UI shows comes from here. Nothing is computed client-side: a
 * percentage recalculated in the browser could disagree with the same percentage
 * in the daily report, and there would be no way to tell which one was wrong.
 */

import type {
  BatchFileRow,
  ChargerDayDetail,
  CollisionGroup,
  CoverageRow,
  DailySummary,
  Envelope,
  FrameDetail,
  FrameDiff,
  FrameSummaryRow,
  GapRow,
  IngestionRun,
  LateFileRow,
  MissingChargerRow,
  PaginatedEnvelope,
  ReconstructionSummary,
  UploadBatchDetail,
  UploadBatchRow,
  UploadCreated,
  UploadLimits,
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

  // --- Phase 1D: frame reconstruction diagnostics -------------------------

  fileReconstruction: (fileId: string) =>
    request<Envelope<ReconstructionSummary>>(
      `/ingestion/files/${encodeURIComponent(fileId)}/reconstruction`,
    ),

  chargerFrames: (
    chargerId: string,
    options: {
      from?: string;
      to?: string;
      frame_status?: string;
      duplicate_classification?: string;
      canonical_only?: string;
      page?: number;
      page_size?: number;
    } = {},
  ) =>
    request<PaginatedEnvelope<FrameSummaryRow>>(
      `/chargers/${encodeURIComponent(chargerId)}/frames`,
      options,
    ),

  chargerCollisions: (chargerId: string, date: string) =>
    request<Envelope<CollisionGroup[]>>(
      `/chargers/${encodeURIComponent(chargerId)}/frames/collisions`,
      { date },
    ),

  frame: (frameId: string) =>
    request<Envelope<FrameDetail>>(`/frames/${encodeURIComponent(frameId)}`),

  frameDiff: (frameId: string, otherFrameId: string) =>
    request<Envelope<FrameDiff>>(
      `/frames/${encodeURIComponent(frameId)}/diff/${encodeURIComponent(otherFrameId)}`,
    ),

  // --- Phase 1C.5: bulk manual upload -------------------------------------

  /**
   * Upload telemetry files as one batch.
   *
   * Uses XMLHttpRequest rather than fetch purely for `onprogress`: an operator
   * uploading a multi-gigabyte backfill needs to see transfer progress, and fetch
   * cannot report it. The response only means the bytes are staged - processing
   * happens in the worker, which is why the caller then polls the batch.
   */
  uploadFiles: (
    files: File[],
    onProgress?: (transferred: number, total: number) => void,
  ): Promise<Envelope<UploadCreated>> =>
    new Promise((resolve, reject) => {
      const form = new FormData();
      for (const file of files) form.append('files', file, file.name);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE}/ingestion/uploads`);
      xhr.setRequestHeader('Accept', 'application/json');

      if (onProgress) {
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) onProgress(event.loaded, event.total);
        };
      }

      xhr.onload = () => {
        let body: unknown;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          reject(new ApiRequestError('Upload response was not JSON', xhr.status));
          return;
        }
        const envelope = body as Envelope<UploadCreated> & {
          error?: { message: string; code: string } | null;
        };
        if (xhr.status >= 400 || envelope.error) {
          reject(
            new ApiRequestError(
              envelope.error?.message ?? `Upload failed (${xhr.status})`,
              xhr.status,
              envelope.error?.code,
            ),
          );
          return;
        }
        resolve(envelope);
      };
      xhr.onerror = () => reject(new ApiRequestError('Upload failed: network error', 0));
      xhr.onabort = () => reject(new ApiRequestError('Upload cancelled', 0));

      xhr.send(form);
    }),

  uploadLimits: () => request<Envelope<UploadLimits>>('/ingestion/uploads/limits'),

  uploadBatches: (page = 1, pageSize = 25) =>
    request<PaginatedEnvelope<UploadBatchRow>>('/ingestion/uploads', {
      page,
      page_size: pageSize,
    }),

  uploadBatch: (batchId: string) =>
    request<Envelope<UploadBatchDetail>>(
      `/ingestion/uploads/${encodeURIComponent(batchId)}`,
    ),

  uploadBatchFiles: (
    batchId: string,
    options: { status?: string; page?: number; page_size?: number } = {},
  ) =>
    request<PaginatedEnvelope<BatchFileRow>>(
      `/ingestion/uploads/${encodeURIComponent(batchId)}/files`,
      options,
    ),
};
