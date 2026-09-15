import { useCallback, useMemo, useState } from 'react';
import clsx from 'clsx';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import VesselMap from '../components/maritime/VesselMap';
import VesselTable from '../components/maritime/VesselTable';
import BreachBoard from '../components/maritime/BreachBoard';
import EvasionPatterns from '../components/maritime/EvasionPatterns';
import TransshipmentAlert from '../components/maritime/TransshipmentAlert';
import PortIntelligence from '../components/maritime/PortIntelligence';
import ShippingLanes from '../components/maritime/ShippingLanes';
import { useFetch } from '../hooks/useFetch';
import { useWebSocket } from '../hooks/useWebSocket';

const TABS = [
  ['vessels', 'Vessels'],
  ['breaches', 'Breach board'],
  ['evasion', 'Evasion patterns'],
  ['transshipment', 'Transshipment'],
  ['ports', 'Port activity'],
  ['lanes', 'Zones & lanes'],
];

export default function Maritime() {
  const [view, setView] = useState(null);
  // Zoomed out: the 5,000 highest-risk vessels worldwide. Zoomed in: everything inside the visible area.
  const vesselsUrl = useMemo(
    () => (view && view.zoom >= 5 ? `/api/maritime/vessels?max_age_hours=6&bbox=${view.bbox.join(',')}` : '/api/maritime/vessels?max_age_hours=6'),
    [view],
  );
  const { data: vessels, refetch: refetchVessels } = useFetch(vesselsUrl, 60000);
  const onViewChange = useCallback((next) => setView((current) => (current && current.zoom === next.zoom && current.bbox.join() === next.bbox.join() ? current : next)), []);
  const { data: breaches, refetch: refetchBreaches } = useFetch('/api/maritime/breaches?limit=500', 60000);
  const { data: status } = useFetch('/api/maritime/status', 30000);
  const [tab, setTab] = useState('vessels');
  const [toasts, setToasts] = useState([]);

  const onFrame = useCallback(
    (frame) => {
      if (frame.type === 'vessel_positions') {
        refetchVessels();
      } else if (frame.type === 'breach_detected' || frame.type === 'transshipment_detected') {
        const text =
          frame.type === 'breach_detected'
            ? `BREACH ${frame.data.authority}: ${frame.data.vessel_name} (${frame.data.mmsi}) - ${frame.data.breach_type.replace('_', ' ')}`
            : `STS candidate: ${frame.data.vessel_a.name} & ${frame.data.vessel_b.name} (${frame.data.duration_minutes} min)`;
        setToasts((current) => [{ id: `${Date.now()}-${Math.random()}`, text, kind: frame.type }, ...current].slice(0, 5));
        refetchBreaches();
      }
    },
    [refetchVessels, refetchBreaches],
  );
  const { status: wsStatus } = useWebSocket('/api/maritime/stream', onFrame);

  return (
    <div>
      <PageHeader title="Maritime Intelligence" subtitle="Live AIS tracking, sanctions screening and evasion detection">
        <StatusBadge tone={wsStatus === 'open' ? 'ok' : 'warn'}>stream {wsStatus}</StatusBadge>
        <StatusBadge tone={vessels?.vessel_count ? 'ok' : 'neutral'}>{vessels ? `${vessels.vessel_count} vessels ${view && view.zoom >= 5 ? 'in view' : '(top risk, zoom in for all)'}` : 'loading'}</StatusBadge>
        <StatusBadge tone={breaches?.total ? 'error' : 'ok'}>{breaches ? `${breaches.total} open breach(es)` : ''}</StatusBadge>
      </PageHeader>

      {toasts.length > 0 && (
        <div className="fixed top-16 right-4 z-[2000] space-y-2 w-96 no-print">
          {toasts.map((t) => (
            <div key={t.id} className={clsx('border rounded-md shadow px-3 py-2 text-sm bg-white', t.kind === 'breach_detected' ? 'border-red text-red-700' : 'border-orange text-orange-700')}>
              <div className="flex justify-between gap-2">
                <span>{t.text}</span>
                <button type="button" onClick={() => setToasts((c) => c.filter((x) => x.id !== t.id))} className="text-gray-400 hover:text-gray-700">x</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card p-0 overflow-hidden mb-4">
        <VesselMap vessels={vessels} breaches={breaches?.breaches} height="560px" onViewChange={onViewChange} fitToData={false} center={[45, 20]} zoom={3} />
      </div>

      {status && (
        <div className="grid gap-3 md:grid-cols-4 mb-4 text-xs">
          <div className="card py-2"><div className="card-title">Tracked</div><div className="text-lg font-semibold">{status.vessels_tracked.toLocaleString()}</div><div className="text-gray-500">{status.vessels_active_1h} active last hour</div></div>
          <div className="card py-2"><div className="card-title">Positions stored</div><div className="text-lg font-semibold">{status.positions_stored.toLocaleString()}</div><div className="text-gray-500">last poll {status.last_fetch_at ? new Date(status.last_fetch_at).toLocaleTimeString() : '-'}</div></div>
          <div className="card py-2"><div className="card-title">Sources</div><div className="text-lg font-semibold">{Object.keys(status.sources).length}</div><div className="text-gray-500 truncate" title={Object.entries(status.source_errors).map(([k, v]) => `${k}: ${v}`).join('\n')}>{Object.keys(status.sources).join(', ') || 'none'}{Object.keys(status.source_errors).length ? ` - ${Object.keys(status.source_errors).length} off (no key)` : ''}</div></div>
          <div className="card py-2"><div className="card-title">Screening</div><div className="text-lg font-semibold">{status.open_breaches}</div><div className="text-gray-500">open breaches - last check {status.last_sanctions_check_at ? new Date(status.last_sanctions_check_at).toLocaleTimeString() : 'pending'}</div></div>
        </div>
      )}

      <div className="card">
        <div className="flex flex-wrap gap-1 border-b border-gray-200 mb-4 -mt-1">
          {TABS.map(([key, label]) => (
            <button key={key} type="button" onClick={() => setTab(key)} className={clsx('px-3 py-2 text-sm border-b-2 -mb-px', tab === key ? 'border-steel-600 text-steel-700 font-medium' : 'border-transparent text-gray-600 hover:text-gray-900')}>
              {label}
            </button>
          ))}
        </div>
        {tab === 'vessels' && <VesselTable />}
        {tab === 'breaches' && <BreachBoard onChange={refetchVessels} />}
        {tab === 'evasion' && <EvasionPatterns />}
        {tab === 'transshipment' && <TransshipmentAlert />}
        {tab === 'ports' && <PortIntelligence />}
        {tab === 'lanes' && <ShippingLanes />}
      </div>
    </div>
  );
}
