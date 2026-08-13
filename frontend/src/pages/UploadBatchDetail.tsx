/**
 * Upload Batch Details (Phase 1C.5 sections 12, 30, 39-41).
 *
 * The one thing this page must not blur: **transfer finished ≠ telemetry usable.**
 * The transfer bar is complete for every batch that exists at all, so it is shown
 * as history; the processing bar is the live one, and it is driven entirely by
 * backend-derived counts.
 *
 * Polling stops as soon as the batch reaches a terminal status. A console that keeps
 * hammering a finished batch is how a browser tab quietly becomes load.
 */

import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import {
  BatchFileTable,
  BatchStatusBadge,
  ProgressBar,
  UploadBatchSummary,
  formatBytes,
} from '../components/uploads';
import { api } from '../lib/api';
import { EMPTY, count, timestamp } from '../lib/format';
import { useAsync } from '../lib/useAsync';
import type { UploadBatchStatus, UploadFileStatus } from '../lib/types';

const POLL_MS = 3000;

const TERMINAL: UploadBatchStatus[] = [
  'COMPLETED',
  'COMPLETED_WITH_WARNINGS',
  'FAILED',
];

type Filter = 'all' | UploadFileStatus;

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All files' },
  { key: 'REGISTERED', label: 'Accepted' },
  { key: 'DUPLICATE', label: 'Already uploaded' },
  { key: 'REJECTED', label: 'Rejected' },
  { key: 'FAILED', label: 'Failed' },
  { key: 'PENDING', label: 'Queued' },
];

export function UploadBatchDetail() {
  const { batchId = '' } = useParams();
  const [filter, setFilter] = useState<Filter>('all');
  const [tick, setTick] = useState(0);

  const detail = useAsync(() => api.uploadBatch(batchId), [batchId, tick]);
  const files = useAsync(
    () =>
      api.uploadBatchFiles(batchId, {
        status: filter === 'all' ? undefined : filter,
        page_size: 200,
      }),
    [batchId, filter, tick],
  );

  const batch = detail.data?.data?.batch;
  const counts = detail.data?.data?.counts;
  const settled = batch ? TERMINAL.includes(batch.status) : false;

  // Poll only while work is outstanding.
  useEffect(() => {
    if (settled || detail.error) return;
    const timer = window.setInterval(() => setTick((value) => value + 1), POLL_MS);
    return () => window.clearInterval(timer);
  }, [settled, detail.error]);

  return (
    <div className="app">
      <div className="masthead">
        <div>
          <h1>Upload Batch</h1>
          <div className="sub">
            <code>{batchId}</code>
          </div>
        </div>
        <div className="controls">
          <Link className="btn-link" to="/data-operations/uploads">
            All uploads
          </Link>
          <Link className="btn-link" to="/data-operations/upload">
            Upload more
          </Link>
          <button onClick={() => setTick((value) => value + 1)}>Reload</button>
        </div>
      </div>

      {detail.error ? (
        <div className="panel">
          <div className="error">{detail.error}</div>
        </div>
      ) : null}

      {detail.loading && !batch ? (
        <div className="panel">
          <div className="loading">Loading batch…</div>
        </div>
      ) : null}

      {batch && counts ? (
        <>
          <section className="panel">
            <header>
              <h2>Progress</h2>
              <BatchStatusBadge status={batch.status} />
            </header>

            {/* Two bars, never one: bytes arriving and telemetry becoming usable
                are different questions with different answers. */}
            <ProgressBar
              label="Upload (transfer to server)"
              percentage={100}
              tone="ok"
              note={
                batch.upload_completed_at
                  ? `Completed ${timestamp(batch.upload_completed_at)} · ${formatBytes(
                      batch.total_bytes,
                    )} across ${count(batch.file_count)} file(s)`
                  : `${formatBytes(batch.total_bytes)} received`
              }
            />
            <ProgressBar
              label="Processing (profiling, quality, coverage, frames)"
              percentage={counts.progress_percentage}
              tone={
                batch.status === 'FAILED'
                  ? 'warn'
                  : batch.status === 'COMPLETED_WITH_WARNINGS'
                    ? 'warn'
                    : settled
                      ? 'ok'
                      : 'info'
              }
              note={
                settled
                  ? batch.processing_completed_at
                    ? `Finished ${timestamp(batch.processing_completed_at)}`
                    : 'Finished'
                  : counts.pending + counts.processing > 0
                    ? `${count(counts.pending + counts.processing)} file(s) still to go — this page refreshes itself`
                    : 'Waiting for the ingestion worker to pick this batch up'
              }
            />

            {!settled ? (
              <div className="callout">
                You can safely leave this page. Processing runs on the server and does
                not depend on the browser staying open.
              </div>
            ) : null}
          </section>

          <section className="panel">
            <header>
              <h2>Outcome</h2>
              <span className="hint">Derived from the files, not stored counters</span>
            </header>
            <UploadBatchSummary counts={counts} />
            <div className="kv">
              <div>
                <span className="k">Uploaded at</span>
                <span className="v">{timestamp(batch.created_at)}</span>
              </div>
              <div>
                <span className="k">Processing started</span>
                <span className="v">{timestamp(batch.processing_started_at)}</span>
              </div>
              <div>
                <span className="k">Processing finished</span>
                <span className="v">{timestamp(batch.processing_completed_at)}</span>
              </div>
              <div>
                <span className="k">Duration</span>
                <span className="v">
                  {batch.processing_duration_seconds === null
                    ? EMPTY
                    : `${batch.processing_duration_seconds.toFixed(1)}s`}
                </span>
              </div>
            </div>
            {counts.duplicate > 0 ? (
              <div className="callout">
                {count(counts.duplicate)} file(s) contained telemetry the platform had
                already received. They were recognised and not stored or processed a
                second time — nothing was lost.
              </div>
            ) : null}
          </section>

          <section className="panel">
            <header>
              <h2>Files</h2>
              <span className="hint">
                {files.data ? `${count(files.data.meta.total)} shown` : ''}
              </span>
            </header>
            <div className="tabs">
              {FILTERS.map((entry) => (
                <button
                  key={entry.key}
                  className={filter === entry.key ? 'active' : ''}
                  onClick={() => setFilter(entry.key)}
                >
                  {entry.label}
                </button>
              ))}
            </div>
            {files.error ? (
              <div className="error">{files.error}</div>
            ) : files.data ? (
              <BatchFileTable rows={files.data.data} />
            ) : (
              <div className="loading">Loading files…</div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
