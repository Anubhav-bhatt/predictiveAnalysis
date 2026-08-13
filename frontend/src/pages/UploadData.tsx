/**
 * Upload Data (Phase 1C.5 sections 33-38, 42-45).
 *
 * The page is explicit that uploading is not processing. Once the transfer
 * finishes it stops claiming progress it cannot observe and points the operator at
 * the batch, where processing state actually lives.
 */

import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import {
  ProgressBar,
  SelectedFileList,
  StagedResultList,
  TelemetryDropzone,
  checkFileLocally,
  formatBytes,
  type LocalCheck,
} from '../components/uploads';
import { api } from '../lib/api';
import { count } from '../lib/format';
import { useAsync } from '../lib/useAsync';
import type { UploadCreated } from '../lib/types';

type Phase = 'idle' | 'uploading' | 'staged' | 'error';

export function UploadData() {
  const navigate = useNavigate();
  const limits = useAsync(() => api.uploadLimits(), []);

  const [files, setFiles] = useState<File[]>([]);
  const [phase, setPhase] = useState<Phase>('idle');
  const [transferred, setTransferred] = useState(0);
  const [result, setResult] = useState<UploadCreated | null>(null);
  const [error, setError] = useState<string | null>(null);

  const limit = limits.data?.data;
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);

  const checks = useMemo(() => {
    const map = new Map<string, LocalCheck>();
    if (!limit) return map;
    for (const file of files) {
      map.set(
        file.name,
        checkFileLocally(file, {
          allowedExtensions: limit.allowed_extensions,
          maxBytes: limit.max_file_size_bytes,
        }),
      );
    }
    return map;
  }, [files, limit]);

  const batchTooLarge = limit ? totalBytes > limit.max_batch_size_bytes : false;
  const tooManyFiles = limit ? files.length > limit.max_files_per_batch : false;
  const blocked = batchTooLarge || tooManyFiles;

  const addFiles = (incoming: File[]) => {
    setPhase('idle');
    setResult(null);
    setError(null);
    setFiles((current) => {
      // Same filename twice in one batch is almost always an accident; keep the
      // first and let the operator re-add deliberately if they meant it.
      const seen = new Set(current.map((file) => file.name));
      return [...current, ...incoming.filter((file) => !seen.has(file.name))];
    });
  };

  const submit = async () => {
    setPhase('uploading');
    setTransferred(0);
    setError(null);
    try {
      const response = await api.uploadFiles(files, (loaded) => setTransferred(loaded));
      if (!response.data) throw new Error('Upload returned no batch');
      setResult(response.data);
      setPhase('staged');
      setFiles([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Upload failed');
      setPhase('error');
    }
  };

  const uploadPercentage =
    totalBytes > 0 ? (transferred / totalBytes) * 100 : phase === 'staged' ? 100 : 0;

  return (
    <div className="app">
      <div className="masthead">
        <div>
          <h1>Upload Telemetry Data</h1>
          <div className="sub">
            Uploaded files go through exactly the same pipeline as automatically
            collected telemetry — same profiling, schema checks, quality scoring,
            coverage and frame reconstruction. Upload is only how the file arrives.
          </div>
        </div>
        <div className="controls">
          <Link className="btn-link" to="/data-operations/uploads">
            Upload history
          </Link>
        </div>
      </div>

      {limits.error ? (
        <div className="panel">
          <div className="error">Could not read upload limits: {limits.error}</div>
        </div>
      ) : null}

      {phase !== 'staged' ? (
        <section className="panel">
          <TelemetryDropzone onFiles={addFiles} disabled={phase === 'uploading'} />
          {limit ? (
            <div className="hint" style={{ marginTop: 10 }}>
              Accepted: {limit.allowed_extensions.join(', ')} · up to{' '}
              {formatBytes(limit.max_file_size_bytes)} per file ·{' '}
              {count(limit.max_files_per_batch)} files and{' '}
              {formatBytes(limit.max_batch_size_bytes)} per batch.
            </div>
          ) : null}
        </section>
      ) : null}

      {phase !== 'staged' ? (
        <SelectedFileList
          files={files}
          checks={checks}
          onRemove={(name) =>
            setFiles((current) => current.filter((file) => file.name !== name))
          }
          disabled={phase === 'uploading'}
        />
      ) : null}

      {blocked ? (
        <div className="panel">
          <div className="error">
            {tooManyFiles
              ? `This batch has ${count(files.length)} files, above the limit of ${count(
                  limit?.max_files_per_batch ?? 0,
                )}. Split it into smaller batches.`
              : `This batch is ${formatBytes(totalBytes)}, above the limit of ${formatBytes(
                  limit?.max_batch_size_bytes ?? 0,
                )}. Split it into smaller batches.`}
          </div>
        </div>
      ) : null}

      {files.length > 0 && phase !== 'staged' ? (
        <section className="panel">
          <div className="controls">
            <button
              className="primary"
              onClick={submit}
              disabled={phase === 'uploading' || blocked}
            >
              {phase === 'uploading'
                ? 'Uploading…'
                : `Upload ${count(files.length)} file(s) · ${formatBytes(totalBytes)}`}
            </button>
            <button onClick={() => setFiles([])} disabled={phase === 'uploading'}>
              Clear
            </button>
          </div>

          {phase === 'uploading' ? (
            <>
              <ProgressBar
                label="Transferring to server"
                percentage={uploadPercentage}
                note={`${formatBytes(transferred)} of ${formatBytes(totalBytes)} sent`}
              />
              <div className="callout">
                Keep this tab open until the transfer completes. Processing continues
                on the server afterwards and does not need the browser.
              </div>
            </>
          ) : null}
        </section>
      ) : null}

      {phase === 'error' && error ? (
        <div className="panel">
          <div className="error">{error}</div>
          <div className="hint">
            Nothing was processed. You can retry the same files — telemetry already
            received is recognised and is not stored twice.
          </div>
        </div>
      ) : null}

      {phase === 'staged' && result ? (
        <section className="panel">
          <header>
            <h2>Upload complete — processing queued</h2>
            <span className="hint">Batch {result.upload_batch_id.slice(0, 8)}</span>
          </header>

          <ProgressBar label="Transfer" percentage={100} tone="ok" note="All bytes received" />

          <p>
            {count(result.accepted_count)} file(s) accepted
            {result.rejected_count > 0
              ? `, ${count(result.rejected_count)} not accepted`
              : ''}
            . Processing runs in the background; the batch page shows how far it has
            got.
          </p>

          <StagedResultList staged={result.staged} />

          <div className="controls" style={{ marginTop: 12 }}>
            <button
              className="primary"
              onClick={() =>
                navigate(`/data-operations/uploads/${result.upload_batch_id}`)
              }
            >
              View processing progress
            </button>
            <button
              onClick={() => {
                setResult(null);
                setPhase('idle');
              }}
            >
              Upload more files
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
