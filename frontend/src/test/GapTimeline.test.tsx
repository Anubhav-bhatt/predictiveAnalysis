import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { GapTimeline } from '../components/GapTimeline';
import type { CoverageRow, GapRow } from '../lib/types';

const coverage: CoverageRow = {
  charger_id: 'HYD12',
  business_date: '2026-08-10',
  site_code: 'SITE-A',
  ocpp_id: 'HYD12',
  arrival_status: 'RECEIVED',
  completeness_status: 'PARTIAL',
  expected: true,
  coverage_percentage: '50.000',
  sample_coverage_percentage: '50.000',
  span_coverage_percentage: '99.000',
  gap_adjusted_coverage_percentage: '50.000',
  first_event_at: '2026-08-10T00:00:00Z',
  last_event_at: '2026-08-10T23:00:00Z',
  unique_timestamp_count: 360,
  expected_timestamp_count: 720,
  expected_sampling_interval_seconds: 120,
  observed_median_sampling_interval_seconds: '120.000',
  gap_count: 1,
  largest_gap_seconds: 43200,
  connector_count_detected: 2,
  expected_connector_count: 2,
  smr_count_detected: 4,
  expected_smr_count: 4,
  file_count: 1,
  duplicate_timestamp_count: 0,
  logical_collision_count: 0,
  overlapping_timestamp_count: 0,
  first_received_at: '2026-08-11T02:00:00Z',
  late_by_seconds: null,
  quality_score: '95.00',
  last_evaluated_at: '2026-08-11T03:00:00Z',
};

const gap: GapRow = {
  charger_id: 'HYD12',
  business_date: '2026-08-10',
  start_event_at: '2026-08-10T06:00:00Z',
  end_event_at: '2026-08-10T18:00:00Z',
  duration_seconds: 43200,
  duration_minutes: 720,
  expected_interval_seconds: 120,
  estimated_missing_samples: 359,
  severity: 'CRITICAL',
};

describe('GapTimeline', () => {
  it('draws a track and distinguishes gaps from leading/trailing absence', () => {
    const { container } = render(<GapTimeline coverage={coverage} gaps={[gap]} />);

    expect(container.querySelector('.timeline-track')).toBeInTheDocument();
    expect(container.querySelectorAll('.timeline-gap')).toHaveLength(1);
    // The legend names all three states explicitly, so colour is not the only cue.
    expect(screen.getByText('Telemetry present')).toBeInTheDocument();
    expect(screen.getByText(/Gap between samples/)).toBeInTheDocument();
    expect(screen.getByText(/Before first \/ after last sample/)).toBeInTheDocument();
  });

  it('labels the track for assistive technology', () => {
    render(<GapTimeline coverage={coverage} gaps={[gap]} />);
    expect(screen.getByRole('img', { name: /with 1 gap/ })).toBeInTheDocument();
  });

  it('draws no gap elements when the day is unbroken', () => {
    const { container } = render(
      <GapTimeline coverage={{ ...coverage, gap_count: 0 }} gaps={[]} />,
    );
    expect(container.querySelectorAll('.timeline-gap')).toHaveLength(0);
  });

  it('says so rather than drawing an empty track when there is no telemetry', () => {
    render(
      <GapTimeline
        coverage={{ ...coverage, first_event_at: null, last_event_at: null }}
        gaps={[]}
      />,
    );
    expect(screen.getByText(/no timeline to draw/)).toBeInTheDocument();
  });
});
