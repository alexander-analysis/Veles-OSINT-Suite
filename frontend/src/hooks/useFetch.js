import { useCallback, useEffect, useRef, useState } from 'react';
import { apiGet } from '../services/api';

/**
 * Fetch JSON from the API and (optionally) re-poll it.
 *
 * @param {string|null} url       API path; pass null to pause
 * @param {number}      interval  Poll interval in ms (0 = fetch once). Default 30s.
 */
export function useFetch(url, interval = 30000) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(Boolean(url));
  const [updatedAt, setUpdatedAt] = useState(null);
  const active = useRef(true);

  const load = useCallback(async () => {
    if (!url) return;
    try {
      const result = await apiGet(url);
      if (!active.current) return;
      setData(result);
      setError(null);
      setUpdatedAt(new Date());
    } catch (err) {
      if (active.current) setError(err);
    } finally {
      if (active.current) setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    active.current = true;
    setLoading(Boolean(url));
    load();
    const timer = interval > 0 && url ? setInterval(load, interval) : null;
    return () => {
      active.current = false;
      if (timer) clearInterval(timer);
    };
  }, [load, interval, url]);

  return { data, error, loading, updatedAt, refetch: load };
}

export default useFetch;
