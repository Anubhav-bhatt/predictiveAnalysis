/**
 * Upload UI tests (Phase 1C.5 sections 39-41, 45).
 *
 * These guard the two claims the UI makes that are easy to break silently:
 * unmeasured values render as "-" rather than 0, and a duplicate is presented as a
 * recognised re-upload rather than an error.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  BatchFileTable,
  BatchStatusBadge,
  FileStatusBadge,
  ProgressBar,
  SelectedFileList,
  StagedResultList,
  UploadBatchSummary,
  checkFileLocally,
  formatBytes,
} from '../components/uploads';
import type { BatchFileRow, UploadCounts } from '../lib/types';

const LIMITS = { allowedExtensions: ['.csv'], maxBytes: 1000 };

function file(name: string, size: number): File {
  const blob = new File([new Uint8Array(size)], name, { type: 'text/csv' });
  return blob;
}

function row(overrides: Partial<BatchFileRow> = {}): BatchFileRow {
  return {
    original_filename: 'HYD12.csv',
    size_bytes: 2048,
    status: 'REGISTERED',
    telemetry_file_id: 'f1',
    duplicate_of_file_id: null,
    failure_reason: null,
    staged_at: '2026-07-28T04:00:00Z',
    registered_at: '2026-07-28T04:00:01Z',
    telemetry_status: 'FRAMES_RECONSTRUCTED',
    charger_id: 'HYD12',
    business_date: '2026-07-27',
    row_count: 5600,
    unique_event_timestamp_count: 700,
    quality_score: 96.5,
    is_duplicate: false,
    ...overrides,
  };
}

function counts(overrides: Partial<UploadCounts> = {}): UploadCounts {
  return {
    total_files: 0,
    pending: 0,
    processing: 0,
    completed: 0,
    duplicate: 0,
    failed: 0,
    quarantined: 0,
    rejected: 0,
    progress_percentage: 0,
    ...overrides,
  };
}

describe('formatBytes', () => {
  it('renders "-" for an unknown size rather than 0 B', () => {
    expect(formatBytes(null)).toBe('-');
    expect(formatBytes(undefined)).toBe('-');
  });

  it('distinguishes a genuinely empty file from an unknown one', () => {
    expect(formatBytes(0)).toBe('0 B');
  });

  it('scales to the nearest unit', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(16_500_000)).toBe('15.7 MB');
    expect(formatBytes(5 * 1024 ** 3)).toBe('5.0 GB');
  });
});

describe('checkFileLocally', () => {
  it('accepts a plausible telemetry file', () => {
    expect(checkFileLocally(file('HYD12.csv', 100), LIMITS).ok).toBe(true);
  });

  it('rejects an unsupported extension, naming it', () => {
    const check = checkFileLocally(file('payload.exe', 100), LIMITS);
    expect(check.ok).toBe(false);
    expect(check.reason).toContain('.exe');
  });

  it('rejects a file with no extension at all', () => {
    expect(checkFileLocally(file('telemetry', 100), LIMITS).reason).toContain(
      'no extension',
    );
  });

  it('rejects an empty file', () => {
    expect(checkFileLocally(file('empty.csv', 0), LIMITS).reason).toBe('File is empty');
  });

  it('rejects a file above the server limit', () => {
    expect(checkFileLocally(file('big.csv', 2000), LIMITS).ok).toBe(false);
  });

  it('is case-insensitive about the extension', () => {
    expect(checkFileLocally(file('HYD12.CSV', 100), LIMITS).ok).toBe(true);
  });
});

describe('status labels', () => {
  it('states batch status in operator language, keeping the raw enum available', () => {
    render(<BatchStatusBadge status="COMPLETED_WITH_WARNINGS" />);
    const pill = screen.getByText('Completed with warnings');
    expect(pill).toHaveAttribute('title', 'COMPLETED_WITH_WARNINGS');
  });

  it('calls a queued batch "Queued", not "REGISTERED"', () => {
    render(<BatchStatusBadge status="REGISTERED" />);
    expect(screen.getByText('Queued')).toBeInTheDocument();
  });

  it('prefers the telemetry file state once the file is registered', () => {
    render(<FileStatusBadge status="REGISTERED" telemetryStatus="FRAMES_RECONSTRUCTED" />);
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('describes a duplicate as already uploaded rather than as a failure', () => {
    render(<FileStatusBadge status="DUPLICATE" />);
    const pill = screen.getByText('Already uploaded');
    expect(pill.className).not.toContain('bad');
  });

  it('renders quarantine as review, not as loss', () => {
    render(<FileStatusBadge status="REGISTERED" telemetryStatus="QUARANTINED" />);
    expect(screen.getByText('Needs review')).toBeInTheDocument();
  });
});

describe('BatchFileTable', () => {
  it('shows the telemetry date and measured sample count', () => {
    render(<BatchFileTable rows={[row()]} />);
    expect(screen.getByText('2026-07-27')).toBeInTheDocument();
    expect(screen.getByText('700')).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('renders "-" for a file that has not been processed yet', () => {
    render(
      <BatchFileTable
        rows={[
          row({
            status: 'PENDING',
            telemetry_file_id: null,
            telemetry_status: null,
            business_date: null,
            row_count: null,
            unique_event_timestamp_count: null,
            quality_score: null,
          }),
        ]}
      />,
    );
    // Two dashes: telemetry date and unique samples. Neither may render as 0.
    expect(screen.getAllByText('-')).toHaveLength(2);
    expect(screen.queryByText('0')).not.toBeInTheDocument();
    expect(screen.getByText('Queued')).toBeInTheDocument();
  });

  it('explains a duplicate in plain language', () => {
    render(<BatchFileTable rows={[row({ status: 'DUPLICATE', is_duplicate: true })]} />);
    expect(
      screen.getByText(/already received and was not processed again/i),
    ).toBeInTheDocument();
  });

  it('is empty-safe', () => {
    render(<BatchFileTable rows={[]} />);
    expect(screen.getByText(/No files match/i)).toBeInTheDocument();
  });
});

describe('UploadBatchSummary', () => {
  it('shows every outcome bucket, including zeros, so nothing looks hidden', () => {
    render(
      <UploadBatchSummary
        counts={counts({ total_files: 5, completed: 3, duplicate: 1, failed: 1 })}
      />,
    );
    expect(screen.getByText('Files')).toBeInTheDocument();
    expect(screen.getByText('Already uploaded')).toBeInTheDocument();
    expect(screen.getByText('Needs review')).toBeInTheDocument();
    expect(screen.getByText('Rejected')).toBeInTheDocument();
  });

  it('marks a duplicate count as not reprocessed rather than as lost', () => {
    render(<UploadBatchSummary counts={counts({ total_files: 2, duplicate: 2 })} />);
    expect(screen.getByText('not processed again')).toBeInTheDocument();
  });
});

describe('ProgressBar', () => {
  it('exposes progress to assistive technology', () => {
    render(<ProgressBar label="Processing" percentage={42.4} />);
    const bar = screen.getByRole('progressbar', { name: 'Processing' });
    expect(bar).toHaveAttribute('aria-valuenow', '42');
    expect(screen.getByText('42%')).toBeInTheDocument();
  });

  it('clamps out-of-range values instead of overflowing the track', () => {
    render(<ProgressBar label="Upload" percentage={140} />);
    expect(screen.getByRole('progressbar', { name: 'Upload' })).toHaveAttribute(
      'aria-valuenow',
      '100',
    );
  });
});

describe('SelectedFileList', () => {
  it('warns which selected files will be rejected before uploading', () => {
    const files = [file('good.csv', 100), file('bad.exe', 100)];
    const checks = new Map(
      files.map((item) => [item.name, checkFileLocally(item, LIMITS)]),
    );
    render(<SelectedFileList files={files} checks={checks} onRemove={() => {}} />);

    expect(screen.getByText(/1 will be rejected/)).toBeInTheDocument();
    expect(screen.getByText('Looks valid')).toBeInTheDocument();
    // And it is explicit that the server is the authority.
    expect(screen.getByText(/server revalidates every file/i)).toBeInTheDocument();
  });

  it('renders nothing when no files are selected', () => {
    const { container } = render(
      <SelectedFileList files={[]} checks={new Map()} onRemove={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('StagedResultList', () => {
  it('lists rejected files with their reasons and says the rest continued', () => {
    render(
      <StagedResultList
        staged={[
          { original_filename: 'good.csv', size_bytes: 10, status: 'PENDING', reason: null },
          {
            original_filename: 'bad.exe',
            size_bytes: 2,
            status: 'REJECTED',
            reason: 'Extension .exe is not permitted',
          },
        ]}
      />,
    );
    expect(screen.getByText(/Extension .exe is not permitted/)).toBeInTheDocument();
    expect(screen.getByText(/continued normally/i)).toBeInTheDocument();
  });

  it('stays silent when every file was accepted', () => {
    const { container } = render(
      <StagedResultList
        staged={[
          { original_filename: 'a.csv', size_bytes: 10, status: 'PENDING', reason: null },
        ]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
