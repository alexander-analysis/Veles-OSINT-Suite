import { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import { Bar } from 'react-chartjs-2';
import 'leaflet/dist/leaflet.css';
import { Fuel, RefreshCw, Droplets, AlertTriangle, Factory } from 'lucide-react';
import clsx from 'clsx';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useFetch } from '../hooks/useFetch';
import { apiPost } from '../services/api';
import { baseOptions } from '../services/charts';

const TYPE_COLOR = { crude_export: '#c0392b', product_export: '#d35400', lng_export: '#8e44ad', refinery: '#7f8c8d', import_terminal: '#2471a3', sts_hub: '#b7950b' };
const SEVERITY_TONE = { critical: 'error', high: 'error', medium: 'warn', low: 'neutral' };
const STATUS_TONE = { underway: 'warn', discharged: 'ok', transshipped: 'error', stale: 'neutral' };
const label = (s) => (s || '').replace(/_/g, ' ');
const when = (iso) => (iso ? new Date(iso).toLocaleString() : '-');
const bbl = (v) => (v == null ? '-' : `${Math.round(v / 1000).toLocaleString()}k bbl`);

function InvalidateOnMount() {
  const map = useMap();
  useEffect(() => {
    const timers = [50, 300, 1000].map((ms) => setTimeout(() => map.invalidateSize(), ms));
    return () => timers.forEach(clearTimeout);
  }, [map]);
  return null;
}

function FacilityMap({ features, onSelect }) {
  return (
    <MapContainer center={[35, 40]} zoom={2} minZoom={1} worldCopyJump className="h-[380px] w-full rounded" scrollWheelZoom>
      <InvalidateOnMount />
      <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {features.map((f) => {
        const p = f.properties;
        const [lon, lat] = f.geometry.coordinates;
        const radius = 4 + Math.min(10, Math.sqrt(p.calls_30d || 0) * 2);
        return (
          <CircleMarker key={p.id} center={[lat, lon]} radius={radius} pathOptions={{ color: p.sanctioned ? '#c0392b' : TYPE_COLOR[p.type] || '#555', fillColor: TYPE_COLOR[p.type] || '#555', fillOpacity: 0.6, weight: p.sanctioned ? 2 : 1 }} eventHandlers={{ click: () => onSelect(p.id) }}>
            <Popup>
              <div className="text-xs max-w-[240px]">
                <div className="font-semibold">{p.name}</div>
                <div className="text-gray-500">{label(p.type)} - {p.country} - {p.commodity}{p.sanctioned ? ' - sanctioned' : ''}</div>
                <div>{p.calls_7d || 0} tanker calls / 7 d - {p.calls_30d || 0} / 30 d</div>
                {p.note && <div className="text-gray-500 mt-1">{p.note}</div>}
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}

function FlowChart({ context }) {
  const series = context?.series || [];
  if (!series.length) return <p className="text-sm text-gray-500">No flow snapshots yet - they build up as tankers call at the tracked facilities.</p>;
  const labels = series.map((s) => s.day.slice(5));
  const data = {
    labels,
    datasets: [
      { type: 'bar', label: 'Laden departures (sanctioned facilities)', data: series.map((s) => s.laden_departures), backgroundColor: 'rgba(192,57,43,0.6)', yAxisID: 'y' },
      { type: 'bar', label: 'Flagged tankers', data: series.map((s) => s.flagged), backgroundColor: 'rgba(183,149,11,0.6)', yAxisID: 'y' },
      { type: 'line', label: `${context.price_asset || 'Oil'} (USD)`, data: series.map((s) => s.price), borderColor: '#2471a3', backgroundColor: '#2471a3', pointRadius: 2, tension: 0.2, yAxisID: 'y1', spanGaps: true },
    ],
  };
  const options = { ...baseOptions, scales: { ...baseOptions.scales, y: { ...baseOptions.scales.y, position: 'left', beginAtZero: true }, y1: { position: 'right', grid: { display: false }, ticks: { font: { size: 10 } } } } };
  return (
    <div>
      <div className="h-56"><Bar data={data} options={options} /></div>
      <div className="text-xs text-gray-500 mt-1">Correlation laden departures vs price: {context.correlation_departures_price == null ? 'n/a (needs 5+ days with prices)' : context.correlation_departures_price}</div>
    </div>
  );
}

function FacilityDetail({ id, onClose }) {
  const { data, loading } = useFetch(id ? `/api/energy/facilities/${id}?days=30` : null, 0);
  if (!id) return null;
  if (loading && !data) return <div className="card"><LoadingSpinner label="Loading facility" /></div>;
  if (!data) return null;
  const f = data.facility;
  return (
    <div className="card space-y-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap gap-1"><StatusBadge tone={f.is_sanctioned_facility ? 'error' : 'neutral'}>{f.is_sanctioned_facility ? `sanctioned (${f.sanctioning_authority || '-'})` : label(f.facility_type)}</StatusBadge>{f.owner_sanctioned && <StatusBadge tone="error">owner listed</StatusBadge>}</div>
          <h3 className="text-base font-semibold mt-1">{f.facility_name}</h3>
          <div className="text-xs text-gray-500">{[f.country, label(f.facility_type), f.commodity, f.operator_name && `operator ${f.operator_name}`, f.owner_name && `owner ${f.owner_name}`].filter(Boolean).join(' - ')}</div>
          {f.notes && <div className="text-xs text-gray-600 mt-1">{f.notes}</div>}
        </div>
        <button type="button" onClick={onClose} className="text-xs text-gray-500 hover:underline">close</button>
      </div>
      <table className="kv-table">
        <tbody>
          <tr><td>Capacity</td><td>{f.production_capacity_bpd ? `${(f.production_capacity_bpd / 1000).toLocaleString()} kb/d` : f.production_capacity_mtpa ? `${f.production_capacity_mtpa} mtpa` : '-'}{f.estimated_utilization != null && <span className="text-gray-500"> - est. utilisation {Math.round(f.estimated_utilization * 100)}%</span>}</td></tr>
          <tr><td>Tanker calls</td><td>{f.tanker_calls_7d || 0} / 7 d - {f.tanker_calls_30d || 0} / 30 d</td></tr>
          <tr><td>Last activity</td><td>{when(f.last_activity_at)}</td></tr>
          <tr><td>Watch radius</td><td>{f.radius_km} km</td></tr>
        </tbody>
      </table>
      <div className="text-xs">
        <div className="card-title mb-1">Recent calls ({data.recent_calls.length})</div>
        {data.recent_calls.length ? (
          <ul className="space-y-0.5 max-h-56 overflow-y-auto">
            {data.recent_calls.map((c) => (
              <li key={c.id} className="flex flex-wrap gap-x-2">
                <a href={`/maritime/vessel/${c.mmsi}`} className="font-medium text-steel-700 hover:underline">{c.vessel_name}</a>
                <span className="text-gray-500">{c.flag} - {c.ship_type}</span>
                <span className="text-gray-500">{new Date(c.arrival_time).toLocaleDateString()}{c.departure_time ? ` → ${new Date(c.departure_time).toLocaleDateString()}` : ' (in port)'}</span>
                {c.draught_arrival && <span className="text-gray-400">draught {c.draught_arrival}{c.draught_departure ? ` → ${c.draught_departure}` : ''} m</span>}
                {c.sanctioned_status && c.sanctioned_status !== 'clear' && <StatusBadge tone="error">{c.sanctioned_status}</StatusBadge>}
              </li>
            ))}
          </ul>
        ) : <p className="text-gray-500">No tanker calls recorded in the last 30 days.</p>}
      </div>
    </div>
  );
}

export default function Energy() {
  const [days, setDays] = useState(30);
  const [selected, setSelected] = useState(null);
  const [shipFilter, setShipFilter] = useState('sanctioned');
  const [starting, setStarting] = useState(false);

  const shipParams = useMemo(() => {
    const p = new URLSearchParams({ days: String(days), limit: '100' });
    if (shipFilter === 'sanctioned') p.set('sanctioned_only', 'true');
    if (shipFilter === 'dark') p.set('dark_oil_only', 'true');
    return p.toString();
  }, [days, shipFilter]);

  const { data: summary, refetch: refetchSummary } = useFetch(`/api/energy/summary?days=7`, 60000);
  const { data: geojson, refetch: refetchGeo } = useFetch('/api/energy/facilities/geojson', 120000);
  const { data: shipments, refetch: refetchShipments } = useFetch(`/api/energy/shipments?${shipParams}`, 60000);
  const { data: dark, refetch: refetchDark } = useFetch(`/api/energy/dark-oil?days=${days}&limit=60`, 60000);
  const { data: context } = useFetch(`/api/energy/price-context?days=${Math.max(7, days)}`, 300000);
  const { data: status } = useFetch('/api/energy/status', 30000);

  const refreshAll = () => { refetchSummary(); refetchGeo(); refetchShipments(); refetchDark(); };
  const runNow = async () => {
    setStarting(true);
    try {
      await apiPost('/api/energy/refresh?job=all', {});
      setTimeout(refreshAll, 12000);
    } catch (err) {
      alert(err.message);
    } finally {
      setStarting(false);
    }
  };
  const setStatus = async (id, value) => {
    try {
      await apiPost(`/api/energy/dark-oil/${id}/status?status=${value}`, {});
      refetchDark();
    } catch (err) {
      alert(err.message);
    }
  };

  const indicators = summary?.dark_oil_indicators || {};
  const indicatorTotal = Object.values(indicators).reduce((s, n) => s + n, 0);

  return (
    <div>
      <PageHeader title="Energy Flow Monitor" subtitle="Tanker traffic at sanctioned export terminals, STS anchorages and discharge hubs - shipments reconstructed from AIS calls and draught, dark-oil indicators, price context">
        {status?.last_run?.visits && <span className="text-xs text-gray-500">Facility sweep {new Date(status.last_run.visits).toLocaleTimeString()}</span>}
        <button type="button" onClick={runNow} disabled={starting} className="flex items-center gap-1 px-2 py-1 rounded border border-gray-300 bg-white text-xs hover:bg-gray-100 disabled:opacity-50">
          <RefreshCw size={12} className={starting ? 'animate-spin' : ''} aria-hidden="true" /> Run now
        </button>
      </PageHeader>

      {summary && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5 mb-4">
          <div className="card py-3"><div className="card-title">Facilities watched</div><div className="text-xl font-semibold mt-1">{summary.facilities}</div><div className="text-xs text-gray-500">{summary.facilities_sanctioned} sanctioned - {summary.tankers_at_facilities_now} tankers alongside now</div></div>
          <div className="card py-3"><div className="card-title">Shipments (7 d)</div><div className="text-xl font-semibold mt-1">{summary.shipments}</div><div className="text-xs text-gray-500">{summary.sanctioned_shipments} from sanctioned facilities - {bbl(summary.sanctioned_barrels)}</div></div>
          <div className="card py-3"><div className="card-title">Dark-oil indicators (7 d)</div><div className="text-xl font-semibold mt-1">{indicatorTotal}</div><div className="text-xs text-gray-500">{Object.entries(indicators).map(([k, n]) => `${label(k)} ${n}`).join(' - ') || 'none'}</div></div>
          <div className="card py-3"><div className="card-title">Origins → destinations</div><div className="text-xs mt-1">{Object.entries(summary.by_origin || {}).map(([c, n]) => `${c} ${n}`).join(' - ') || '-'}</div><div className="text-xs text-gray-500">→ {Object.entries(summary.by_destination || {}).map(([c, n]) => `${c} ${n}`).join(' - ') || 'no discharges yet'}</div></div>
          <div className="card py-3"><div className="card-title">Most active</div><div className="text-xs mt-1 space-y-0.5">{(summary.most_active || []).slice(0, 4).map((f) => <div key={f.facility}><button type="button" onClick={() => setSelected(geojson?.features?.find((x) => x.properties.name === f.facility)?.properties.id)} className="text-steel-700 hover:underline">{f.facility}</button> <span className="text-gray-500">{f.calls_7d} / 7 d</span></div>)}{!summary.most_active?.length && <span className="text-gray-500">no tanker calls yet</span>}</div></div>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2 space-y-4">
          <div className="card p-2">
            <FacilityMap features={geojson?.features || []} onSelect={setSelected} />
            <div className="text-xs text-gray-500 mt-1 px-1 flex flex-wrap gap-x-3">{Object.entries(TYPE_COLOR).map(([t, c]) => <span key={t}><span className="inline-block h-2 w-2 rounded-full mr-1" style={{ background: c }} aria-hidden="true" />{label(t)}</span>)}<span>red outline = sanctioned facility - size = 30-day tanker calls</span></div>
          </div>
          <div className="card">
            <div className="flex items-center justify-between mb-2">
              <span className="card-title flex items-center gap-1"><Droplets size={12} aria-hidden="true" /> Sanctioned-facility departures vs price</span>
              <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="border border-gray-300 rounded px-1 py-0.5 text-xs bg-white">{[7, 14, 30, 60, 90].map((d) => <option key={d} value={d}>{d} d</option>)}</select>
            </div>
            <FlowChart context={context} />
          </div>
          <div className="card overflow-x-auto">
            <div className="flex items-center justify-between mb-2">
              <span className="card-title flex items-center gap-1"><Fuel size={12} aria-hidden="true" /> Shipments ({shipments?.total ?? 0})</span>
              <select value={shipFilter} onChange={(e) => setShipFilter(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 text-xs bg-white"><option value="sanctioned">sanctioned routes</option><option value="dark">dark-oil suspects</option><option value="all">all</option></select>
            </div>
            <table className="w-full text-xs">
              <thead className="text-left text-gray-500 border-b border-gray-200"><tr><th className="py-1 pr-2 font-medium">Vessel</th><th className="py-1 pr-2 font-medium">Loaded</th><th className="py-1 pr-2 font-medium">Cargo</th><th className="py-1 pr-2 font-medium">Discharge</th><th className="py-1 pr-2 font-medium">Status</th><th className="py-1 font-medium text-right">Risk</th></tr></thead>
              <tbody>
                {(shipments?.shipments || []).map((s) => (
                  <tr key={s.id} className="border-b border-gray-100">
                    <td className="py-1 pr-2"><a href={`/maritime/vessel/${s.mmsi}`} className="font-medium text-steel-700 hover:underline">{s.vessel_name}</a> <span className="text-gray-500">{s.flag}</span>{s.dark_oil_suspect && <AlertTriangle size={11} className="inline ml-1 text-red-700" aria-hidden="true" />}</td>
                    <td className="py-1 pr-2">{s.loading_location} <span className="text-gray-500">{s.origin_country} - {new Date(s.loading_date).toLocaleDateString()}</span></td>
                    <td className="py-1 pr-2">{s.cargo_type} {s.laden === true ? bbl(s.cargo_volume_barrels) : s.laden === false ? '(ballast)' : ''}</td>
                    <td className="py-1 pr-2">{s.discharge_location ? `${s.discharge_location} (${s.destination_country || '?'})` : <span className="text-gray-400">underway</span>}</td>
                    <td className="py-1 pr-2"><StatusBadge tone={STATUS_TONE[s.status] || 'neutral'}>{s.status}</StatusBadge></td>
                    <td className="py-1 text-right font-mono">{s.risk_score != null ? Math.round(s.risk_score * 100) + '%' : '-'}</td>
                  </tr>
                ))}
                {!shipments?.shipments?.length && <tr><td colSpan={6} className="py-2 text-gray-500">No shipments reconstructed yet. A shipment needs a tanker to leave a tracked export facility (or STS hub) with a laden draught - the global AIS feed produces the first ones within hours.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
        <div className="space-y-4">
          {selected ? <FacilityDetail id={selected} onClose={() => setSelected(null)} /> : (
            <div className="card text-sm text-gray-500"><Factory size={14} className="inline mr-1" aria-hidden="true" />Select a facility on the map for its recent tanker calls, draught changes, shipments and utilisation. Facilities are curated in <code>backend/app/data/energy_facilities.py</code>.</div>
          )}
          <div className="card">
            <div className="card-title mb-2 flex items-center gap-1"><AlertTriangle size={12} aria-hidden="true" /> Dark-oil indicators ({dark?.total ?? 0})</div>
            {dark?.indicators?.length ? (
              <ul className="space-y-1 text-xs max-h-[560px] overflow-y-auto">
                {dark.indicators.map((i) => (
                  <li key={i.id} className={clsx('border rounded px-2 py-1', i.investigation_status === 'cleared' ? 'border-gray-200 opacity-60' : 'border-gray-200')}>
                    <div className="flex items-center justify-between gap-2"><span className="font-medium">{label(i.detected_pattern)}</span><StatusBadge tone={SEVERITY_TONE[i.severity] || 'neutral'}>{i.severity} {Math.round((i.confidence_score || 0) * 100)}%</StatusBadge></div>
                    <div className="text-gray-700">{i.summary}</div>
                    <div className="text-gray-500 flex flex-wrap gap-x-2 mt-0.5">
                      <a href={`/maritime/vessel/${i.mmsi}`} className="text-steel-700 hover:underline">{i.mmsi}</a>
                      <span>{when(i.detected_at)}</span>
                      {i.suspected_origin && <span>origin {i.suspected_origin}</span>}
                      <span className="ml-auto">{i.investigation_status}</span>
                      {i.investigation_status !== 'cleared' && <button type="button" onClick={() => setStatus(i.id, 'investigating')} className="hover:underline">investigate</button>}
                      {i.investigation_status !== 'cleared' && <button type="button" onClick={() => setStatus(i.id, 'cleared')} className="hover:underline">clear</button>}
                    </div>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-gray-500">No indicators in the window.</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
