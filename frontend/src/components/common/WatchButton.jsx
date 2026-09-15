import { useEffect, useState } from 'react';
import { Bookmark, BookmarkCheck } from 'lucide-react';
import clsx from 'clsx';
import { apiDelete, apiGet, apiPost } from '../../services/api';

/** Toggle a vessel / listing / company / wallet / aircraft / domain / keyword on the analyst watchlist. */
export default function WatchButton({ kind, itemKey, label, className }) {
  const [item, setItem] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    if (!itemKey) return undefined;
    apiGet(`/api/watchlist/lookup?kind=${kind}&key=${encodeURIComponent(itemKey)}`)
      .then((r) => { if (active) setItem(r.watched ? r.item : null); })
      .catch(() => {});
    return () => { active = false; };
  }, [kind, itemKey]);

  const toggle = async () => {
    setBusy(true);
    setError(null);
    try {
      if (item) {
        await apiDelete(`/api/watchlist/${item.id}`);
        setItem(null);
      } else {
        setItem(await apiPost('/api/watchlist', { kind, key: itemKey, label: label || undefined }));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <button type="button" onClick={toggle} disabled={busy || !itemKey} title={error || (item ? 'On the watchlist - click to stop watching' : 'Add to the watchlist')}
      className={clsx('inline-flex items-center gap-1 px-2 py-1 rounded border text-xs disabled:opacity-50', item ? 'bg-steel-700 text-white border-steel-700' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-100', className)}>
      {item ? <BookmarkCheck size={12} aria-hidden="true" /> : <Bookmark size={12} aria-hidden="true" />} {item ? 'watching' : 'watch'}
    </button>
  );
}
