/**
 * Upload History (Phase 1C.5 sections 39, 46).
 *
 * One row per batch, newest first, with the counts the backend derived. Nothing is
 * tallied in the browser — a total computed here could disagree with the same total
 * on the batch page.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';

import { BatchStatusBadge, formatBytes } from '../components/uploads';
import { api } from '../lib/api';
import { EMPTY, count, timestamp } from '../lib/format';
import { useAsync } from '../lib/useAsync';

const PAGE_SIZE = 25;

export function UploadHistory() {
  const [page, setPage] = useState(1);
  const batches = useAsync(() => api.uploadBatches(page, PAGE_SIZE), [page]);

  const rows = batches.data?.data ?? [];
  const meta = batches.data?.meta;

  return (
    <div className="app">
      <div className="masthead">
        <div>
          <h1>Upload History</h1>
          <div className="sub">
            Every manual upload batch, newest first. Counts are derived from the files
            themselves each time they are read.
          </div>
        </div>
        <div className="controls">
          <Link className="btn-link" to="/data-operations/upload">
            Upload data
          </Link>
          <button onClick={() => batches.reload()}>Reload</button>
        </div>
      </div>

      {batches.error ? (
        <div className="panel">
          <div className="error">{batches.error}</div>
        </div>
      ) : null}

      <section className="panel">
        <header>
          <h2>Batches</h2>
          {meta ? (
            <span className="hint">
              {count(meta.total)} batch(es) · page {meta.page} of{' '}
              {Math.max(meta.total_pages, 1)}
            </span>
          ) : null}
        </header>

        {batches.loading && rows.length === 0 ? (
          <div className="loading">Loading upload history…</div>
        ) : rows.length === 0 ? (
          <div className="empty">
            No uploads yet. <Link to="/data-operations/upload">Upload telemetry files</Link>{' '}
            to get started.
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Uploaded</th>
                  <th>Source</th>
                  <th style={{ textAlign: 'right' }}>Files</th>
                  <th style={{ textAlign: 'right' }}>Size</th>
                  <th>Outcome</th>
                  <th>Status</th>
                  <th style={{ textAlign: 'right' }}>Processing time</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const counts = row.counts;
                  return (
                    <tr key={row.id}>
                      <td>{timestamp(row.created_at)}</td>
                      <td title={row.source_type}>
                        {row.source_type === 'MANUAL_UPLOAD' ? 'Manual upload' : row.source_type}
                      </td>
                      <td className="num">{count(row.file_count)}</td>
                      <td className="num">{formatBytes(row.total_bytes)}</td>
                      <td className="dim" style={{ whiteSpace: 'normal' }}>
                        {counts ? summarise(counts) : EMPTY}
                      </td>
                      <td>
                        <BatchStatusBadge status={row.status} />
                      </td>
                      {/* Null until processing has actually finished - never 0. */}
                      <td className="num">
                        {row.processing_duration_seconds === null
                          ? EMPTY
                          : `${row.processing_duration_seconds.toFixed(1)}s`}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <Link to={`/data-operations/uploads/${row.id}`}>Details</Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {meta && meta.total_pages > 1 ? (
          <div className="controls" style={{ marginTop: 12 }}>
            <button onClick={() => setPage((value) => value - 1)} disabled={meta.page <= 1}>
              Previous
            </button>
            <button
              onClick={() => setPage((value) => value + 1)}
              disabled={meta.page >= meta.total_pages}
            >
              Next
            </button>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function summarise(counts: {
  completed: number;
  processing: number;
  pending: number;
  duplicate: number;
  quarantined: number;
  failed: number;
  rejected: number;
}): string {
  const parts: string[] = [];
  if (counts.completed) parts.push(`${counts.completed} ready`);
  if (counts.processing) parts.push(`${counts.processing} processing`);
  if (counts.pending) parts.push(`${counts.pending} queued`);
  if (counts.duplicate) parts.push(`${counts.duplicate} already uploaded`);
  if (counts.quarantined) parts.push(`${counts.quarantined} needs review`);
  if (counts.failed) parts.push(`${counts.failed} failed`);
  if (counts.rejected) parts.push(`${counts.rejected} rejected`);
  return parts.length > 0 ? parts.join(' · ') : EMPTY;
}
