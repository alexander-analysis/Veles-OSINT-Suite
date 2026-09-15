import { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { Globe, RefreshCw, Link2, ExternalLink, CheckCircle2, AlertTriangle, Newspaper } from 'lucide-react';
import clsx from 'clsx';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useFetch } from '../hooks/useFetch';
import { apiPost } from '../services/api';

const EVENT_TYPES = ['conflict', 'sanctions', 'maritime_incident', 'port_closure', 'infrastructure', 'trade', 'political'];
const TYPE_COLOR = {
  conflict: '#c0392b',
  sanctions: '#8e44ad',
  maritime_incident: '#2471a3',
  port_closure: '#d68910',
  infrastructure: '#b9770e',
  trade: '#1e8449',
  political: '#7f8c8d',
};
const SEVERITY_TONE = { critical: 'error', high: 'error', medium: 'warn', low: 'neutral' };
const SEVERITY_RADIUS = { critical: 10, high: 8, medium: 6, low: 4 };
const SOURCE_LABEL = {
  gdelt_events: 'GDELT events',
  gdelt_doc: 'GDELT articles',
  gov_uk_fcdo: 'UK FCDO',
  un_press: 'UN press',
  ofac_recent_actions: 'OFAC recent actions',
  rt: 'RT (state media)',
  tass: 'TASS (state media)',
  global_times: 'Global Times (state media)',
};

const label = (s) => (s || '').replace(/_/g, ' ');
const when = (iso) => (iso ? new Date(iso).toLocaleString() : '-');

function InvalidateOnMount() {
  const map = useMap();
  useEffect(() => {
    const timers = [50, 300, 1000].map((ms) => setTimeout(() => map.invalidateSize(), ms));
    return () => timers.forEach(clearTimeout);
  }, [map]);
  return null;
}

function EventMap({ features, onSelect }) {
  return (
    <MapContainer center={[30, 20]} zoom={2} minZoom={1} worldCopyJump className="h-[420px] w-full rounded" scrollWheelZoom>
      <InvalidateOnMount />
      <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {features.map((f) => {
        const p = f.properties;
        const [lon, lat] = f.geometry.coordinates;
        return (
          <CircleMarker
            key={p.id}
            center={[lat, lon]}
            radius={SEVERITY_RADIUS[p.severity] || 5}
            pathOptions={{ color: TYPE_COLOR[p.event_type] || '#555', fillColor: TYPE_COLOR[p.event_type] || '#555', fillOpacity: 0.55, weight: 1 }}
            eventHandlers={{ click: () => onSelect(p.id) }}
          >
            <Popup>
              <div className="text-xs max-w-[260px]">
                <div className="font-semibold">{p.title}</div>
                <div className="text-gray-500 mt-1">{label(p.event_type)} - {p.severity} - {p.country || '?'} - {when(p.event_date)}</div>
                {p.mentions ? <div className="text-gray-500">{p.mentions} media mentions</div> : null}
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}

function EventRow({ event, selected, onSelect }) {
  const correlated = event.correlated_with_market || event.correlated_with_maritime || event.correlated_with_sanctions;
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(event.id)}
        className={clsx('w-full text-left px-2 py-1.5 rounded border transition-colors', selected ? 'bg-steel-50 border-steel-200' : 'border-transparent hover:bg-gray-50')}
      >
        <div className="flex items-start gap-2">
          <span className="mt-1.5 inline-block h-2.5 w-2.5 rounded-full shrink-0" style={{ background: TYPE_COLOR[event.event_type] || '#555' }} aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-gray-900 line-clamp-2">{event.title}</div>
            <div className="text-xs text-gray-500 flex flex-wrap gap-x-2">
              <span>{label(event.event_type)}</span>
              <span>{event.country_primary || '-'}</span>
              <span>{when(event.event_date)}</span>
              <span>{SOURCE_LABEL[event.source] || event.source}</span>
              {correlated && <span className="text-steel-700 inline-flex items-center gap-0.5"><Link2 size={10} aria-hidden="true" /> linked</span>}
            </div>
          </div>
          <StatusBadge tone={SEVERITY_TONE[event.severity] || 'neutral'}>{event.severity}</StatusBadge>
        </div>
      </button>
    </li>
  );
}

function EventDetail({ id, onChanged }) {
  const { data: event, loading, refetch } = useFetch(id ? `/api/geopolitical/events/${id}` : null, 0);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => setNote(''), [id]);

  if (!id) return <p className="text-sm text-gray-500">Select an event on the map or in the list to see sources, impact assessment and cross-domain links.</p>;
  if (loading && !event) return <LoadingSpinner label="Loading event" />;
  if (!event) return null;

  const verify = async (status) => {
    setBusy(true);
    try {
      await apiPost(`/api/geopolitical/events/${event.id}/verify`, { status, notes: note || undefined });
      setNote('');
      await refetch();
      onChanged?.();
    } catch (err) {
      alert(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center gap-2 flex-wrap">
          <StatusBadge tone={SEVERITY_TONE[event.severity] || 'neutral'}>{event.severity}</StatusBadge>
          <span className="text-xs px-2 py-0.5 rounded text-white" style={{ background: TYPE_COLOR[event.event_type] || '#555' }}>{label(event.event_type)}</span>
          <StatusBadge tone={event.verification_status === 'confirmed' ? 'ok' : event.verification_status === 'disputed' ? 'error' : 'neutral'}>{event.verification_status}</StatusBadge>
          <span className="text-xs text-gray-500">confidence {Math.round((event.confidence_score || 0) * 100)}%</span>
        </div>
        <h3 className="text-base font-semibold mt-2">{event.title}</h3>
        <p className="text-sm text-gray-700 mt-1 whitespace-pre-wrap">{event.description}</p>
      </div>
      <table className="kv-table">
        <tbody>
          <tr><td>When</td><td>{when(event.event_date)} <span className="text-gray-400">(detected {when(event.detected_date)})</span></td></tr>
          <tr><td>Where</td><td>{[event.region, event.country_primary, event.country_secondary && `/ ${event.country_secondary}`].filter(Boolean).join(' ') || '-'}</td></tr>
          <tr><td>Countries</td><td>{(event.affected_countries || []).join(', ') || '-'}</td></tr>
          <tr><td>Sectors</td><td>{(event.affected_sectors || []).join(', ') || '-'}</td></tr>
          <tr><td>Source</td><td>{SOURCE_LABEL[event.source] || event.source}{event.mentions ? ` - ${event.mentions} mentions` : ''}{event.goldstein_scale != null ? ` - Goldstein ${event.goldstein_scale}` : ''}</td></tr>
          {event.market_impact && <tr><td>Market</td><td>{event.market_impact}</td></tr>}
          {event.supply_chain_impact && <tr><td>Supply chain</td><td>{event.supply_chain_impact}</td></tr>}
        </tbody>
      </table>
      {event.source_urls?.length ? (
        <div className="text-xs">
          {event.source_urls.map((u) => (
            <a key={u} href={u} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-steel-700 hover:underline break-all">
              <ExternalLink size={11} aria-hidden="true" /> {u}
            </a>
          ))}
        </div>
      ) : null}
      <div>
        <div className="card-title mb-1 flex items-center gap-1"><Link2 size={12} aria-hidden="true" /> Cross-domain links ({event.correlations.length})</div>
        {event.correlations.length ? (
          <ul className="space-y-1 text-xs">
            {event.correlations.map((c) => (
              <li key={c.id} className="border border-gray-200 rounded px-2 py-1">
                <div className="flex justify-between gap-2">
                  <span className="font-medium">{label(c.alert_type)}</span>
                  <span className="text-gray-500">{Math.round((c.correlation_score || 0) * 100)}% - {c.correlation_type} - {Math.abs(c.time_delta_minutes || 0)} min {c.time_delta_direction}</span>
                </div>
                <div className="text-gray-700">{c.alert_summary}</div>
              </li>
            ))}
          </ul>
        ) : <p className="text-xs text-gray-500">No market / maritime / sanctions signal inside the correlation window yet.</p>}
      </div>
      {event.intelligence_notes && <pre className="text-xs whitespace-pre-wrap bg-gray-50 border border-gray-200 rounded p-2">{event.intelligence_notes}</pre>}
      <div className="border-t border-gray-200 pt-2">
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Analyst note (optional)" className="w-full border border-gray-300 rounded px-2 py-1 text-xs" />
        <div className="flex gap-1 mt-1">
          <button type="button" disabled={busy} onClick={() => verify('confirmed')} className="inline-flex items-center gap-1 px-2 py-1 rounded border border-green bg-green-50 text-green-700 text-xs hover:bg-green-100 disabled:opacity-50"><CheckCircle2 size={12} aria-hidden="true" /> Confirm</button>
          <button type="button" disabled={busy} onClick={() => verify('disputed')} className="inline-flex items-center gap-1 px-2 py-1 rounded border border-red bg-red-50 text-red-700 text-xs hover:bg-red-100 disabled:opacity-50"><AlertTriangle size={12} aria-hidden="true" /> Dispute</button>
          <button type="button" disabled={busy} onClick={() => verify('unconfirmed')} className="px-2 py-1 rounded border border-gray-300 bg-white text-xs hover:bg-gray-100 disabled:opacity-50">Reset</button>
        </div>
      </div>
    </div>
  );
}

function Summary({ summary }) {
  if (!summary) return null;
  const sev = summary.by_severity || {};
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 mb-4">
      <div className="card py-3"><div className="card-title">Events ({summary.hours}h)</div><div className="text-xl font-semibold mt-1">{summary.total}</div><div className="text-xs text-gray-500">{summary.correlations} cross-domain links</div></div>
      <div className="card py-3"><div className="card-title">Severity</div><div className="text-sm mt-1 flex flex-wrap gap-x-3"><span className="text-red-700">critical {sev.critical || 0}</span><span className="text-red-600">high {sev.high || 0}</span><span className="text-yellow-700">medium {sev.medium || 0}</span><span className="text-gray-500">low {sev.low || 0}</span></div></div>
      <div className="card py-3"><div className="card-title">By type</div><div className="text-xs mt-1 flex flex-wrap gap-x-2 gap-y-0.5">{Object.entries(summary.by_type || {}).sort((a, b) => b[1] - a[1]).map(([t, n]) => <span key={t}><span className="inline-block h-2 w-2 rounded-full mr-1" style={{ background: TYPE_COLOR[t] }} aria-hidden="true" />{label(t)} {n}</span>)}</div></div>
      <div className="card py-3"><div className="card-title">Most active countries</div><div className="text-xs mt-1 flex flex-wrap gap-x-2">{(summary.top_countries || []).slice(0, 8).map((c) => <span key={c.country}><span className="font-mono font-medium">{c.country}</span> {c.events}</span>)}</div></div>
    </div>
  );
}

export default function Geopolitical() {
  const [hours, setHours] = useState(48);
  const [types, setTypes] = useState(EVENT_TYPES.filter((t) => t !== 'political'));
  const [minSeverity, setMinSeverity] = useState('low');
  const [country, setCountry] = useState('');
  const [query, setQuery] = useState('');
  const [onlyLinked, setOnlyLinked] = useState(false);
  const [selected, setSelected] = useState(null);
  const [starting, setStarting] = useState(false);

  const params = useMemo(() => {
    const p = new URLSearchParams({ hours: String(hours), min_severity: minSeverity, limit: '150' });
    if (types.length && types.length < EVENT_TYPES.length) p.set('event_type', types.join(','));
    if (country.trim()) p.set('country', country.trim().toUpperCase());
    if (query.trim()) p.set('q', query.trim());
    if (onlyLinked) p.set('correlated', 'true');
    return p.toString();
  }, [hours, types, minSeverity, country, query, onlyLinked]);

  const { data: events, loading, error, refetch, updatedAt } = useFetch(`/api/geopolitical/events?${params}`, 60000);
  const { data: geojson } = useFetch(`/api/geopolitical/geojson?hours=${hours}&min_severity=${minSeverity}`, 60000);
  const { data: summary, refetch: refetchSummary } = useFetch(`/api/geopolitical/summary?hours=${hours}`, 60000);
  const { data: sources } = useFetch('/api/geopolitical/sources', 120000);
  const { data: status } = useFetch('/api/geopolitical/status', 30000);

  const typeSet = new Set(types);
  const features = (geojson?.features || []).filter((f) => typeSet.has(f.properties.event_type));

  const toggleType = (t) => setTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const collectNow = async () => {
    setStarting(true);
    try {
      await apiPost('/api/geopolitical/refresh?job=all', {});
      setTimeout(() => {
        refetch();
        refetchSummary();
      }, 8000);
    } catch (err) {
      alert(err.message);
    } finally {
      setStarting(false);
    }
  };

  const lastRun = status?.last_run || {};
  const lastGdelt = lastRun.gdelt_events ? new Date(lastRun.gdelt_events).toLocaleTimeString() : 'pending';

  return (
    <div>
      <PageHeader title="Geopolitical Event Monitor" subtitle="GDELT 2.0 events and articles, UK FCDO, UN and OFAC announcements - classified, scored and linked to market, maritime and sanctions signals">
        {updatedAt && <span className="text-xs text-gray-500">Refreshed {updatedAt.toLocaleTimeString()}</span>}
        <StatusBadge tone={lastRun.gdelt_events ? 'ok' : 'warn'}>GDELT {lastGdelt}</StatusBadge>
        <button type="button" onClick={collectNow} disabled={starting} className="flex items-center gap-1 px-2 py-1 rounded border border-gray-300 bg-white text-xs hover:bg-gray-100 disabled:opacity-50">
          <RefreshCw size={12} className={starting ? 'animate-spin' : ''} aria-hidden="true" /> Collect now
        </button>
      </PageHeader>

      <Summary summary={summary} />

      <div className="card mb-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
          <label className="flex items-center gap-1">Window
            <select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="border border-gray-300 rounded px-1 py-0.5 bg-white">
              {[6, 24, 48, 72, 168, 720].map((h) => <option key={h} value={h}>{h < 48 ? `${h} h` : `${h / 24} d`}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1">Min severity
            <select value={minSeverity} onChange={(e) => setMinSeverity(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white">
              {['low', 'medium', 'high', 'critical'].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1">Country <input value={country} onChange={(e) => setCountry(e.target.value)} placeholder="ISO-2" maxLength={2} className="border border-gray-300 rounded px-1 py-0.5 w-14 uppercase" /></label>
          <label className="flex items-center gap-1">Search <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="tanker, pipeline, ..." className="border border-gray-300 rounded px-1 py-0.5 w-40" /></label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={onlyLinked} onChange={(e) => setOnlyLinked(e.target.checked)} /> linked only</label>
          <div className="flex flex-wrap gap-1 ml-auto">
            {EVENT_TYPES.map((t) => (
              <button key={t} type="button" onClick={() => toggleType(t)} className={clsx('px-2 py-0.5 rounded border', types.includes(t) ? 'text-white border-transparent' : 'bg-white text-gray-500 border-gray-300')} style={types.includes(t) ? { background: TYPE_COLOR[t] } : undefined}>
                {label(t)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <div className="card border-red mb-4 text-sm text-red-700">{error.message}</div>}

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2 space-y-4">
          <div className="card p-2">
            <EventMap features={features} onSelect={setSelected} />
            <div className="text-xs text-gray-500 mt-1 px-1">{features.length} geolocated event(s) - marker size follows severity, colour follows type. GDELT geocodes the action location; official feeds are listed without coordinates.</div>
          </div>
          <div className="card">
            <div className="flex items-center justify-between mb-2">
              <span className="card-title flex items-center gap-1"><Globe size={12} aria-hidden="true" /> Events ({events?.total ?? 0})</span>
              {loading && <span className="text-xs text-gray-400">loading</span>}
            </div>
            {events?.events?.length ? (
              <ul className="space-y-0.5 max-h-[560px] overflow-y-auto pr-1">
                {events.events.map((e) => <EventRow key={e.id} event={e} selected={selected === e.id} onSelect={setSelected} />)}
              </ul>
            ) : !loading && <p className="text-sm text-gray-500">No events match - widen the window or lower the severity floor. The first GDELT export lands about a minute after start.</p>}
          </div>
        </div>
        <div className="space-y-4">
          <div className="card">
            <div className="card-title mb-2">Event detail</div>
            <EventDetail id={selected} onChanged={() => { refetch(); refetchSummary(); }} />
          </div>
          <div className="card">
            <div className="card-title mb-2 flex items-center gap-1"><Newspaper size={12} aria-hidden="true" /> Sources</div>
            <table className="w-full text-xs">
              <tbody>
                {(sources || []).map((s) => (
                  <tr key={s.id} className="border-b border-gray-100">
                    <td className="py-1 pr-2">{SOURCE_LABEL[s.source_name] || s.source_name}</td>
                    <td className="py-1 pr-2 text-gray-500">{s.source_type}</td>
                    <td className="py-1 text-right text-gray-500">{s.last_fetch ? new Date(s.last_fetch).toLocaleTimeString() : '-'}</td>
                    <td className="py-1 pl-2"><StatusBadge tone={(s.last_status || '').startsWith('ok') ? 'ok' : s.last_status ? 'error' : 'neutral'}>{(s.last_status || 'pending').split(':')[0]}</StatusBadge></td>
                  </tr>
                ))}
                {!sources?.length && <tr><td className="text-gray-500 py-1">Feeds are polled every 30 minutes.</td></tr>}
              </tbody>
            </table>
            <div className="text-xs text-gray-500 mt-2">
              GDELT events: {status?.last_result?.gdelt_events ? `${status.last_result.gdelt_events.inserted} new of ${status.last_result.gdelt_events.rows} rows` : 'pending'} - articles: {status?.last_result?.gdelt_doc ? `${status.last_result.gdelt_doc.inserted} new` : 'pending'} - correlation: {status?.last_result?.correlate ? `${status.last_result.correlate.correlations} new link(s)` : 'pending'}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
