/**
 * Upload UI primitives (Phase 1C.5 sections 34-45).
 *
 * Two things this UI must communicate honestly:
 *
 * **Upload is not processing.** A finished transfer means the bytes are safe, not
 * that the telemetry is usable. The two progress bars are separate for that reason
 * (sections 12, 30).
 *
 * **Backend status is authoritative.** The browser checks extension, emptiness and
 * size for fast feedback only; the server revalidates everything (section 36).
 */

import { useCallback, useRef, useState } from 'react';

import { count, timestamp } from '../lib/format';
import type {
  BatchFileRow,
  StagedFileResult,
  UploadBatchStatus,
  UploadCounts,
  UploadFileStatus,
} from '../lib/types';
import { Pill } from './status';

type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'neutral';

/** Human labels. Raw enums stay available in the title attribute (section 41). */
const BATCH_LABEL: Record<UploadBatchStatus, string> = {
  CREATED: 'Created',
  UPLOADING: 'Uploading',
  REGISTERED: 'Queued',
  PROCESSING: 'Processing',
  COMPLETED: 'Completed',
  COMPLETED_WITH_WARNINGS: 'Completed with warnings',
  FAILED: 'Failed',
};

const BATCH_TONE: Record<UploadBatchStatus, Tone> = {
  CREATED: 'neutral',
  UPLOADING: 'info',
  REGISTERED: 'info',
  PROCESSING: 'info',
  COMPLETED: 'ok',
  COMPLETED_WITH_WARNINGS: 'warn',
  FAILED: 'bad',
};

const FILE_LABEL: Record<UploadFileStatus, string> = {
  PENDING: 'Queued',
  REGISTERED: 'Accepted',
  DUPLICATE: 'Already uploaded',
  REJECTED: 'Rejected',
  FAILED: 'Failed',
};

const FILE_TONE: Record<UploadFileStatus, Tone> = {
  PENDING: 'neutral',
  REGISTERED: 'info',
  DUPLICATE: 'info',
  REJECTED: 'warn',
  FAILED: 'bad',
};

/** Telemetry-file lifecycle, in operator language (section 41). */
const TELEMETRY_LABEL: Record<string, string> = {
  DISCOVERED: 'Discovered',
  REGISTERED: 'Registered',
  LANDING: 'Storing',
  PROFILING: 'Profiling',
  SCHEMA_VALIDATION: 'Checking schema',
  QUALITY_VALIDATION: 'Checking quality',
  READY_FOR_NORMALIZATION: 'Ready for reconstruction',
  FRAME_RECONSTRUCTION: 'Reconstructing frames',
  FRAMES_RECONSTRUCTED: 'Ready',
  COMPLETED: 'Ready',
  PARTIAL: 'Partial',
  DUPLICATE: 'Already uploaded',
  QUARANTINED: 'Needs review',
  FAILED: 'Processing failed',
};

const TELEMETRY_TONE: Record<string, Tone> = {
  FRAMES_RECONSTRUCTED: 'ok',
  COMPLETED: 'ok',
  READY_FOR_NORMALIZATION: 'info',
  FRAME_RECONSTRUCTION: 'info',
  PARTIAL: 'warn',
  QUARANTINED: 'warn',
  DUPLICATE: 'info',
  FAILED: 'bad',
};

export function BatchStatusBadge({ status }: { status: UploadBatchStatus }) {
  return (
    <span className={`pill ${BATCH_TONE[status] ?? 'neutral'}`} title={status}>
      {BATCH_LABEL[status] ?? status}
    </span>
  );
}

export function FileStatusBadge({
  status,
  telemetryStatus,
}: {
  status: UploadFileStatus;
  telemetryStatus?: string | null;
}) {
  // Once a file is registered, the telemetry file's own state is the truthful
  // answer to "what happened to it".
  if (status === 'REGISTERED' && telemetryStatus) {
    return (
      <span
        className={`pill ${TELEMETRY_TONE[telemetryStatus] ?? 'neutral'}`}
        title={telemetryStatus}
      >
        {TELEMETRY_LABEL[telemetryStatus] ?? telemetryStatus}
      </span>
    );
  }
  return (
    <span className={`pill ${FILE_TONE[status] ?? 'neutral'}`} title={status}>
      {FILE_LABEL[status] ?? status}
    </span>
  );
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '-';
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const exponent = Math.min(
    units.length - 1,
    Math.floor(Math.log(bytes) / Math.log(1024)),
  );
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

/** Local pre-checks, mirroring the server's rules for fast feedback only. */
export interface LocalCheck {
  ok: boolean;
  reason?: string;
}

export function checkFileLocally(
  file: File,
  { allowedExtensions, maxBytes }: { allowedExtensions: string[]; maxBytes: number },
): LocalCheck {
  const dot = file.name.lastIndexOf('.');
  const extension = dot >= 0 ? file.name.slice(dot).toLowerCase() : '';
  if (!allowedExtensions.includes(extension)) {
    return { ok: false, reason: `${extension || 'no extension'} is not supported` };
  }
  if (file.size === 0) return { ok: false, reason: 'File is empty' };
  if (file.size > maxBytes) {
    return { ok: false, reason: `Larger than ${formatBytes(maxBytes)}` };
  }
  return { ok: true };
}

export function TelemetryDropzone({
  onFiles,
  disabled,
}: {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setDragging(false);
      if (disabled) return;
      onFiles(Array.from(event.dataTransfer.files));
    },
    [disabled, onFiles],
  );

  return (
    <div
      className={`dropzone${dragging ? ' dragging' : ''}`}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".csv"
        hidden
        onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []));
          // Reset so selecting the same file twice still fires onChange.
          event.target.value = '';
        }}
      />
      <p className="dz-title">Drop charger telemetry files here</p>
      <p className="dz-or">or</p>
      <button onClick={() => inputRef.current?.click()} disabled={disabled}>
        Browse files
      </button>
      <p className="dz-hint">Multiple files are supported</p>
    </div>
  );
}

export function SelectedFileList({
  files,
  checks,
  onRemove,
  disabled,
}: {
  files: File[];
  checks: Map<string, LocalCheck>;
  onRemove: (name: string) => void;
  disabled?: boolean;
}) {
  if (files.length === 0) return null;
  const total = files.reduce((sum, file) => sum + file.size, 0);
  const invalid = files.filter((file) => checks.get(file.name)?.ok === false).length;

  return (
    <section className="panel">
      <header>
        <h2>Selected files</h2>
        <span className="hint">
          {count(files.length)} files · {formatBytes(total)}
          {invalid > 0 ? ` · ${invalid} will be rejected` : ''}
        </span>
      </header>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Filename</th>
              <th style={{ textAlign: 'right' }}>Size</th>
              <th>Check</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {files.map((file) => {
              const check = checks.get(file.name);
              return (
                <tr key={file.name}>
                  <td>
                    <code>{file.name}</code>
                  </td>
                  <td className="num">{formatBytes(file.size)}</td>
                  <td>
                    {check?.ok === false ? (
                      <span title={check.reason}>
                        <Pill tone="warn">{check.reason}</Pill>
                      </span>
                    ) : (
                      <Pill tone="ok">Looks valid</Pill>
                    )}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <button onClick={() => onRemove(file.name)} disabled={disabled}>
                      Remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="callout">
        These checks are a quick local sanity pass only. The server revalidates every
        file, and it decides what is accepted.
      </div>
    </section>
  );
}

export function ProgressBar({
  label,
  percentage,
  note,
  tone,
}: {
  label: string;
  percentage: number;
  note?: string;
  tone?: Tone;
}) {
  const clamped = Math.max(0, Math.min(100, percentage));
  const colour =
    tone === 'ok' ? 'var(--ok)' : tone === 'warn' ? 'var(--warn)' : 'var(--info)';
  return (
    <div className="progress-row">
      <div className="progress-label">
        <span>{label}</span>
        <span className="num">{clamped.toFixed(0)}%</span>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-label={label}
        aria-valuenow={Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span style={{ width: `${clamped}%`, background: colour }} />
      </div>
      {note ? <div className="progress-note">{note}</div> : null}
    </div>
  );
}

export function UploadBatchSummary({ counts }: { counts: UploadCounts }) {
  const tiles: { label: string; value: number; tone?: Tone; note?: string }[] = [
    { label: 'Files', value: counts.total_files },
    { label: 'Completed', value: counts.completed, tone: 'ok' },
    { label: 'Processing', value: counts.processing, tone: 'info' },
    {
      label: 'Already uploaded',
      value: counts.duplicate,
      tone: counts.duplicate ? 'info' : undefined,
      note: 'not processed again',
    },
    {
      label: 'Needs review',
      value: counts.quarantined,
      tone: counts.quarantined ? 'warn' : undefined,
    },
    { label: 'Failed', value: counts.failed, tone: counts.failed ? 'bad' : undefined },
    {
      label: 'Rejected',
      value: counts.rejected,
      tone: counts.rejected ? 'warn' : undefined,
      note: 'never staged',
    },
  ];

  return (
    <div className="tiles">
      {tiles.map((tile) => (
        <div
          key={tile.label}
          className={`tile${tile.tone === 'ok' || tile.tone === 'warn' || tile.tone === 'bad' ? ` ${tile.tone}` : ''}`}
        >
          <div className="label">{tile.label}</div>
          <div className="value">{count(tile.value)}</div>
          {tile.note ? <div className="note">{tile.note}</div> : null}
        </div>
      ))}
    </div>
  );
}

export function StagedResultList({ staged }: { staged: StagedFileResult[] }) {
  const rejected = staged.filter((item) => item.status === 'REJECTED');
  if (rejected.length === 0) return null;
  return (
    <div className="callout" style={{ borderColor: 'var(--warn)' }}>
      <strong>{rejected.length} file(s) were not accepted:</strong>
      <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
        {rejected.map((item) => (
          <li key={item.original_filename}>
            <code>{item.original_filename}</code> — {item.reason}
          </li>
        ))}
      </ul>
      Everything else in this upload continued normally.
    </div>
  );
}

export function BatchFileTable({ rows }: { rows: BatchFileRow[] }) {
  if (rows.length === 0) {
    return <div className="empty">No files match the current filter.</div>;
  }
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>File</th>
            <th style={{ textAlign: 'right' }}>Size</th>
            <th>Telemetry date</th>
            <th style={{ textAlign: 'right' }}>Unique samples</th>
            <th>Status</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.original_filename}>
              <td>
                <code>{row.original_filename}</code>
              </td>
              <td className="num">{formatBytes(row.size_bytes)}</td>
              {/* Telemetry date, not upload date - and "-" when not yet known. */}
              <td className={row.business_date ? '' : 'dim'}>
                {row.business_date ?? '-'}
              </td>
              <td className="num">
                {row.unique_event_timestamp_count === null
                  ? '-'
                  : count(row.unique_event_timestamp_count)}
              </td>
              <td>
                <FileStatusBadge
                  status={row.status}
                  telemetryStatus={row.telemetry_status}
                />
              </td>
              <td style={{ whiteSpace: 'normal', maxWidth: 380 }} className="dim">
                {row.is_duplicate
                  ? 'This telemetry was already received and was not processed again.'
                  : (row.failure_reason ?? '')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function batchTimestamps(row: {
  created_at: string;
  processing_duration_seconds: number | null;
}): string {
  const created = timestamp(row.created_at);
  if (row.processing_duration_seconds === null) return created;
  return `${created} · processed in ${row.processing_duration_seconds.toFixed(1)}s`;
}
