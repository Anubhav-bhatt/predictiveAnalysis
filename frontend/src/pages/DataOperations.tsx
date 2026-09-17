/**
 * Daily Fleet Data Operations (sections 31-36).
 *
 * The page answers, in order: what was expected, what arrived, what is missing,
 * what is incomplete, and what arrived late. Every number comes from the backend.
 */

import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  DailyFindings,
  FleetDistribution,
  ProcessingStages,
  SummaryTiles,
} from '../components/DailySummaryPanel';
import { CoverageTable, LateArrivalsTable, MissingChargersTable } from '../components/tables';
import { api } from '../lib/api';
import { today } from '../lib/format';
import { useAsync } from '../lib/useAsync';
import type { ArrivalStatus, CompletenessStatus } from '../lib/types';

type View = 'overview' | 'all' | 'incomplete' | 'missing' | 'late';

const VIEWS: { key: View; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'all', label: 'All charger-days' },
  { key: 'incomplete', label: 'Partial & incomplete' },
  { key: 'missing', label: 'Missing' },
  { key: 'late', label: 'Late' },
];

export function DataOperations() {
  const [params, setParams] = useSearchParams();
  const date = params.get('date') ?? today();
  const [view, setView] = useState<View>('overview');
  const [site, setSite] = useState('');

  const setDate = (value: string) => {
    const next = new URLSearchParams(params);
    next.set('date', value);
    setParams(next, { replace: true });
  };

  const summary = useAsync(() => api.dailySummary(date), [date]);

  // Filters are resolved server-side; the client never slices a fetched page.
  const filters = useMemo(() => {
    if (view === 'missing') return { arrival_status: 'MISSING' as ArrivalStatus };
    if (view === 'late') return { arrival_status: 'LATE' as ArrivalStatus };
    if (view === 'incomplete') return { completeness_status: 'PARTIAL' as CompletenessStatus };
    return {};
  }, [view]);

  const chargers = useAsync(
    () =>
      api.chargersForDay(date, {
        ...filters,
        site: site || undefined,
        page_size: 100,
      }),
    [date, filters, site],
  );

  const missing = useAsync(() => api.missingChargers(date), [date]);
  const late = useAsync(() => api.lateArrivals(date), [date]);

  const reloadAll = () => {
    summary.reload();
    chargers.reload();
    missing.reload();
    late.reload();
  };

  return (
    <div className="app">
      <div className="masthead">
        <div>
          <h1>Daily Fleet Data Operations</h1>
          <div className="sub">
            Telemetry delivery, coverage and gap detection for one business date.
            Coverage is computed from unique event timestamps, never raw rows.
          </div>
        </div>
        <div className="controls">
          <label htmlFor="business-date" style={{ color: 'var(--text-dim)', fontSize: 13 }}>
            Business date
          </label>
          <input
            id="business-date"
            type="date"
            value={date}
            max={today()}
            onChange={(event) => setDate(event.target.value)}
          />
          <input
            type="text"
            placeholder="Filter by site"
            value={site}
            onChange={(event) => setSite(event.target.value)}
            style={{ width: 130 }}
          />
          <button onClick={reloadAll}>Reload</button>
          <Link className="btn-link" to="/data-operations/upload">
            Upload data
          </Link>
          <Link className="btn-link" to="/data-operations/uploads">
            Upload history
          </Link>
          <Link className="btn-link" to="/research">
            Research Lab
          </Link>
        </div>
      </div>

      {summary.error ? (
        <div className="panel">
          <div className="error">Could not load the daily summary: {summary.error}</div>
        </div>
      ) : null}

      {summary.loading && !summary.data ? (
        <div className="panel">
          <div className="loading">Loading {date}…</div>
        </div>
      ) : null}

      {summary.data?.data ? (
        <>
          <SummaryTiles summary={summary.data.data} />

          <div className="tabs">
            {VIEWS.map((entry) => (
              <button
                key={entry.key}
                className={view === entry.key ? 'active' : ''}
                onClick={() => setView(entry.key)}
              >
                {entry.label}
              </button>
            ))}
          </div>

          {view === 'overview' ? (
            <>
              <FleetDistribution summary={summary.data.data} />
              <ProcessingStages summary={summary.data.data} />
              <DailyFindings summary={summary.data.data} />
            </>
          ) : null}

          {view === 'missing' ? (
            missing.data ? (
              <MissingChargersTable rows={missing.data.data} date={date} />
            ) : (
              <div className="panel">
                <div className="loading">Loading missing chargers…</div>
              </div>
            )
          ) : null}

          {view === 'late' ? (
            late.data ? (
              <LateArrivalsTable rows={late.data.data} date={date} />
            ) : (
              <div className="panel">
                <div className="loading">Loading late arrivals…</div>
              </div>
            )
          ) : null}

          {view === 'all' || view === 'incomplete' ? (
            chargers.error ? (
              <div className="panel">
                <div className="error">{chargers.error}</div>
              </div>
            ) : chargers.data ? (
              <CoverageTable
                rows={chargers.data.data}
                date={date}
                title={view === 'incomplete' ? 'Partial charger-days' : 'All charger-days'}
                hint={`${chargers.data.meta.total} charger-days · worst coverage first`}
              />
            ) : (
              <div className="panel">
                <div className="loading">Loading charger-days…</div>
              </div>
            )
          ) : null}
        </>
      ) : null}
    </div>
  );
}
