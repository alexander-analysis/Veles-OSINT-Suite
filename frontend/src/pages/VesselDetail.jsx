import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import clsx from 'clsx';
import { ArrowLeft, Play, Pause } from 'lucide-react';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import VesselMap from '../components/maritime/VesselMap';
import AuditLog from '../components/intelligence/AuditLog';
import WatchButton from '../components/common/WatchButton';
import { statusTone } from '../components/maritime/VesselTable';
import { useFetch } from '../hooks/useFetch';

const AUTHORITY_TONE = { OFAC: 'error', EU: 'warn', UN: 'neutral' };

function Field({ label, value }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="font-medium">{value ?? '-'}</td>
    </tr>
  );
}

const fmtDate = (d) => (d ? new Date(d).toLocaleDateString() : '-');

function CrossDomain({ dossier }) {
  if (!dossier) return null;
  const psc = dossier.port_state_control || [];
  const shipments = dossier.shipments || [];
  const dark = dossier.dark_oil_indicators || [];
  const links = dossier.fusion_links || [];
  const listed = dossier.listings_by_imo || [];
  const clusters = dossier.spoofing_clusters || [];
  const empty = psc.length + shipments.length + dark.length + links.length + listed.length + clusters.length === 0;
  return (
    <div className="card mb-4">
      <div className="card-title mb-2">Cross-domain dossier</div>
      {empty ? <p className="text-sm text-gray-500">No port state control record, oil shipment, dark-oil indicator, listing by IMO or fusion link touches this hull.</p> : (
        <div className="grid gap-4 xl:grid-cols-2 text-sm">
          {listed.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-red-700 mb-1">Listed by IMO ({listed.length})</div>
              <ul className="space-y-1">{listed.map((e) => <li key={e.id}><StatusBadge tone={AUTHORITY_TONE[e.authority]}>{e.authority}</StatusBadge> <Link to={`/sanctions?entity=${e.id}`} className="font-medium text-steel-700 hover:underline">{e.name}</Link> <span className="text-xs text-gray-500">{(e.programs || []).join(', ')}{e.vessel_owner ? ` - owner ${e.vessel_owner}` : ''}</span></li>)}</ul>
            </div>
          )}
          {psc.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-steel-700 mb-1">Port state control ({psc.length})</div>
              <ul className="space-y-1">{psc.map((p) => <li key={p.id}><span className="text-xs text-gray-500">{fmtDate(p.event_date)}</span> <span className={clsx('font-medium', p.event_type === 'ban' ? 'text-red-700' : '')}>{p.event_type}</span> by {p.source.replace('_', ' ')}{p.port ? ` at ${p.port}` : ''}{p.port_country ? ` (${p.port_country})` : ''}{p.deficiency_count ? ` - ${p.deficiency_count} deficiencies` : ''}{p.deficiencies?.length ? <span className="block text-xs text-gray-600">{p.deficiencies.slice(0, 4).join('; ')}</span> : null}</li>)}</ul>
            </div>
          )}
          {shipments.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-steel-700 mb-1">Oil shipments ({shipments.length})</div>
              <ul className="space-y-1">{shipments.slice(0, 10).map((s) => <li key={s.id}><span className="text-xs text-gray-500">{fmtDate(s.loading_date)}</span> {s.loading_location || '?'} ({s.origin_country || '?'}) {'->'} {s.discharge_location || (s.status === 'underway' ? 'underway' : '?')}{s.destination_country ? ` (${s.destination_country})` : ''} - {s.cargo_type || 'cargo'}{s.cargo_volume_barrels ? ` ~${Math.round(s.cargo_volume_barrels / 1000)}k bbl` : ''}{s.sanctioned_route ? <StatusBadge tone="error">sanctioned route</StatusBadge> : null}{s.dark_oil_suspect ? <StatusBadge tone="warn">dark oil</StatusBadge> : null}</li>)}</ul>
            </div>
          )}
          {dark.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-steel-700 mb-1">Dark-oil indicators ({dark.length})</div>
              <ul className="space-y-1">{dark.slice(0, 10).map((d) => <li key={d.id}><span className="text-xs text-gray-500">{new Date(d.detected_at).toLocaleString()}</span> <span className="font-medium">{(d.pattern || '').replace(/_/g, ' ')}</span> ({d.severity}, {Math.round((d.confidence || 0) * 100)}%) - {d.summary}</li>)}</ul>
            </div>
          )}
          {clusters.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-red-700 mb-1">GNSS spoofing clusters ({clusters.length})</div>
              <ul className="space-y-1">{clusters.map((c) => <li key={c.id}><span className="text-xs text-gray-500">{new Date(c.timestamp).toLocaleString()}</span> <span className="font-medium">{c.vessel_count} hulls</span> ({c.severity}{c.inland ? ', on land' : ''}) - {c.summary}</li>)}</ul>
            </div>
          )}
          {links.length > 0 && (
            <div className="xl:col-span-2">
              <div className="text-xs font-semibold text-steel-700 mb-1">Fusion links ({links.length}) <Link to="/fusion" className="font-normal text-steel-600 hover:underline">open fusion</Link></div>
              <ul className="space-y-1">{links.slice(0, 12).map((c) => <li key={c.id}><span className="text-xs text-gray-500">{new Date(c.detected_at).toLocaleString()}</span> <span className="font-medium">{(c.type || '').replace(/_/g, ' ')}</span> ({Math.round((c.confidence || 0) * 100)}%) - {c.a} <span className="text-gray-400">&harr;</span> {c.b}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function VesselDetail() {
  const { mmsi } = useParams();
  const { data, loading, error } = useFetch(`/api/maritime/vessel/${mmsi}`, 60000);
  const { data: dossier } = useFetch(`/api/maritime/vessel/${mmsi}/dossier`, 120000);
  const [frame, setFrame] = useState(null); // replay cursor (null = full track)
  const [playing, setPlaying] = useState(false);
  const timeline = data?.position_timeline || [];

  useEffect(() => {
    if (!playing) return undefined;
    const timer = setInterval(() => {
      setFrame((f) => {
        const next = (f ?? 0) + Math.max(1, Math.floor(timeline.length / 120));
        if (next >= timeline.length) {
          setPlaying(false);
          return null;
        }
        return next;
      });
    }, 100);
    return () => clearInterval(timer);
  }, [playing, timeline.length]);

  const track = useMemo(() => (frame == null ? timeline : timeline.slice(0, frame + 1)), [timeline, frame]);
  const v = data?.vessel;
  const vesselFeature = useMemo(() => {
    const last = track[track.length - 1];
    if (!v || !last) return null;
    return {
      type: 'FeatureCollection',
      features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [last.lon, last.lat] }, properties: { mmsi: v.mmsi, imo: v.imo, name: v.name, flag: v.flag_state, ship_type: v.ship_type, speed: last.speed, sanctioned_status: v.sanctioned_status || 'clear', risk_score: v.risk_score, marker_color: v.sanctioned_status?.startsWith('breach') ? '#e74c3c' : v.sanctioned_status === 'flagged' ? '#f39c12' : '#2ecc71', ais_source: last.source, last_update: last.timestamp } }],
    };
  }, [v, track]);

  if (loading && !data) return <LoadingSpinner label="Loading vessel profile" />;
  if (error) return <div className="card border-red text-red-700 text-sm">{error.message}</div>;
  if (!v) return null;

  return (
    <div>
      <PageHeader title={`${v.name} (${v.flag_state})`} subtitle={`MMSI ${v.mmsi}${v.imo ? ` - IMO ${v.imo}` : ''}${v.call_sign ? ` - call sign ${v.call_sign}` : ''} - ${v.ship_type || 'type unknown'}`}>
        <StatusBadge tone={statusTone(v.sanctioned_status)}>{v.sanctioned_status || 'clear'}</StatusBadge>
        <StatusBadge tone={(v.risk_score || 0) >= 0.6 ? 'error' : (v.risk_score || 0) >= 0.3 ? 'warn' : 'ok'}>risk {Math.round((v.risk_score || 0) * 100)}%</StatusBadge>
        <WatchButton kind="vessel" itemKey={v.mmsi} label={`${v.name} (${v.flag_state})`} />
        <Link to="/maritime" className="text-xs text-steel-600 flex items-center gap-1"><ArrowLeft size={12} aria-hidden="true" /> back to map</Link>
      </PageHeader>

      <div className="grid gap-4 xl:grid-cols-3 mb-4">
        <div className="card xl:col-span-2 p-0 overflow-hidden">
          <VesselMap vessels={vesselFeature} breaches={[]} selectedTrack={track} height="420px" center={track.length ? [track[track.length - 1].lat, track[track.length - 1].lon] : undefined} zoom={7} />
          <div className="flex items-center gap-3 px-3 py-2 text-xs border-t border-gray-200">
            <button type="button" onClick={() => { if (!playing) setFrame(0); setPlaying(!playing); }} className="flex items-center gap-1 px-2 py-1 border border-gray-300 rounded bg-white hover:bg-gray-100" disabled={timeline.length < 2}>
              {playing ? <Pause size={12} aria-hidden="true" /> : <Play size={12} aria-hidden="true" />} {playing ? 'pause' : 'replay track'}
            </button>
            <input type="range" min={0} max={Math.max(0, timeline.length - 1)} value={frame ?? Math.max(0, timeline.length - 1)} onChange={(e) => { setPlaying(false); setFrame(Number(e.target.value)); }} className="flex-1" />
            <span className="text-gray-500 whitespace-nowrap">{track.length ? new Date(track[track.length - 1].timestamp).toLocaleString() : '-'} - {timeline.length} fixes</span>
          </div>
        </div>
        <div className="card">
          <div className="card-title mb-2">Vessel profile</div>
          <table className="kv-table">
            <tbody>
              <Field label="Owner" value={v.owner_name} />
              <Field label="Operator" value={v.registered_operator} />
              <Field label="Beneficial owner" value={v.beneficial_owner} />
              <Field label="Destination" value={v.destination} />
              <Field label="Nav status" value={v.ais_status} />
              <Field label="Speed" value={v.current_speed != null ? `${v.current_speed} kn` : null} />
              <Field label="Last AIS" value={v.last_ais_update ? `${new Date(v.last_ais_update).toLocaleString()} (${v.ais_source})` : null} />
              <Field label="Last port" value={v.last_port_name} />
              <Field label="Former names" value={v.historical_names?.length ? v.historical_names.join(', ') : null} />
              <Field label="Former flags" value={v.historical_flags?.length ? v.historical_flags.join(', ') : null} />
              <Field label="First seen" value={v.created_at ? new Date(v.created_at).toLocaleString() : null} />
            </tbody>
          </table>
          {v.risk_factors && Object.keys(v.risk_factors).length > 0 && (
            <div className="mt-3 text-xs">
              <div className="card-title mb-1">Risk factors</div>
              <ul className="space-y-0.5 text-gray-700">
                {Object.entries(v.risk_factors).map(([k, val]) => <li key={k}>{k.replace(/_/g, ' ')}: <span className="font-mono">{typeof val === 'object' ? JSON.stringify(val) : String(val)}</span></li>)}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2 mb-4">
        <div className="card">
          <div className="card-title mb-2">Sanctions matches ({data.sanctions_matches.length})</div>
          {data.sanctions_matches.length === 0 ? <p className="text-sm text-gray-500">No listing matched this vessel.</p> : (
            <ul className="space-y-2 text-sm">
              {data.sanctions_matches.map((m) => (
                <li key={m.id} className={clsx('border rounded p-2', m.investigation_status === 'cleared' ? 'border-gray-200 opacity-60' : 'border-red bg-red-50')}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <StatusBadge tone={AUTHORITY_TONE[m.sanctioning_authority]}>{m.sanctioning_authority}</StatusBadge>
                    <span className="font-medium">{m.sanctioned_entity}</span>
                    <span className="text-xs text-gray-500">{m.breach_type.replace('_', ' ')} - {Math.round((m.match_confidence || 0) * 100)}% - {m.investigation_status}</span>
                  </div>
                  <div className="text-xs text-gray-600 mt-1">{m.supporting_evidence?.summary}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card">
          <div className="card-title mb-2">Linked vessels ({data.correlated_vessels.length})</div>
          {data.correlated_vessels.length === 0 ? <p className="text-sm text-gray-500">No ownership, sanctions-entity, rendezvous or port linkage found.</p> : (
            <ul className="space-y-1 text-sm">
              {data.correlated_vessels.slice(0, 15).map((c) => (
                <li key={c.mmsi} className="flex flex-wrap items-center gap-2">
                  <Link to={`/maritime/vessel/${c.mmsi}`} className="font-medium text-steel-700 hover:underline">{c.name}</Link>
                  <span className="text-xs text-gray-500">({c.flag}) - {c.reasons.map((r) => r.type.replace(/_/g, ' ')).join(', ')} - strength {Math.round(c.link_strength * 100)}%</span>
                  {c.sanctioned_status && c.sanctioned_status !== 'clear' && <StatusBadge tone={statusTone(c.sanctioned_status)}>{c.sanctioned_status}</StatusBadge>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2 mb-4">
        <div className="card">
          <div className="card-title mb-2">Evasion indicators ({data.evasion_events.length})</div>
          {data.evasion_events.length === 0 ? <p className="text-sm text-gray-500">None recorded.</p> : (
            <ul className="space-y-1 text-sm">{data.evasion_events.map((e) => <li key={e.id}><span className="text-xs text-gray-500">{new Date(e.timestamp).toLocaleString()}</span> <span className="font-medium">{e.event_type.replace('_', ' ')}</span> ({e.severity}) - {e.summary}</li>)}</ul>
          )}
        </div>
        <div className="card">
          <div className="card-title mb-2">Port calls ({data.port_history.length}) / STS ({data.transshipments.length}) / zone events ({data.lane_events.length})</div>
          <ul className="space-y-1 text-sm">
            {data.port_history.slice(0, 10).map((c) => <li key={`p${c.id}`}><span className="text-xs text-gray-500">{new Date(c.arrival_time).toLocaleString()}</span> {c.port_name} ({c.port_country}) {c.dwell_time_hours != null ? `- ${c.dwell_time_hours.toFixed(1)} h` : '- in port'}{c.flags_raised?.length ? <span className="text-red-700"> - {c.flags_raised.map((f) => f.replace(/_/g, ' ')).join(', ')}</span> : null}</li>)}
            {data.transshipments.slice(0, 5).map((t) => <li key={`t${t.id}`}><span className="text-xs text-gray-500">{new Date(t.timestamp).toLocaleString()}</span> STS with <Link className="text-steel-700 hover:underline" to={`/maritime/vessel/${t.vessel_a.mmsi === v.mmsi ? t.vessel_b.mmsi : t.vessel_a.mmsi}`}>{t.vessel_a.mmsi === v.mmsi ? t.vessel_b.name : t.vessel_a.name}</Link> - {t.duration_minutes} min ({Math.round((t.confidence_score || 0) * 100)}%)</li>)}
            {data.lane_events.slice(0, 5).map((l) => <li key={`l${l.id}`}><span className="text-xs text-gray-500">{new Date(l.timestamp).toLocaleString()}</span> {l.lane_name} ({l.context?.replace('_', ' ')}, {l.severity})</li>)}
            {data.port_history.length + data.transshipments.length + data.lane_events.length === 0 && <li className="text-gray-500">None recorded.</li>}
          </ul>
        </div>
      </div>

      <CrossDomain dossier={dossier} />

      <div className="card">
        <div className="card-title mb-2">Audit history</div>
        <AuditLog vesselId={v.id} compact />
      </div>
    </div>
  );
}
