import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { MissingChargersTable } from '../components/tables';
import { SummaryTiles } from '../components/DailySummaryPanel';
import type { DailySummary, MissingChargerRow } from '../lib/types';

function wrap(ui: React.ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

const summary: DailySummary = {
  business_date: '2026-08-10',
  expected: 5281,
  received: 5214,
  complete: 5168,
  partial: 29,
  severely_incomplete: 17,
  no_data: 67,
  late: 17,
  missing: 67,
  unexpected: 0,
  failed: 5,
  quarantined: 3,
  duplicate: 1,
  fleet_coverage_percentage: 98.4,
  average_coverage_percentage: 98.4,
  p50_coverage_percentage: 99.9,
  p95_coverage_percentage: 100,
  p95_largest_gap_seconds: 1800,
  fleet_delivery_rate: 98.73,
  fleet_complete_day_rate: 97.86,
  fleet_missing_rate: 1.27,
  fleet_partial_rate: 0.55,
  late_arrival_rate: 0.33,
  total_gap_count: 214,
  largest_gap_seconds: 21600,
  daily_rule_counts: { MISSING_CHARGER_DATA: 67 },
  stages: [],
};

describe('SummaryTiles', () => {
  it('renders the section 31 headline figures from the API', () => {
    wrap(<SummaryTiles summary={summary} />);

    expect(screen.getByText('5,281')).toBeInTheDocument(); // expected
    expect(screen.getByText('5,214')).toBeInTheDocument(); // received
    expect(screen.getByText('5,168')).toBeInTheDocument(); // complete
    expect(screen.getByText('29')).toBeInTheDocument(); // partial
    expect(screen.getByText('98.40%')).toBeInTheDocument(); // fleet coverage
  });

  it('shows both missing and late without conflating them', () => {
    wrap(<SummaryTiles summary={summary} />);
    expect(screen.getByText('Missing')).toBeInTheDocument();
    expect(screen.getByText('Late')).toBeInTheDocument();
  });
});

describe('MissingChargersTable', () => {
  const row: MissingChargerRow = {
    charger_id: 'HYD44',
    business_date: '2026-08-10',
    site_code: 'SITE-HYD-002',
    ocpp_id: 'HYD44',
    expected_since: null,
    last_successful_date: null,
    last_successful_coverage_percentage: null,
    previous_day_coverage_percentage: null,
    last_seen_at: null,
  };

  it('renders unavailable history as a dash rather than fabricating zeros', () => {
    wrap(<MissingChargersTable rows={[row]} date="2026-08-10" />);

    expect(screen.getByText('HYD44')).toBeInTheDocument();
    expect(screen.getByText('SITE-HYD-002')).toBeInTheDocument();
    // Four columns have no underlying data and must all read "-".
    expect(screen.getAllByText('-').length).toBeGreaterThanOrEqual(4);
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument();
  });

  it('renders prior history when the backend supplies it', () => {
    wrap(
      <MissingChargersTable
        rows={[
          {
            ...row,
            last_successful_date: '2026-08-09',
            last_successful_coverage_percentage: 99.7,
            previous_day_coverage_percentage: 99.7,
          },
        ]}
        date="2026-08-10"
      />,
    );
    expect(screen.getByText(/09 Aug 2026/)).toBeInTheDocument();
    expect(screen.getByText('99.7%')).toBeInTheDocument();
  });

  it('states plainly when nothing is missing', () => {
    wrap(<MissingChargersTable rows={[]} date="2026-08-10" />);
    expect(
      screen.getByText(/No expected charger is missing telemetry/),
    ).toBeInTheDocument();
  });
});
