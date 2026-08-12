import { useEffect, useRef, useState } from 'react';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Minimal data-loading hook.
 *
 * Deliberately no client-side cache: a data-operations console showing a stale
 * coverage figure is worse than one that takes an extra moment to load, and a
 * cache would make "reload" ambiguous during an incident.
 *
 * The loader is held in a ref so that re-fetching is driven purely by the `deps`
 * the caller declares. Without the ref, an inline loader closure would be a new
 * function on every render and would refetch in a loop.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    loaderRef
      .current()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'Request failed');
          setData(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    // Ignoring an in-flight response after the deps change is what prevents a
    // slow earlier request from overwriting a newer one.
    return () => {
      cancelled = true;
    };
    // The dependency list is supplied by the caller by design - this is a generic
    // hook, so its trigger set cannot be known statically here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, loading, error, reload: () => setNonce((value) => value + 1) };
}
