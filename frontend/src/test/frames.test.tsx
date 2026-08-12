import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  ClassificationPill,
  CollisionExplorer,
  FrameDiffViewer,
  FrameStatusPill,
  FrameTable,
  ReconstructionPanel,
} from '../components/frames';
import type {
  CollisionGroup,
  FrameDiff,
  FrameSummaryRow,
  ReconstructionSummary,
} from '../lib/types';

const summary: ReconstructionSummary = {
  telemetry_file_id: 'f-1',
  original_filename: 'HYD12_28-07-2026.csv',
  reconstruction_version: 'frame-reconstruction-v1',
  raw_rows: 5822,
  unique_timestamps: 720,
  expected_positions_per_frame: 8,
  frames_reconstructed: 733,
  canonical_frames: 724,
  complete_frames: 727,
  partial_frames: 0,
  severely_incomplete_frames: 6,
  malformed_frames: 0,
  ambiguous_frames: 0,
  full_replays: 3,
  partial_replays: 6,
  same_timestamp_distinct_frames: 4,
  collision_timestamps: 3,
  unassigned_rows: 0,
  frame_completeness_percentage: 99.18,
  replay_rate: 1.23,
  rows_per_unique_timestamp: 8.086,
};

function frame(overrides: Partial<FrameSummaryRow> = {}): FrameSummaryRow {
  return {
    id: 'frame-1',
    charger_id: 'D82510560390014',
    event_time: '2026-07-27T15:11:37Z',
    business_date: '2026-07-27',
    frame_sequence: 0,
    frame_status: 'COMPLETE',
    duplicate_classification: 'UNIQUE',
    frame_fingerprint: 'abcdef0123456789'.repeat(4),
    fingerprint_short: 'abcdef012345',
    replay_of_frame_id: null,
    expected_position_count: 8,
    observed_position_count: 8,
    missing_position_count: 0,
    unexpected_position_count: 0,
    completeness_percentage: '100.000',
    source_order_min: 0,
    source_order_max: 7,
    reconstruction_version: 'frame-reconstruction-v1',
    is_canonical: true,
    ...overrides,
  };
}

describe('ReconstructionPanel', () => {
  it('reports the measured frame counts from the API', () => {
    render(<ReconstructionPanel summary={summary} />);

    expect(screen.getByText('5,822')).toBeInTheDocument(); // raw rows
    expect(screen.getByText('720')).toBeInTheDocument(); // unique timestamps
    expect(screen.getByText('733')).toBeInTheDocument(); // frames
    expect(screen.getByText('724')).toBeInTheDocument(); // canonical
  });

  it('makes the raw-rows vs frames distinction explicit', () => {
    render(<ReconstructionPanel summary={summary} />);
    expect(screen.getByText(/8.086x rows per timestamp/)).toBeInTheDocument();
    expect(
      screen.getByText(/Raw rows and frames are different grains/),
    ).toBeInTheDocument();
    expect(screen.getByText(/classified here, never deleted/)).toBeInTheDocument();
  });

  it('labels frame completeness as a data measure, not health', () => {
    render(<ReconstructionPanel summary={summary} />);
    expect(screen.getByText('data measure, not health')).toBeInTheDocument();
  });
});

describe('status pills', () => {
  it('abbreviates long labels but keeps the full value in the title', () => {
    const { container } = render(<FrameStatusPill status="SEVERELY_INCOMPLETE" />);
    expect(screen.getByText('SEVERE')).toBeInTheDocument();
    expect(container.querySelector('[title="SEVERELY_INCOMPLETE"]')).toBeInTheDocument();
  });

  it('shows a distinct frame as a real observation, not a duplicate', () => {
    const { container } = render(
      <ClassificationPill classification="SAME_TIMESTAMP_DISTINCT_FRAME" />,
    );
    expect(screen.getByText('DISTINCT')).toBeInTheDocument();
    // Toned as ok: it is genuine telemetry, unlike a replay.
    expect(container.querySelector('.pill.ok')).toBeInTheDocument();
  });

  it('tones a full replay as informational', () => {
    const { container } = render(<ClassificationPill classification="FULL_FRAME_REPLAY" />);
    expect(screen.getByText('FULL REPLAY')).toBeInTheDocument();
    expect(container.querySelector('.pill.info')).toBeInTheDocument();
  });
});

describe('FrameTable', () => {
  it('renders sequence, positions and a short fingerprint', () => {
    render(<FrameTable frames={[frame(), frame({ id: 'f2', frame_sequence: 1 })]} />);
    expect(screen.getAllByText('8 / 8')).toHaveLength(2);
    expect(screen.getAllByText('abcdef012345')).toHaveLength(2);
  });

  it('states plainly when nothing matches', () => {
    render(<FrameTable frames={[]} />);
    expect(screen.getByText(/No frames match the current filters/)).toBeInTheDocument();
  });
});

describe('CollisionExplorer', () => {
  const group: CollisionGroup = {
    charger_id: 'D82510560390014',
    event_time: '2026-07-27T15:11:37Z',
    business_date: '2026-07-27',
    frame_count: 2,
    canonical_count: 2,
    frames: [
      frame({ id: 'a', frame_sequence: 0 }),
      frame({
        id: 'b',
        frame_sequence: 1,
        duplicate_classification: 'SAME_TIMESTAMP_DISTINCT_FRAME',
      }),
    ],
  };

  it('shows both frames of a collision and says they are kept', () => {
    render(<CollisionExplorer groups={[group]} />);
    expect(screen.getByText(/2 frames · 2 canonical/)).toBeInTheDocument();
    expect(screen.getByText(/kept, not merged/)).toBeInTheDocument();
    expect(screen.getByText('DISTINCT')).toBeInTheDocument();
  });

  it('reports honestly when there are no collisions', () => {
    render(<CollisionExplorer groups={[]} />);
    expect(
      screen.getByText(/No event timestamp on this date carries more than one/),
    ).toBeInTheDocument();
  });
});

describe('FrameDiffViewer', () => {
  const diff: FrameDiff = {
    left: frame({ id: 'a', frame_sequence: 0 }),
    right: frame({
      id: 'b',
      frame_sequence: 1,
      duplicate_classification: 'SAME_TIMESTAMP_DISTINCT_FRAME',
    }),
    same_event_time: true,
    identical_payload: false,
    differing_positions: ['C1/S1', 'C1/S2'],
    matching_positions: ['C2/S1'],
    only_in_left: [],
    only_in_right: [],
    differing_position_count: 2,
    positions: [
      {
        logical_position: 'C1/S1',
        left_row_fingerprint: 'aaaaaaaaaaaa1111',
        right_row_fingerprint: 'bbbbbbbbbbbb2222',
        differs: true,
      },
      {
        logical_position: 'C2/S1',
        left_row_fingerprint: 'cccccccccccc3333',
        right_row_fingerprint: 'cccccccccccc3333',
        differs: false,
      },
    ],
  };

  it('reports which positions changed without exposing telemetry values', () => {
    render(<FrameDiffViewer diff={diff} />);
    expect(screen.getByText(/2 logical position\(s\) differ/)).toBeInTheDocument();
    expect(screen.getByText('C1/S1')).toBeInTheDocument();
    expect(screen.getByText('CHANGED')).toBeInTheDocument();
    expect(screen.getByText('same')).toBeInTheDocument();
  });

  it('explains that an identical payload means a replay', () => {
    render(
      <FrameDiffViewer
        diff={{ ...diff, identical_payload: true, differing_positions: [] }}
      />,
    );
    expect(screen.getByText(/adds no observation/)).toBeInTheDocument();
  });
});
