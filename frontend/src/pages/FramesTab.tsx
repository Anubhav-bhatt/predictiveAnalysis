/**
 * Reconstruction diagnostics for one charger-day (Phase 1D sections 49-53).
 *
 * Deliberately a drilldown, not a landing page: replay classifications and
 * fingerprints are engineering diagnostics, so the default view is the summary and
 * the detail is one click away.
 */

import { useState } from 'react';

import {
  CollisionExplorer,
  FRAME_FILTERS,
  FrameDetailPanel,
  FrameDiffViewer,
  FrameTable,
} from '../components/frames';
import { api } from '../lib/api';
import { count, isoDate } from '../lib/format';
import type { FrameSummaryRow } from '../lib/types';
import { useAsync } from '../lib/useAsync';

export function FramesTab({
  chargerId,
  businessDate,
}: {
  chargerId: string;
  businessDate: string;
}) {
  const [filterKey, setFilterKey] = useState('all');
  const [selectedFrameId, setSelectedFrameId] = useState<string | null>(null);
  const [comparison, setComparison] = useState<[string, string] | null>(null);

  const activeFilter =
    FRAME_FILTERS.find((entry) => entry.key === filterKey) ?? FRAME_FILTERS[0]!;

  const frames = useAsync(
    () =>
      api.chargerFrames(chargerId, {
        from: businessDate,
        to: businessDate,
        ...activeFilter.params,
        page_size: 100,
      }),
    [chargerId, businessDate, filterKey],
  );

  const collisions = useAsync(
    () => api.chargerCollisions(chargerId, businessDate),
    [chargerId, businessDate],
  );

  const detail = useAsync(
    () => (selectedFrameId ? api.frame(selectedFrameId) : Promise.resolve(null)),
    [selectedFrameId],
  );

  const diff = useAsync(
    () =>
      comparison
        ? api.frameDiff(comparison[0], comparison[1])
        : Promise.resolve(null),
    [comparison],
  );

  const collisionGroups = collisions.data?.data ?? [];

  return (
    <>
      <section className="panel">
        <header>
          <h2>Source frames · {isoDate(businessDate)}</h2>
          <span className="hint">
            {frames.data ? `${count(frames.data.meta.total)} frames` : 'loading…'} ·
            repetition is classified, never deleted
          </span>
        </header>

        <div style={{ padding: '10px 14px', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {FRAME_FILTERS.map((entry) => (
            <button
              key={entry.key}
              className={filterKey === entry.key ? 'active' : ''}
              onClick={() => setFilterKey(entry.key)}
            >
              {entry.label}
            </button>
          ))}
        </div>

        {frames.error ? (
          <div className="error">
            Unable to load frames: {frames.error}
            <div style={{ marginTop: 10 }}>
              <button onClick={frames.reload}>Retry</button>
            </div>
          </div>
        ) : frames.loading && !frames.data ? (
          <div className="loading">Loading frames…</div>
        ) : (
          <FrameTable
            frames={frames.data?.data ?? []}
            selectedId={selectedFrameId}
            onSelect={(frame: FrameSummaryRow) => {
              setSelectedFrameId(frame.id);
              setComparison(null);
            }}
          />
        )}
      </section>

      {collisionGroups.length > 0 ? (
        <CollisionExplorer
          groups={collisionGroups}
          onCompare={(left, right) => {
            setComparison([left.id, right.id]);
            setSelectedFrameId(null);
          }}
        />
      ) : null}

      {comparison && diff.data?.data ? <FrameDiffViewer diff={diff.data.data} /> : null}

      {selectedFrameId && detail.data?.data ? (
        <FrameDetailPanel detail={detail.data.data} />
      ) : null}
    </>
  );
}
