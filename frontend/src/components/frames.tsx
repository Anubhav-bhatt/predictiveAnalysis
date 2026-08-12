/**
 * Frame reconstruction diagnostics (Phase 1D sections 49-53).
 *
 * Operational, not decorative. Three views:
 *
 * - **Reconstruction summary** for a file, with the raw-rows vs frames contrast
 *   spelled out so the two grains are never confused.
 * - **Collision explorer** for timestamps holding several distinct frames.
 * - **Frame diff** showing which logical positions changed - computed from the
 *   backend's fingerprint comparison, with no field names hard-coded here.
 */

import { count, percent, timeOnly, timestamp } from '../lib/format';
import type {
  CollisionGroup,
  DuplicateClassification,
  FrameDetail,
  FrameDiff,
  FrameStatus,
  FrameSummaryRow,
  ReconstructionSummary,
} from '../lib/types';
import { Pill } from './status';

type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'neutral';

const FRAME_STATUS_TONE: Record<FrameStatus, Tone> = {
  COMPLETE: 'ok',
  PARTIAL: 'warn',
  SEVERELY_INCOMPLETE: 'bad',
  MALFORMED: 'bad',
  AMBIGUOUS: 'bad',
};

/**
 * Replays are informational: they add no observation but are not defects.
 * A same-timestamp distinct frame is real telemetry, so it reads as ok.
 */
const CLASSIFICATION_TONE: Record<DuplicateClassification, Tone> = {
  UNIQUE: 'ok',
  EXACT_ROW_DUPLICATE: 'neutral',
  FULL_FRAME_REPLAY: 'info',
  PARTIAL_FRAME_REPLAY: 'warn',
  SAME_TIMESTAMP_DISTINCT_FRAME: 'ok',
  AMBIGUOUS: 'bad',
};

const SHORT_LABEL: Partial<Record<DuplicateClassification, string>> = {
  SAME_TIMESTAMP_DISTINCT_FRAME: 'DISTINCT',
  FULL_FRAME_REPLAY: 'FULL REPLAY',
  PARTIAL_FRAME_REPLAY: 'PARTIAL REPLAY',
  EXACT_ROW_DUPLICATE: 'ROW DUPLICATE',
};

export function FrameStatusPill({ status }: { status: FrameStatus }) {
  const label = status === 'SEVERELY_INCOMPLETE' ? 'SEVERE' : status;
  return (
    <span className={`pill ${FRAME_STATUS_TONE[status] ?? 'neutral'}`} title={status}>
      {label}
    </span>
  );
}

export function ClassificationPill({
  classification,
}: {
  classification: DuplicateClassification;
}) {
  return (
    <span
      className={`pill ${CLASSIFICATION_TONE[classification] ?? 'neutral'}`}
      title={classification}
    >
      {SHORT_LABEL[classification] ?? classification}
    </span>
  );
}

/** Section 49: the file-level reconstruction panel. */
export function ReconstructionPanel({ summary }: { summary: ReconstructionSummary }) {
  return (
    <section className="panel">
      <header>
        <h2>Reconstruction</h2>
        <span className="hint">
          {summary.reconstruction_version ?? 'latest'} ·{' '}
          {summary.expected_positions_per_frame} expected positions per frame
        </span>
      </header>

      <div className="tiles" style={{ padding: 14, marginBottom: 0 }}>
        <Tile label="Raw rows" value={count(summary.raw_rows)} note="source grain" />
        <Tile
          label="Unique timestamps"
          value={count(summary.unique_timestamps)}
          note={
            summary.rows_per_unique_timestamp
              ? `${summary.rows_per_unique_timestamp}x rows per timestamp`
              : undefined
          }
        />
        <Tile label="Frames" value={count(summary.frames_reconstructed)} />
        <Tile
          label="Canonical"
          value={count(summary.canonical_frames)}
          note="consumed downstream"
          tone="ok"
        />
        <Tile
          label="Full replays"
          value={count(summary.full_replays)}
          note="no new observation"
          tone={summary.full_replays > 0 ? 'info' : undefined}
        />
        <Tile
          label="Partial replays"
          value={count(summary.partial_replays)}
          tone={summary.partial_replays > 0 ? 'warn' : undefined}
        />
        <Tile
          label="Collisions"
          value={count(summary.collision_timestamps)}
          note="distinct frames, one second"
          tone={summary.collision_timestamps > 0 ? 'warn' : undefined}
        />
        <Tile
          label="Partial frames"
          value={count(summary.partial_frames)}
          tone={summary.partial_frames > 0 ? 'warn' : undefined}
        />
        <Tile
          label="Malformed"
          value={count(summary.malformed_frames)}
          tone={summary.malformed_frames > 0 ? 'bad' : undefined}
        />
        <Tile
          label="Ambiguous"
          value={count(summary.ambiguous_frames)}
          tone={summary.ambiguous_frames > 0 ? 'bad' : undefined}
        />
        <Tile
          label="Unassigned rows"
          value={count(summary.unassigned_rows)}
          note="retained, not dropped"
          tone={summary.unassigned_rows > 0 ? 'warn' : undefined}
        />
        <Tile
          label="Frame completeness"
          value={percent(summary.frame_completeness_percentage, 2)}
          note="data measure, not health"
        />
      </div>

      <div className="callout">
        Raw rows and frames are different grains. The source repeats each event
        timestamp once per connector/SMR position, and replayed frames add rows without
        adding observations — so {count(summary.raw_rows)} raw rows reduce to{' '}
        {count(summary.canonical_frames)} canonical frames. Repetition is classified
        here, never deleted.
      </div>
    </section>
  );
}

function Tile({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: Tone;
}) {
  const toneClass = tone === 'ok' || tone === 'warn' || tone === 'bad' ? ` ${tone}` : '';
  return (
    <div className={`tile${toneClass}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note ? <div className="note">{note}</div> : null}
    </div>
  );
}

/** Section 53: filter chips over frame status and duplicate classification. */
export const FRAME_FILTERS: { key: string; label: string; params: Record<string, string> }[] = [
  { key: 'all', label: 'All', params: {} },
  { key: 'canonical', label: 'Canonical', params: { canonical_only: 'true' } },
  { key: 'complete', label: 'Complete', params: { frame_status: 'COMPLETE' } },
  { key: 'partial', label: 'Partial', params: { frame_status: 'PARTIAL' } },
  {
    key: 'replay',
    label: 'Replay',
    params: { duplicate_classification: 'FULL_FRAME_REPLAY' },
  },
  {
    key: 'collision',
    label: 'Collision',
    params: { duplicate_classification: 'SAME_TIMESTAMP_DISTINCT_FRAME' },
  },
  { key: 'malformed', label: 'Malformed', params: { frame_status: 'MALFORMED' } },
  { key: 'ambiguous', label: 'Ambiguous', params: { frame_status: 'AMBIGUOUS' } },
];

export function FrameTable({
  frames,
  onSelect,
  selectedId,
}: {
  frames: FrameSummaryRow[];
  onSelect?: (frame: FrameSummaryRow) => void;
  selectedId?: string | null;
}) {
  if (frames.length === 0) {
    return <div className="empty">No frames match the current filters.</div>;
  }
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Event time</th>
            <th style={{ textAlign: 'right' }}>Seq</th>
            <th>Status</th>
            <th>Classification</th>
            <th style={{ textAlign: 'right' }}>Positions</th>
            <th style={{ textAlign: 'right' }}>Missing</th>
            <th style={{ textAlign: 'right' }}>Source rows</th>
            <th>Fingerprint</th>
          </tr>
        </thead>
        <tbody>
          {frames.map((frame) => (
            <tr
              key={frame.id}
              onClick={() => onSelect?.(frame)}
              style={{
                cursor: onSelect ? 'pointer' : undefined,
                background: frame.id === selectedId ? 'var(--surface-2)' : undefined,
              }}
            >
              <td>{timestamp(frame.event_time)}</td>
              <td className="num">{frame.frame_sequence}</td>
              <td>
                <FrameStatusPill status={frame.frame_status} />
              </td>
              <td>
                <ClassificationPill classification={frame.duplicate_classification} />
              </td>
              <td className="num">
                {frame.observed_position_count} / {frame.expected_position_count}
              </td>
              <td className="num">{count(frame.missing_position_count)}</td>
              <td className="num dim">
                {frame.source_order_min}–{frame.source_order_max}
              </td>
              <td className="dim">
                <code>{frame.fingerprint_short}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Section 50: timestamps carrying several distinct frames. */
export function CollisionExplorer({
  groups,
  onCompare,
}: {
  groups: CollisionGroup[];
  onCompare?: (left: FrameSummaryRow, right: FrameSummaryRow) => void;
}) {
  return (
    <section className="panel">
      <header>
        <h2>Timestamp collisions</h2>
        <span className="hint">
          Several genuinely different frames at one event timestamp — kept, not merged
        </span>
      </header>
      {groups.length === 0 ? (
        <div className="empty">
          No event timestamp on this date carries more than one distinct frame.
        </div>
      ) : (
        <>
          {groups.map((group) => (
            <div key={group.event_time} style={{ borderTop: '1px solid var(--border)' }}>
              <div
                style={{
                  padding: '10px 14px',
                  display: 'flex',
                  gap: 12,
                  alignItems: 'baseline',
                  flexWrap: 'wrap',
                }}
              >
                <strong>{timestamp(group.event_time)}</strong>
                <span className="hint">
                  {group.frame_count} frames · {group.canonical_count} canonical
                </span>
                {onCompare && group.frames.length >= 2 ? (
                  <button
                    onClick={() => onCompare(group.frames[0]!, group.frames[1]!)}
                    style={{ marginLeft: 'auto' }}
                  >
                    Compare seq 0 ↔ 1
                  </button>
                ) : null}
              </div>
              <FrameTable frames={group.frames} />
            </div>
          ))}
        </>
      )}
    </section>
  );
}

/** Section 51: which logical positions differ between two frames. */
export function FrameDiffViewer({ diff }: { diff: FrameDiff }) {
  return (
    <section className="panel">
      <header>
        <h2>Frame comparison</h2>
        <span className="hint">
          seq {diff.left.frame_sequence} ↔ seq {diff.right.frame_sequence} ·{' '}
          {diff.same_event_time ? 'same event timestamp' : 'different timestamps'}
        </span>
      </header>

      <div className="callout">
        {diff.identical_payload ? (
          <>
            Identical payload — these frames carry the same telemetry, so the later one
            is a replay and adds no observation.
          </>
        ) : (
          <>
            {diff.differing_position_count} logical position(s) differ. Positions are
            compared by canonical fingerprint, so the two frames are genuinely different
            observations rather than a duplicate.
          </>
        )}
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Logical position</th>
              <th>Seq {diff.left.frame_sequence}</th>
              <th>Seq {diff.right.frame_sequence}</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {diff.positions.map((position) => (
              <tr key={position.logical_position}>
                <td>
                  <code>{position.logical_position}</code>
                </td>
                <td className="dim">
                  <code>{position.left_row_fingerprint?.slice(0, 12) ?? '-'}</code>
                </td>
                <td className="dim">
                  <code>{position.right_row_fingerprint?.slice(0, 12) ?? '-'}</code>
                </td>
                <td>
                  {position.differs ? (
                    <Pill tone="warn">CHANGED</Pill>
                  ) : (
                    <Pill tone="neutral">same</Pill>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Section 52: provenance and replay audit for one frame. */
export function FrameDetailPanel({ detail }: { detail: FrameDetail }) {
  const { frame } = detail;
  return (
    <section className="panel">
      <header>
        <h2>
          Frame {timeOnly(frame.event_time)} · seq {frame.frame_sequence}
        </h2>
        <span className="hint">{frame.reconstruction_version}</span>
      </header>

      <div style={{ padding: 14, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <FrameStatusPill status={frame.frame_status} />
        <ClassificationPill classification={frame.duplicate_classification} />
        <span className="hint">
          {frame.observed_position_count} of {frame.expected_position_count} positions ·{' '}
          {percent(frame.completeness_percentage, 2)}
        </span>
        {detail.replay_count > 0 ? (
          <span className="hint">· replayed {detail.replay_count}x</span>
        ) : null}
      </div>

      {detail.missing_positions.length > 0 || detail.unexpected_positions.length > 0 ? (
        <div className="callout">
          {detail.missing_positions.length > 0 ? (
            <div>Missing positions: {detail.missing_positions.join(', ')}</div>
          ) : null}
          {detail.unexpected_positions.length > 0 ? (
            <div>
              Unexpected positions: {detail.unexpected_positions.join(', ')} — retained
              and reported, not discarded.
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th colSpan={4}>Source files</th>
            </tr>
            <tr>
              <th>File</th>
              <th style={{ textAlign: 'right' }}>Rows</th>
              <th style={{ textAlign: 'right' }}>Source row range</th>
              <th>Primary</th>
            </tr>
          </thead>
          <tbody>
            {detail.sources.map((source) => (
              <tr key={source.telemetry_file_id}>
                <td>
                  <code>{source.original_filename ?? source.telemetry_file_id}</code>
                </td>
                <td className="num">{count(source.row_count)}</td>
                <td className="num dim">
                  {source.first_source_row}–{source.last_source_row}
                </td>
                <td>
                  {source.is_primary_source ? (
                    <Pill tone="ok">primary</Pill>
                  ) : (
                    <Pill tone="info">also appears here</Pill>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail.replays.length > 0 ? (
        <div className="table-scroll" style={{ borderTop: '1px solid var(--border)' }}>
          <table>
            <thead>
              <tr>
                <th colSpan={3}>Replays of this frame</th>
              </tr>
              <tr>
                <th style={{ textAlign: 'right' }}>Seq</th>
                <th>Classification</th>
                <th style={{ textAlign: 'right' }}>Source rows</th>
              </tr>
            </thead>
            <tbody>
              {detail.replays.map((replay) => (
                <tr key={replay.id}>
                  <td className="num">{replay.frame_sequence}</td>
                  <td>
                    <ClassificationPill classification={replay.duplicate_classification} />
                  </td>
                  <td className="num dim">
                    {replay.source_order_min}–{replay.source_order_max}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="callout">
        Provenance: this frame → {detail.sources.length} source file(s) →{' '}
        {detail.rows.length} raw row(s). Raw telemetry values are not shown here; Bronze
        remains their only copy.
      </div>
    </section>
  );
}
