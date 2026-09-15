import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { Plane, ShieldAlert, Megaphone, Globe2, Gavel, Anchor, RefreshCw, ExternalLink } from 'lucide-react';
import clsx from 'clsx';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import { useFetch } from '../hooks/useFetch';
import { apiPost } from '../services/api';

const SEVERITY_TONE = { critical: 'error', high: 'error', medium: 'warn', low: 'neutral' };
const when = (iso) => (iso ? new Date(iso).toLocaleString() : '-');
const label = (s) => (s || '').replace(/_/g, ' ');
const usd = (v) => (v == null ? '-' : `$${Math.round(v).toLocaleString()}`);

function InvalidateOnMount() {
  const map = useMap();
  useEffect(() => {
    const timers = [50, 300, 1000].map((ms) => setTimeout(() => map.invalidateSize(), ms));
    return () => timers.forEach(clearTimeout);
  }, [map]);
  return null;
}

function RunButton({ path, label: text, onDone }) {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      await apiPost(path, {});
      setTimeout(onDone, 15000);
    } catch (err) {
      alert(err.message);
    } finally {
      setBusy(false);
    }
  };
  return <button type="button" onClick={run} disabled={busy} className="flex items-center gap-1 px-2 py-1 rounded border border-gray-300 bg-white text-xs hover:bg-gray-100 disabled:opacity-50"><RefreshCw size={12} className={busy ? 'animate-spin' : ''} aria-hidden="true" /> {text}</button>;
}

function Aviation() {
  const { data: summary, refetch: r1 } = useFetch('/api/aviation/summary?days=7', 60000);
  const { data: aircraft, refetch: r2 } = useFetch('/api/aviation/aircraft?limit=300', 60000);
  const { data: geo, refetch: r3 } = useFetch('/api/aviation/geojson?hours=48', 60000);
  const { data: status } = useFetch('/api/aviation/status', 30000);
  const [selected, setSelected] = useState(null);
  const { data: sightings } = useFetch(selected ? `/api/aviation/aircraft/${selected}/sightings?days=30` : null, 0);
  const refresh = () => { r1(); r2(); r3(); };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {summary && <><span className="card px-3 py-2"><b>{summary.aircraft}</b> listed airframes - <b>{summary.with_mode_s}</b> with Mode S - <b>{summary.seen_recently}</b> seen in 7 d - <b>{summary.sightings}</b> fixes</span>
          <span className="text-gray-500">{Object.entries(summary.by_country || {}).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([c, n]) => `${c} ${n}`).join(' - ')}</span></>}
        <span className="text-gray-500 ml-auto">sweep {status?.last_run?.sweep ? new Date(status.last_run.sweep).toLocaleTimeString() : 'pending'}{status?.last_result?.sweep ? ` - ${status.last_result.sweep.checked} checked, ${status.last_result.sweep.airborne} airborne` : ''} - OpenSky calls today {status?.opensky_calls_today ?? 0}</span>
        <RunButton path="/api/aviation/refresh?job=sweep" label="Sweep now" onDone={refresh} />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2 card p-2">
          <MapContainer center={[30, 40]} zoom={2} minZoom={1} worldCopyJump className="h-[360px] w-full rounded" scrollWheelZoom>
            <InvalidateOnMount />
            <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            {(geo?.features || []).map((f) => (
              <CircleMarker key={f.properties.id} center={[f.geometry.coordinates[1], f.geometry.coordinates[0]]} radius={7} pathOptions={{ color: '#7c3aed', fillColor: '#7c3aed', fillOpacity: 0.7 }} eventHandlers={{ click: () => setSelected(f.properties.id) }}>
                <Popup><div className="text-xs"><b>{f.properties.registration}</b> {f.properties.operator} - {f.properties.model}<br />{f.properties.callsign} - {f.properties.altitude_ft ? `${f.properties.altitude_ft} ft` : 'ground'} - {when(f.properties.last_seen)}</div></Popup>
              </CircleMarker>
            ))}
          </MapContainer>
          <div className="text-xs text-gray-500 mt-1 px-1">{geo?.features?.length || 0} listed aircraft seen on ADS-B in the last 48 h. Registrations are swept on adsb.lol in rotation; positions appear only while the airframe transmits.</div>
        </div>
        <div className="card text-xs">
          <div className="card-title mb-2">Recent flights</div>
          {summary?.recent?.length ? (
            <ul className="space-y-1">{summary.recent.map((a) => <li key={a.registration}><button type="button" onClick={() => setSelected(aircraft?.find((x) => x.registration === a.registration)?.id)} className="font-mono font-medium text-steel-700 hover:underline">{a.registration}</button> <span className="text-gray-500">{a.operator} - {a.model} - {a.callsign || '-'} - {when(a.last_seen)}</span></li>)}</ul>
          ) : <p className="text-gray-500">No listed aircraft observed yet. Iranian and Russian sanctioned airframes fly irregularly; the first sightings usually arrive within a day.</p>}
          {selected && sightings && (
            <div className="mt-3">
              <div className="card-title mb-1">Track ({sightings.length} fixes)</div>
              <ul className="max-h-48 overflow-y-auto space-y-0.5">{sightings.map((s) => <li key={s.id}><span className="text-gray-500">{when(s.timestamp)}</span> {s.callsign || '-'} {s.altitude_ft ? `${s.altitude_ft} ft` : 'ground'} {s.nearest_place || `${s.latitude?.toFixed(2)}, ${s.longitude?.toFixed(2)}`} <span className="text-gray-400">{s.source}</span></li>)}</ul>
            </div>
          )}
        </div>
      </div>
      <div className="card overflow-x-auto">
        <div className="card-title mb-2">Watched airframes ({aircraft?.length || 0})</div>
        <table className="w-full text-xs">
          <thead className="text-left text-gray-500 border-b border-gray-200"><tr><th className="py-1 pr-2 font-medium">Registration</th><th className="py-1 pr-2 font-medium">Mode S</th><th className="py-1 pr-2 font-medium">Model</th><th className="py-1 pr-2 font-medium">Operator</th><th className="py-1 pr-2 font-medium">Country</th><th className="py-1 pr-2 font-medium">Programmes</th><th className="py-1 pr-2 font-medium">Last seen</th><th className="py-1 font-medium text-right">Fixes</th></tr></thead>
          <tbody>{(aircraft || []).map((a) => (
            <tr key={a.id} onClick={() => setSelected(a.id)} className={clsx('border-b border-gray-100 cursor-pointer hover:bg-gray-50', selected === a.id && 'bg-steel-50')}>
              <td className="py-1 pr-2 font-mono font-medium">{a.registration}</td><td className="py-1 pr-2 font-mono text-gray-500">{a.icao_hex || '-'}</td><td className="py-1 pr-2">{a.model || '-'}</td><td className="py-1 pr-2">{a.operator || '-'}</td><td className="py-1 pr-2">{a.country || '-'}</td>
              <td className="py-1 pr-2 text-gray-500">{(a.programs || []).join(', ')}</td><td className="py-1 pr-2 text-gray-500">{a.last_seen ? when(a.last_seen) : 'never'}</td><td className="py-1 text-right font-mono">{a.sightings_count || 0}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}

function Leaks() {
  const [relevance, setRelevance] = useState('');
  const { data: summary, refetch: r1 } = useFetch('/api/leaks/summary?days=30', 60000);
  const { data: events, refetch: r2 } = useFetch(`/api/leaks/events?days=30&limit=200${relevance ? `&relevance=${relevance}` : ''}`, 60000);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {summary && <span className="card px-3 py-2"><b>{summary.events}</b> relevant events / 30 d - <b>{summary.tracked_company_hits}</b> tracked-company hits - actors: {(summary.top_actors || []).slice(0, 4).map((a) => `${a.actor} ${a.events}`).join(', ') || '-'}</span>}
        <select value={relevance} onChange={(e) => setRelevance(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white"><option value="">all relevance</option>{['sanctioned_party', 'tracked_company', 'watch_keyword', 'critical_sector', 'general'].map((r) => <option key={r} value={r}>{label(r)}</option>)}</select>
        <span className="ml-auto" /><RunButton path="/api/leaks/refresh" label="Fetch now" onDone={() => { r1(); r2(); }} />
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-gray-500 border-b border-gray-200"><tr><th className="py-1 pr-2 font-medium">Severity</th><th className="py-1 pr-2 font-medium">Victim</th><th className="py-1 pr-2 font-medium">Country</th><th className="py-1 pr-2 font-medium">Sector</th><th className="py-1 pr-2 font-medium">Actor / source</th><th className="py-1 pr-2 font-medium">Relevance</th><th className="py-1 font-medium">Date</th></tr></thead>
          <tbody>{(events || []).map((e) => (
            <tr key={e.id} className="border-b border-gray-100">
              <td className="py-1 pr-2"><StatusBadge tone={SEVERITY_TONE[e.severity] || 'neutral'}>{e.severity}</StatusBadge></td>
              <td className="py-1 pr-2"><div className="font-medium">{e.url ? <a href={e.url} target="_blank" rel="noreferrer noopener" className="hover:underline">{e.victim_name}</a> : e.victim_name}</div><div className="text-gray-500">{e.victim_domain}{e.records_affected ? ` - ${e.records_affected.toLocaleString()} records` : ''}</div></td>
              <td className="py-1 pr-2">{e.country || '-'}</td><td className="py-1 pr-2">{e.sector || '-'}</td><td className="py-1 pr-2">{e.threat_actor || e.source}</td>
              <td className="py-1 pr-2"><div>{label(e.relevance)} {Math.round((e.relevance_score || 0) * 100)}%</div><div className="text-gray-500">{(e.details?.reasons || []).join('; ')}</div></td>
              <td className="py-1 text-gray-500 whitespace-nowrap">{e.event_date ? new Date(e.event_date).toLocaleDateString() : '-'}</td>
            </tr>
          ))}{!events?.length && <tr><td colSpan={7} className="py-2 text-gray-500">No relevant breach events in the window.</td></tr>}</tbody>
        </table>
      </div>
    </div>
  );
}

function Narratives() {
  const { data: summary, refetch: r1 } = useFetch('/api/narratives/summary?days=7', 60000);
  const { data: rows, refetch: r2 } = useFetch('/api/narratives/?days=7&limit=60', 60000);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {summary && <span className="card px-3 py-2"><b>{summary.narratives}</b> narratives / 7 d from <b>{summary.state_media_items}</b> state-media items - {Object.entries(summary.by_divergence || {}).map(([k, n]) => `${label(k)} ${n}`).join(', ') || '-'}</span>}
        <span className="ml-auto" /><RunButton path="/api/narratives/refresh" label="Cluster now" onDone={() => { r1(); r2(); }} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {(rows || []).map((n) => (
          <div key={n.id} className="card text-xs">
            <div className="flex flex-wrap items-center gap-2 mb-1"><StatusBadge tone={n.divergence === 'state_only' ? 'error' : n.divergence === 'amplified' ? 'warn' : 'neutral'}>{label(n.divergence)}</StatusBadge><span className="font-medium">{n.topic}</span><span className="text-gray-500 ml-auto">score {Math.round((n.score || 0) * 100)}%</span></div>
            <div className="text-gray-600">{n.assessment}</div>
            <ul className="mt-1 space-y-0.5">{(n.sample_titles || []).slice(0, 4).map((t, i) => <li key={i} className="text-gray-700">{n.sample_urls?.[i] ? <a href={n.sample_urls[i]} target="_blank" rel="noreferrer noopener" className="hover:underline">{t}</a> : t}</li>)}</ul>
            <div className="text-gray-400 mt-1">{when(n.first_seen)} → {when(n.last_seen)} - {(n.countries || []).join(', ')}</div>
          </div>
        ))}
        {!rows?.length && <div className="card text-sm text-gray-500">No state-media narrative clusters yet - RT / TASS / Global Times headlines are clustered every 30 minutes.</div>}
      </div>
    </div>
  );
}

function Infra() {
  const [live, setLive] = useState('true');
  const { data: summary, refetch: r1 } = useFetch('/api/infra/summary', 60000);
  const { data: assets, refetch: r2 } = useFetch(`/api/infra/assets?limit=300${live ? `&live=${live}` : ''}`, 60000);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {summary && <span className="card px-3 py-2"><b>{summary.assets}</b> domains from listings - <b>{summary.checked}</b> checked - <b>{summary.live}</b> live - hosting: {(summary.hosting_countries || []).slice(0, 5).map((c) => `${c.country} ${c.assets}`).join(', ') || '-'}</span>}
        <select value={live} onChange={(e) => setLive(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white"><option value="true">live only</option><option value="false">dead only</option><option value="">all</option></select>
        <span className="ml-auto" /><RunButton path="/api/infra/refresh?job=footprint" label="Footprint batch" onDone={() => { r1(); r2(); }} />
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-gray-500 border-b border-gray-200"><tr><th className="py-1 pr-2 font-medium">Domain</th><th className="py-1 pr-2 font-medium">Listed party</th><th className="py-1 pr-2 font-medium">Resolves</th><th className="py-1 pr-2 font-medium">Hosting</th><th className="py-1 pr-2 font-medium">Registrar</th><th className="py-1 pr-2 font-medium text-right">Certs</th><th className="py-1 pr-2 font-medium text-right">Risk</th><th className="py-1 font-medium">Findings</th></tr></thead>
          <tbody>{(assets || []).map((a) => (
            <tr key={a.id} className="border-b border-gray-100">
              <td className="py-1 pr-2 font-mono"><a href={`https://crt.sh/?q=${a.value}`} target="_blank" rel="noreferrer noopener" className="hover:underline">{a.value}</a></td>
              <td className="py-1 pr-2 max-w-[220px] truncate" title={a.entity_name || ''}>{a.entity_name || '-'}</td>
              <td className="py-1 pr-2 font-mono text-gray-600">{a.is_live == null ? 'unchecked' : a.is_live ? (a.resolves_to || []).slice(0, 2).join(', ') : 'no'}</td>
              <td className="py-1 pr-2">{a.hosting_country || '-'} {a.asn_org ? <span className="text-gray-500">{a.asn_org}</span> : null}</td>
              <td className="py-1 pr-2 text-gray-500 max-w-[160px] truncate">{a.registrar || '-'}</td>
              <td className="py-1 pr-2 text-right font-mono">{a.certificate_count ?? '-'}</td>
              <td className="py-1 pr-2 text-right font-mono">{a.risk_score != null ? Math.round(a.risk_score * 100) + '%' : '-'}</td>
              <td className="py-1 text-gray-500">{(a.findings || []).join('; ')}</td>
            </tr>
          ))}{!assets?.length && <tr><td colSpan={8} className="py-2 text-gray-500">Nothing footprinted yet - domains are checked in batches of 15 every 20 minutes.</td></tr>}</tbody>
        </table>
      </div>
    </div>
  );
}

function Legal() {
  const [matched, setMatched] = useState(false);
  const { data: summary, refetch: r1 } = useFetch('/api/legal/summary?days=365', 60000);
  const { data: events, refetch: r2 } = useFetch(`/api/legal/events?days=365&limit=200${matched ? '&matched_only=true' : ''}`, 60000);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {summary && <span className="card px-3 py-2"><b>{summary.events}</b> events / 12 mo - {Object.entries(summary.by_source || {}).map(([k, n]) => `${label(k)} ${n}`).join(', ') || '-'} - OFAC penalties {usd(summary.penalties_usd)} - <b>{summary.docket_matches_total}</b> dockets naming listed parties</span>}
        <label className="flex items-center gap-1"><input type="checkbox" checked={matched} onChange={(e) => setMatched(e.target.checked)} /> listed parties only</label>
        <span className="ml-auto" /><RunButton path="/api/legal/refresh?job=all" label="Fetch now" onDone={() => { r1(); r2(); }} />
      </div>
      <div className="card">
        <ul className="space-y-1 text-xs">
          {(events || []).map((e) => (
            <li key={e.id} className="border border-gray-200 rounded px-2 py-1">
              <div className="flex flex-wrap items-center gap-2"><StatusBadge tone={e.matched_entity_id ? 'error' : e.source === 'ofac_enforcement' ? 'warn' : 'neutral'}>{label(e.event_type)}</StatusBadge><span className="text-gray-500">{e.source} - {e.court || ''} - {e.event_date ? new Date(e.event_date).toLocaleDateString() : ''}</span>{e.penalty_usd ? <span className="font-mono">{usd(e.penalty_usd)}</span> : null}</div>
              <div className="font-medium">{e.url ? <a href={e.url} target="_blank" rel="noreferrer noopener" className="hover:underline inline-flex items-center gap-1">{e.title} <ExternalLink size={10} aria-hidden="true" /></a> : e.title}</div>
              {e.matched_entity_name && <div className="text-red-700">names listed party {e.matched_entity_name}</div>}
              {e.summary && <div className="text-gray-600">{e.summary}</div>}
            </li>
          ))}
          {!events?.length && <li className="text-sm text-gray-500">No legal events yet - OFAC penalties and DOJ releases are polled every 6 h, CourtListener dockets for listed parties every 30 min.</li>}
        </ul>
      </div>
    </div>
  );
}


function PortStateControl() {
  const [view, setView] = useState('flagged');
  const { data: summary, refetch: r1 } = useFetch('/api/psc/summary?days=90', 60000);
  const params = view === 'flagged' ? '&flagged_only=true' : view === 'tankers' ? '&tankers_only=true' : view === 'bans' ? '&event_type=ban' : view === 'matched' ? '&matched_only=true' : '';
  const { data: events, refetch: r2 } = useFetch(`/api/psc/events?days=90&limit=300${params}`, 60000);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {summary && <span className="card px-3 py-2"><b>{summary.events}</b> PSC events / 90 d ({Object.entries(summary.by_source || {}).map(([k, n]) => `${label(k)} ${n}`).join(', ') || '-'}) - <b>{summary.matched_vessels}</b> on tracked hulls - <b>{summary.flagged_vessels}</b> on flagged hulls - <b>{summary.bans_on_record}</b> bans on record - flags: {(summary.top_flags || []).slice(0, 5).map((f) => `${f.flag} ${f.events}`).join(', ')}</span>}
        <select value={view} onChange={(e) => setView(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white"><option value="flagged">flagged hulls</option><option value="matched">tracked hulls</option><option value="tankers">tankers</option><option value="bans">bans</option><option value="all">all</option></select>
        <span className="ml-auto" /><RunButton path="/api/psc/refresh" label="Fetch now" onDone={() => { r1(); r2(); }} />
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-gray-500 border-b border-gray-200"><tr><th className="py-1 pr-2 font-medium">Type</th><th className="py-1 pr-2 font-medium">Ship</th><th className="py-1 pr-2 font-medium">Flag</th><th className="py-1 pr-2 font-medium">Ship type</th><th className="py-1 pr-2 font-medium">Port</th><th className="py-1 pr-2 font-medium">Date</th><th className="py-1 pr-2 font-medium">Company</th><th className="py-1 font-medium">Deficiencies</th></tr></thead>
          <tbody>{(events || []).map((e) => (
            <tr key={e.id} className={clsx('border-b border-gray-100', e.vessel_flagged && 'bg-red-50/40')}>
              <td className="py-1 pr-2"><StatusBadge tone={e.event_type === 'ban' ? 'error' : e.vessel_flagged ? 'error' : 'warn'}>{e.event_type}</StatusBadge> <span className="text-gray-400">{label(e.source)}</span></td>
              <td className="py-1 pr-2"><div className="font-medium">{e.vessel_mmsi ? <a href={`/maritime/vessel/${e.vessel_mmsi}`} className="text-steel-700 hover:underline">{e.ship_name}</a> : e.ship_name}</div><div className="text-gray-500 font-mono">IMO {e.imo || '-'}{e.vessel_flagged ? ' - flagged in VELES' : e.vessel_id ? ' - tracked' : ''}</div></td>
              <td className="py-1 pr-2">{e.flag || '-'}</td><td className="py-1 pr-2">{e.ship_type || '-'}</td>
              <td className="py-1 pr-2">{e.port || '-'} <span className="text-gray-500">{e.port_country || ''}</span></td>
              <td className="py-1 pr-2 whitespace-nowrap text-gray-500">{e.event_date ? new Date(e.event_date).toLocaleDateString() : '-'}{e.release_date ? ` → ${new Date(e.release_date).toLocaleDateString()}` : ''}</td>
              <td className="py-1 pr-2 max-w-[180px] truncate" title={e.company || ''}>{e.company || '-'}</td>
              <td className="py-1 text-gray-500 max-w-[320px]"><div className="truncate" title={(e.deficiencies || []).join(' | ')}>{e.deficiency_count ? `${e.deficiency_count}: ${(e.deficiencies || []).slice(0, 2).map((d) => d.split(' - ').slice(1).join(' - ')).join('; ')}` : (e.details?.ban_reason?.description || '-')}</div></td>
            </tr>
          ))}{!events?.length && <tr><td colSpan={8} className="py-2 text-gray-500">No port state control records in this view yet - Paris MoU (THETIS) and Tokyo MoU (APCIS) are polled every 6 hours.</td></tr>}</tbody>
        </table>
      </div>
    </div>
  );
}

const TABS = [['aviation', 'Aviation', Plane], ['psc', 'Port state control', Anchor], ['leaks', 'Leaks & breaches', ShieldAlert], ['narratives', 'Narratives', Megaphone], ['infra', 'Domains & hosting', Globe2], ['legal', 'Legal & enforcement', Gavel]];

export default function Monitors() {
  const [tab, setTab] = useState('aviation');
  return (
    <div>
      <PageHeader title="Monitors" subtitle="Tier 2 / 3 collectors: sanctioned aircraft on ADS-B, port state control detentions and bans, ransomware and breach postings, state-media narratives, listed parties' web infrastructure, courts and enforcement" />
      <div className="card mb-4"><div className="flex flex-wrap gap-1 text-xs">{TABS.map(([key, text, Icon]) => <button key={key} type="button" onClick={() => setTab(key)} className={clsx('px-2 py-1 rounded border inline-flex items-center gap-1', tab === key ? 'bg-steel-700 text-white border-steel-700' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-100')}><Icon size={12} aria-hidden="true" /> {text}</button>)}</div></div>
      {tab === 'aviation' && <Aviation />}
      {tab === 'psc' && <PortStateControl />}
      {tab === 'leaks' && <Leaks />}
      {tab === 'narratives' && <Narratives />}
      {tab === 'infra' && <Infra />}
      {tab === 'legal' && <Legal />}
    </div>
  );
}
