/**
 * Response types mirroring the backend Pydantic models.
 *
 * Nullable fields are typed `| null` deliberately: the API returns null when a
 * value genuinely does not exist, and the UI must render that as "-" rather than
 * substituting a zero that was never measured.
 */

export type ArrivalStatus = 'EXPECTED' | 'RECEIVED' | 'LATE' | 'MISSING' | 'UNEXPECTED';

export type CompletenessStatus =
  | 'COMPLETE'
  | 'PARTIAL'
  | 'SEVERELY_INCOMPLETE'
  | 'NO_DATA'
  | 'UNKNOWN';

export type GapSeverity = 'MINOR' | 'MODERATE' | 'MAJOR' | 'CRITICAL';

export type QualitySeverity = 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown> | null;
}

export interface Envelope<T> {
  data: T | null;
  meta: Record<string, unknown>;
  error: ApiError | null;
}

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface PaginatedEnvelope<T> {
  data: T[];
  meta: PageMeta;
  error: ApiError | null;
}

export interface ProcessingStage {
  stage: string;
  status: string;
  detail: string | null;
  count: number | null;
}

export interface DailySummary {
  business_date: string;

  expected: number;
  received: number;
  complete: number;
  partial: number;
  severely_incomplete: number;
  no_data: number;
  late: number;
  missing: number;
  unexpected: number;

  failed: number;
  quarantined: number;
  duplicate: number;

  fleet_coverage_percentage: number;
  average_coverage_percentage: number;
  p50_coverage_percentage: number | null;
  p95_coverage_percentage: number | null;
  p95_largest_gap_seconds: number | null;

  fleet_delivery_rate: number;
  fleet_complete_day_rate: number;
  fleet_missing_rate: number;
  fleet_partial_rate: number;
  late_arrival_rate: number;

  total_gap_count: number;
  largest_gap_seconds: number;

  daily_rule_counts: Record<string, number>;
  stages: ProcessingStage[];
}

export interface CoverageRow {
  charger_id: string;
  business_date: string;
  site_code: string | null;
  ocpp_id: string | null;

  arrival_status: ArrivalStatus;
  completeness_status: CompletenessStatus;
  expected: boolean;

  coverage_percentage: string | null;
  sample_coverage_percentage: string | null;
  span_coverage_percentage: string | null;
  gap_adjusted_coverage_percentage: string | null;

  first_event_at: string | null;
  last_event_at: string | null;
  unique_timestamp_count: number;
  expected_timestamp_count: number | null;

  expected_sampling_interval_seconds: number | null;
  observed_median_sampling_interval_seconds: string | null;

  gap_count: number;
  largest_gap_seconds: number | null;

  connector_count_detected: number | null;
  expected_connector_count: number | null;
  smr_count_detected: number | null;
  expected_smr_count: number | null;

  file_count: number;
  duplicate_timestamp_count: number;
  logical_collision_count: number;
  overlapping_timestamp_count: number;

  first_received_at: string | null;
  late_by_seconds: number | null;
  quality_score: string | null;
  last_evaluated_at: string | null;
}

export interface MissingChargerRow {
  charger_id: string;
  business_date: string;
  site_code: string | null;
  ocpp_id: string | null;
  expected_since: string | null;
  last_successful_date: string | null;
  last_successful_coverage_percentage: number | null;
  previous_day_coverage_percentage: number | null;
  last_seen_at: string | null;
}

export interface LateFileRow {
  charger_id: string;
  business_date: string;
  site_code: string | null;
  received_at: string | null;
  late_by_seconds: number | null;
  coverage_percentage: string | null;
  completeness_status: CompletenessStatus;
  arrival_status: ArrivalStatus;
}

export interface GapRow {
  charger_id: string;
  business_date: string;
  start_event_at: string;
  end_event_at: string;
  duration_seconds: number;
  duration_minutes: number;
  expected_interval_seconds: number | null;
  estimated_missing_samples: number | null;
  severity: GapSeverity;
}

export interface ChargerDayFinding {
  rule_code: string;
  severity: QualitySeverity;
  message: string;
  occurrence_count: number;
  detected_at: string;
}

export interface ContributingFile {
  telemetry_file_id: string;
  original_filename: string;
  status: string;
  received_at: string;
  business_date: string | null;
  filename_date: string | null;
  file_date_span: string | null;
  row_count_for_date: number;
  unique_timestamp_count_for_date: number;
  first_event_at: string | null;
  last_event_at: string | null;
  quality_score: string | null;
  filename_date_matches_event_date: boolean | null;
}

export interface ChargerDayDetail {
  coverage: CoverageRow;
  gaps: GapRow[];
  findings: ChargerDayFinding[];
  files: ContributingFile[];
}

export interface IngestionRun {
  id: string;
  business_date: string | null;
  source_type: string;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;

  files_discovered: number;
  files_registered: number;
  files_ready: number;
  files_partial: number;
  files_duplicate: number;
  files_quarantined: number;
  files_failed: number;

  expected_charger_count: number | null;
  received_charger_count: number | null;
  missing_charger_count: number | null;
  late_charger_count: number | null;
  fleet_coverage_percentage: string | null;
}
