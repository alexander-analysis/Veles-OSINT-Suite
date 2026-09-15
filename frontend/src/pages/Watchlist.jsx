import { useState } from 'react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { Bookmark, BellOff, Bell, Trash2, RefreshCw, Plus } from 'lucide-react';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useFetch } from '../hooks/useFetch';
import { apiDelete, apiPatch, apiPost } from '../services/api';

const KINDS = ['vessel', 'entity', 'company', 'wallet', 'aircraft', 'domain', 'keyword'];
const KEY_HINT = { vessel: 'MMSI, IMO or exact name', entity: 'listing id or exact name', company: 'company name or LEI', wallet: 'address', aircraft: 'registration', domain: 'hostname', keyword: 'free text' };
const SEVERITY = { critical: 'border-red-900 bg-red-50', high: 'border-red bg-red-50', medium: 'border-orange bg-orange-50', low: 'border-gray-200 bg-white' };
const RECORD = { evasion_event: 'evasion', sanctions_breach: 'sanctions match', port_call: 'port call', transshipment: 'STS', psc_event: 'port state control', shipment: 'shipment', dark_oil: 'dark oil', legal_event: 'legal', transfer: 'transfer', sighting: 'sighting', breach_event: 'breach posting', geopolitical_event: 'event', narrative: 'narrative', sanctions_update: 'list update' };

function AddForm({ onAdded }) {
  const [kind, setKind] = useState('vessel');
  const [key, setKey] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (!key.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost('/api/watchlist', { kind, key: key.trim(), note: note.trim() || undefined });
      setKey('');
      setNote('');
      onAdded();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="card flex flex-wrap gap-2 items-center text-sm">
      <select value={kind} onChange={(e) => setKind(e.target.value)} className="border border-gray-300 rounded px-2 py-1.5 bg-white">{KINDS.map((k) => <option key={k} value={k}>{k}</option>)}</select>
      <input value={key} onChange={(e) => setKey(e.target.value)} placeholder={KEY_HINT[kind]} className="flex-1 min-w-[12rem] border border-gray-300 rounded px-3 py-1.5" />
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="note (optional)" className="flex-1 min-w-[12rem] border border-gray-300 rounded px-3 py-1.5" />
      <button type="submit" disabled={busy} className="flex items-center gap-1 px-3 py-1.5 rounded bg-steel-600 text-white hover:bg-steel-700 disabled:opacity-50"><Plus size={14} aria-hidden="true" /> Watch</button>
      {error && <span className="text-xs text-red-700 w-full">{error}</span>}
    </form>
  );
}

export default function Watchlist() {
  const { data: items, refetch, loading } = useFetch('/api/watchlist', 30000);
  const [selected, setSelected] = useState(null);
  const hitsUrl = `/api/watchlist/hits?limit=150${selected ? `&item_id=${selected}` : ''}`;
  const { data: hits, refetch: refetchHits } = useFetch(hitsUrl, 30000);
  const { data: summary } = useFetch('/api/watchlist/summary', 60000);
  const [checking, setChecking] = useState(false);

  const refresh = () => { refetch(); refetchHits(); };
  const toggle = async (item, field) => { await apiPatch(`/api/watchlist/${item.id}`, { [field]: !item[field] }); refresh(); };
  const remove = async (item) => { await apiDelete(`/api/watchlist/${item.id}`); if (selected === item.id) setSelected(null); refresh(); };
  const runCheck = async () => { setChecking(true); try { await apiPost('/api/watchlist/check', {}); setTimeout(refresh, 2500); } finally { setChecking(false); } };

  return (
    <div>
      <PageHeader title="Watchlist" subtitle="Vessels, listed parties, companies, wallets, aircraft, domains and keywords you want to be told about - every new record touching them lands here (and in your alert channels)">
        {summary && <StatusBadge tone={summary.hits ? 'warn' : 'ok'}>{summary.items} watched - {summary.hits} hit(s) in 7 d</StatusBadge>}
        <button type="button" onClick={runCheck} disabled={checking} className="flex items-center gap-1 px-2 py-1 rounded border border-gray-300 bg-white text-xs hover:bg-gray-100 disabled:opacity-50"><RefreshCw size={12} className={checking ? 'animate-spin' : ''} aria-hidden="true" /> Check now</button>
      </PageHeader>
      <div className="mb-4"><AddForm onAdded={refresh} /></div>
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="card xl:col-span-1">
          <div className="card-title mb-2 flex items-center gap-2"><Bookmark size={14} aria-hidden="true" /> Watched ({items?.length ?? 0})</div>
          {loading && !items && <LoadingSpinner />}
          {items?.length === 0 && <p className="text-sm text-gray-500">Nothing watched yet. Use the form above or the <em>watch</em> buttons on vessel pages, entity dossiers and search results.</p>}
          <ul className="space-y-1 text-sm max-h-[40rem] overflow-y-auto pr-1">
            {items?.map((item) => (
              <li key={item.id} className={clsx('border rounded p-2 cursor-pointer', selected === item.id ? 'border-steel-500 bg-steel-50' : 'border-gray-200 bg-white hover:bg-gray-50')} onClick={() => setSelected(selected === item.id ? null : item.id)}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium truncate">{item.href ? <Link to={item.href} className="text-steel-700 hover:underline" onClick={(e) => e.stopPropagation()}>{item.label || item.key}</Link> : (item.label || item.key)}</span>
                  <span className="flex items-center gap-1 shrink-0">
                    <StatusBadge>{item.kind}</StatusBadge>
                    {item.recent_hits > 0 && <StatusBadge tone="warn">{item.recent_hits} new</StatusBadge>}
                  </span>
                </div>
                <div className="text-xs text-gray-500 flex items-center justify-between gap-2 mt-1">
                  <span>{item.hit_count} hit(s){item.last_hit_at ? ` - last ${new Date(item.last_hit_at).toLocaleString()}` : ''}{item.note ? ` - ${item.note}` : ''}</span>
                  <span className="flex gap-1">
                    <button type="button" title={item.alert ? 'alerts on' : 'alerts off'} onClick={(e) => { e.stopPropagation(); toggle(item, 'alert'); }} className="p-0.5 hover:text-steel-700">{item.alert ? <Bell size={12} /> : <BellOff size={12} />}</button>
                    <button type="button" title="stop watching" onClick={(e) => { e.stopPropagation(); remove(item); }} className="p-0.5 hover:text-red-700"><Trash2 size={12} /></button>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="card xl:col-span-2">
          <div className="card-title mb-2">Hits {selected ? 'for the selected item' : '(all items)'} {hits ? `(${hits.length})` : ''}</div>
          {hits?.length === 0 && <p className="text-sm text-gray-500">No hits yet. A fresh item is back-filled with the last seven days; the bot then checks every 10 minutes.</p>}
          <ul className="space-y-1.5 text-sm max-h-[40rem] overflow-y-auto pr-1">
            {hits?.map((h) => (
              <li key={h.id} className={clsx('border rounded p-2', SEVERITY[h.severity] || SEVERITY.low)}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-gray-500">{new Date(h.timestamp).toLocaleString()}</span>
                  <StatusBadge>{RECORD[h.record_type] || h.record_type}</StatusBadge>
                  <span className="text-xs text-gray-500">{h.severity}</span>
                  {!selected && <span className="text-xs text-gray-600">{h.item_label || h.item_key} ({h.item_kind})</span>}
                  {h.href && <Link to={h.href} className="text-xs text-steel-700 hover:underline ml-auto">open</Link>}
                </div>
                <div className="mt-0.5">{h.summary}</div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
