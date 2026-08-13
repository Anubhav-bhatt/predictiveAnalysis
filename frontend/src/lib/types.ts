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

// --- Phase 1D: source frame reconstruction ---------------------------------

export type FrameStatus =
  | 'COMPLETE'
  | 'PARTIAL'
  | 'SEVERELY_INCOMPLETE'
  | 'MALFORMED'
  | 'AMBIGUOUS';

export type DuplicateClassification =
  | 'UNIQUE'
  | 'EXACT_ROW_DUPLICATE'
  | 'FULL_FRAME_REPLAY'
  | 'PARTIAL_FRAME_REPLAY'
  | 'SAME_TIMESTAMP_DISTINCT_FRAME'
  | 'AMBIGUOUS';

export interface ReconstructionSummary {
  telemetry_file_id: string;
  original_filename: string;
  reconstruction_version: string | null;

  raw_rows: number | null;
  unique_timestamps: number;
  expected_positions_per_frame: number;

  frames_reconstructed: number;
  canonical_frames: number;
  complete_frames: number;
  partial_frames: number;
  severely_incomplete_frames: number;
  malformed_frames: number;
  ambiguous_frames: number;

  full_replays: number;
  partial_replays: number;
  same_timestamp_distinct_frames: number;
  collision_timestamps: number;
  unassigned_rows: number;

  frame_completeness_percentage: number;
  replay_rate: number;
  rows_per_unique_timestamp: number | null;
}

export interface FrameSummaryRow {
  id: string;
  charger_id: string;
  event_time: string;
  business_date: string;
  frame_sequence: number;

  frame_status: FrameStatus;
  duplicate_classification: DuplicateClassification;
  frame_fingerprint: string;
  fingerprint_short: string;
  replay_of_frame_id: string | null;

  expected_position_count: number;
  observed_position_count: number;
  missing_position_count: number;
  unexpected_position_count: number;
  completeness_percentage: string | null;

  source_order_min: number | null;
  source_order_max: number | null;
  reconstruction_version: string;
  is_canonical: boolean;
}

export interface FrameSourceRef {
  telemetry_file_id: string;
  original_filename: string | null;
  status: string | null;
  received_at: string | null;
  first_source_row: number;
  last_source_row: number;
  row_count: number;
  source_occurrence: number;
  is_primary_source: boolean;
}

export interface FrameRowRef {
  telemetry_file_id: string;
  source_row_number: number;
  connector_id: string | null;
  smr_id: string | null;
  logical_position: string | null;
  occurrence_index: number;
  row_fingerprint: string;
  unassigned: boolean;
}

export interface FrameDetail {
  frame: FrameSummaryRow;
  missing_positions: string[];
  unexpected_positions: string[];
  observed_positions: string[];
  issues: string[];
  sources: FrameSourceRef[];
  rows: FrameRowRef[];
  replays: FrameSummaryRow[];
  siblings: FrameSummaryRow[];
  detail: Record<string, unknown>;
  replay_count: number;
}

export interface CollisionGroup {
  charger_id: string;
  event_time: string;
  business_date: string;
  frame_count: number;
  canonical_count: number;
  frames: FrameSummaryRow[];
}

export interface FramePositionDifference {
  logical_position: string;
  left_row_fingerprint: string | null;
  right_row_fingerprint: string | null;
  differs: boolean;
}

export interface FrameDiff {
  left: FrameSummaryRow;
  right: FrameSummaryRow;
  same_event_time: boolean;
  identical_payload: boolean;
  differing_positions: string[];
  matching_positions: string[];
  only_in_left: string[];
  only_in_right: string[];
  positions: FramePositionDifference[];
  differing_position_count: number;
}

// --- Phase 1C.5: bulk manual upload ----------------------------------------

export type UploadBatchStatus =
  | 'CREATED'
  | 'UPLOADING'
  | 'REGISTERED'
  | 'PROCESSING'
  | 'COMPLETED'
  | 'COMPLETED_WITH_WARNINGS'
  | 'FAILED';

export type UploadFileStatus =
  | 'PENDING'
  | 'REGISTERED'
  | 'DUPLICATE'
  | 'REJECTED'
  | 'FAILED';

export interface UploadCounts {
  total_files: number;
  pending: number;
  processing: number;
  completed: number;
  duplicate: number;
  failed: number;
  quarantined: number;
  rejected: number;
  progress_percentage: number;
}

export interface UploadLimits {
  max_files_per_batch: number;
  max_file_size_bytes: number;
  max_batch_size_bytes: number;
  allowed_extensions: string[];
}

export interface StagedFileResult {
  original_filename: string;
  size_bytes: number;
  status: UploadFileStatus;
  reason: string | null;
}

export interface UploadCreated {
  upload_batch_id: string;
  status: UploadBatchStatus;
  file_count: number;
  total_bytes: number;
  staged: StagedFileResult[];
  accepted_count: number;
  rejected_count: number;
}

export interface UploadBatchRow {
  id: string;
  source_type: string;
  status: UploadBatchStatus;
  created_at: string;
  file_count: number;
  total_bytes: number;
  upload_completed_at: string | null;
  processing_started_at: string | null;
  processing_completed_at: string | null;
  uploaded_by: string | null;
  counts: UploadCounts | null;
  processing_duration_seconds: number | null;
}

export interface BatchFileRow {
  original_filename: string;
  size_bytes: number;
  status: UploadFileStatus;
  telemetry_file_id: string | null;
  duplicate_of_file_id: string | null;
  failure_reason: string | null;
  staged_at: string;
  registered_at: string | null;
  telemetry_status: string | null;
  charger_id: string | null;
  business_date: string | null;
  row_count: number | null;
  unique_event_timestamp_count: number | null;
  quality_score: number | null;
  is_duplicate: boolean;
}

export interface UploadBatchDetail {
  batch: UploadBatchRow;
  counts: UploadCounts;
}
