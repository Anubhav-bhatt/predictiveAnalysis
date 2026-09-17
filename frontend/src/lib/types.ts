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

// ---------------------------------------------------------------------------
// Phase 7: Historical Continuity & Time-Series Research Types
// ---------------------------------------------------------------------------

export interface SamplingProfile {
  observation_count: number;
  distinct_timestamps: number;
  first_event_time: string | null;
  last_event_time: string | null;
  coverage_duration_seconds: number;
  median_interval_seconds: number | null;
  p05_interval_seconds: number | null;
  p95_interval_seconds: number | null;
  min_interval_seconds: number | null;
  max_interval_seconds: number | null;
  expected_interval_seconds: number | null;
  same_second_frame_count: number;
}

export interface HistoricalGap {
  gap_start: string;
  gap_end: string;
  gap_duration_seconds: number;
  previous_event_time: string;
  next_event_time: string;
  expected_interval_seconds: number | null;
  gap_multiple: number | null;
}

export interface PatternResearchEligibility {
  charger_id: string;
  history_days: number;
  observation_count: number;
  median_sampling_interval_seconds: number | null;
  largest_gap_seconds: number | null;
  gap_count: number;
  signal_count: number;
  pattern_research_ready: boolean;
  reason: string;
}

export interface ChargerContinuitySummary {
  charger_id: string;
  first_seen: string | null;
  last_seen: string | null;
  observation_count: number;
  distinct_timestamps: number;
  observed_days: number;
  latest_observation_age_seconds: number | null;
  connectors_observed: number[];
  smrs_observed: number[];
  rectifiers_observed: number[];
  configuration_versions_count: number;
  sampling_profile: SamplingProfile;
  gaps: HistoricalGap[];
  pattern_eligibility: PatternResearchEligibility;
  history_depth_status: 'SINGLE_OBSERVATION' | 'MULTI_OBSERVATION' | 'NO_DATA';
}

export interface HistoricalObservation {
  event_time: string;
  frame_sequence: number;
  frame_id: string;
  metrics: Record<string, unknown>;
}

export interface ChargerHistoryResponse {
  charger_id: string;
  total_count: number;
  observations: HistoricalObservation[];
  next_cursor: string | null;
}

export interface SignalObservation {
  event_time: string;
  frame_sequence: number;
  value: unknown;
  raw_value: string | null;
  masked_sentinel: boolean;
}

export interface SignalHistoryResponse {
  charger_id: string;
  component_type: string | null;
  component_id: number | null;
  signal_name: string;
  observation_count: number;
  observations: SignalObservation[];
}

export interface ConfigurationSnapshot {
  event_time: string;
  frame_sequence: number;
  config_hash: string;
  raw_config_json: Record<string, unknown> | null;
  charging_mode: string | null;
  charging_start_method: string | null;
  charge_selected_mode: string | null;
  ev_max_voltage_limit: number | null;
  ev_max_current_limit: number | null;
}

// ---------------------------------------------------------------------------
// Phase 8: Discrete Operational Event Reconstruction Types
// ---------------------------------------------------------------------------

export type EventType =
  | 'CHARGING_SESSION'
  | 'ALARM_EVENT'
  | 'FAULT_EVENT'
  | 'STATE_TRANSITION'
  | 'CONFIGURATION_CHANGE';

export type EventConfidence = 'HIGH' | 'MEDIUM' | 'LOW';

export type DiscreteAlarmSeverity = 'INFO' | 'MINOR' | 'MAJOR' | 'CRITICAL';

export type TerminationClass =
  | 'NORMAL'
  | 'USER_ABORTED'
  | 'REMOTE_STOPPED'
  | 'SYSTEM_FAULT'
  | 'COMMUNICATION_LOSS'
  | 'UNSPECIFIED';

export interface ChargingSessionEvent {
  id: string;
  charger_id: string;
  connector_id: number;
  session_id: string | null;
  start_time: string;
  charging_start_time: string | null;
  charging_end_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  energy_delivered_kwh: number | null;
  start_soc: number | null;
  end_soc: number | null;
  stop_reason: string | null;
  termination_class: TerminationClass | null;
  confidence: EventConfidence;
  has_gap: boolean;
  quality_flags: string[] | null;
  evidence: Record<string, unknown> | null;
  reconstruction_version: string;
  created_at: string;
}

export interface AlarmEvent {
  id: string;
  charger_id: string;
  component_type: string;
  component_id: number | null;
  alarm_code: string;
  alarm_name: string;
  severity: DiscreteAlarmSeverity;
  start_time: string;
  end_time: string | null;
  duration_seconds: number | null;
  is_open: boolean;
  start_state: string | null;
  end_state: string | null;
  confidence: EventConfidence;
  has_gap: boolean;
  quality_flags: string[] | null;
  reconstruction_version: string;
  created_at: string;
}

export interface FaultEvent {
  id: string;
  charger_id: string;
  component_type: string;
  component_id: number | null;
  fault_code: string;
  fault_name: string;
  start_time: string;
  end_time: string | null;
  duration_seconds: number | null;
  is_open: boolean;
  initial_reading: string | null;
  clearing_reading: string | null;
  confidence: EventConfidence;
  has_gap: boolean;
  quality_flags: string[] | null;
  reconstruction_version: string;
  created_at: string;
}

export interface StateTransitionEvent {
  id: string;
  charger_id: string;
  component_type: string;
  component_id: number | null;
  state_field: string;
  from_state: string | null;
  to_state: string;
  transition_time: string;
  frame_sequence: number;
  created_at: string;
}

export interface ConfigurationChangeEvent {
  id: string;
  charger_id: string;
  change_time: string;
  old_config_hash: string;
  new_config_hash: string;
  changed_fields_json: Record<string, unknown>;
  previous_config_json: Record<string, unknown> | null;
  new_config_json: Record<string, unknown> | null;
  reconstruction_version: string;
  created_at: string;
}

export interface UnifiedEventTimelineItem {
  event_id: string;
  event_type: EventType;
  event_time: string;
  end_time: string | null;
  title: string;
  description: string;
  component: string;
  severity: string | null;
  duration_seconds: number | null;
  is_open: boolean;
  has_gap: boolean;
  confidence: EventConfidence;
  metadata: Record<string, unknown>;
}

export interface EventTimelineResponse {
  charger_id: string;
  total_count: number;
  events: UnifiedEventTimelineItem[];
}

export interface EventReconstructionOutcome {
  charger_id: string;
  sessions_reconstructed: number;
  alarms_reconstructed: number;
  faults_reconstructed: number;
  state_transitions_reconstructed: number;
  configuration_changes_reconstructed: number;
  reconstruction_duration_ms: number;
}

export interface ChargingSessionsResponse {
  charger_id: string;
  total_count: number;
  sessions: ChargingSessionEvent[];
}

export interface AlarmEventsResponse {
  charger_id: string;
  total_count: number;
  alarms: AlarmEvent[];
}

// ---------------------------------------------------------------------------
// Phase 9: Scientific Pattern Discovery & Analytical Dataset Types
// ---------------------------------------------------------------------------

export type PatternEvidenceLevel =
  | 'OBSERVATION'
  | 'WEAK_CANDIDATE'
  | 'MODERATE_CANDIDATE'
  | 'STRONG_CANDIDATE'
  | 'CONFIRMED_PRECURSOR';

export type PatternCategory =
  | 'THERMAL_DRIFT'
  | 'VOLTAGE_ANOMALY'
  | 'CURRENT_IMBALANCE'
  | 'SESSION_DEGRADATION'
  | 'ALARM_CLUSTERING'
  | 'FAULT_RECURRENCE'
  | 'EFFICIENCY_DECLINE'
  | 'COMPONENT_DIVERGENCE'
  | 'OPERATIONAL_PATTERN';

export type AnalyticalGrain =
  | 'CHARGER_TIME'
  | 'CONNECTOR_TIME'
  | 'SMR_TIME'
  | 'RECTIFIER_TIME'
  | 'SESSION_LEVEL'
  | 'EVENT_CENTERED';

export interface SignalStatisticsDTO {
  signal_name: string;
  count: number;
  non_null_count: number;
  null_count: number;
  sentinel_count: number;
  zero_count: number;
  negative_count: number;
  mean: number | null;
  std: number | null;
  min_val: number | null;
  max_val: number | null;
  p05: number | null;
  p25: number | null;
  p50: number | null;
  p75: number | null;
  p95: number | null;
  skewness: number | null;
  kurtosis: number | null;
  distinct_count: number | null;
  missing_rate: number;
}

export interface CorrelationEntry {
  signal_a: string;
  signal_b: string;
  pearson_r: number | null;
  spearman_rho: number | null;
  sample_count: number;
}

export interface CorrelationMatrix {
  signal_names: string[];
  entries: CorrelationEntry[];
}

export interface PatternCandidateDTO {
  id: string | null;
  charger_id: string;
  pattern_category: PatternCategory;
  evidence_level: PatternEvidenceLevel;
  title: string;
  description: string;
  confidence_score: number;
  affected_signals: string[];
  affected_components: string[];
  observation_window_start: string | null;
  observation_window_end: string | null;
  supporting_evidence: Record<string, unknown>[];
  analytical_grain: AnalyticalGrain | null;
  scan_version: string;
  created_at: string | null;
}

export interface ChargerEDASummary {
  charger_id: string;
  observation_count?: number;
  session_count?: number;
  alarm_count?: number;
  gap_count?: number;
  missing_rate?: number;
  pattern_count?: number;
}

export interface FleetEDASummary {
  total_chargers: number;
  total_observations: number;
  total_sessions: number;
  total_alarms: number;
  total_faults: number;
  total_gaps: number;
  temporal_span_start: string | null;
  temporal_span_end: string | null;
  fleet_missing_rate: number;
  signal_count: number;
  pattern_candidate_count: number;
  charger_summaries: ChargerEDASummary[];
}

export interface AnalyticalDatasetSummary {
  grain: string;
  charger_id: string | null;
  record_count: number;
  signal_count: number;
  window_start: string | null;
  window_end: string | null;
  gap_count: number;
  missing_rate: number;
  dataset_version: string;
  build_duration_ms: number;
}

export interface DataReadiness {
  overall_readiness: string;
  temporal_depth: string;
  charger_count: number;
  observation_count: number;
  signal_coverage_rate: number;
  temporal_span_days: number;
  gap_rate: number;
  session_count: number;
  alarm_count: number;
  pattern_candidate_count: number;
  blockers: string[];
  recommendations: string[];
}

export interface PatternScanOutcome {
  charger_id: string;
  candidates_found: number;
  candidates_persisted: number;
  scan_duration_ms: number;
  signals_scanned: number;
  records_analyzed: number;
  scan_version: string;
}

