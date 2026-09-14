import { Link } from 'react-router-dom';
import { ArrowLeftRight } from 'lucide-react';
import { useFetch } from '../../hooks/useFetch';
import { apiPatch } from '../../services/api';
import LoadingSpinner from '../common/LoadingSpinner';
import StatusBadge from '../common/StatusBadge';
import { statusTone } from './VesselTable';

const STATUSES = ['possible', 'confirmed', 'cleared'];

function VesselChip({ v }) {
  return (
    <span className="inline-flex items-center gap-1">
      <Link to={`/maritime/vessel/${v.mmsi}`} className="font-medium text-steel-700 hover:underline">{v.name || v.mmsi}</Link>
      <span className="text-gray-500">({v.flag || '?'}{v.ship_type ? `, ${v.ship_type}` : ''})</span>
      {v.sanctioned_status && v.sanctioned_status !== 'clear' && <StatusBadge tone={statusTone(v.sanctioned_status)}>{v.sanctioned_status}</StatusBadge>}
    </span>
  );
}

/** Detected ship-to-ship rendezvous. */
export default function TransshipmentAlert() {
  const { data, loading, error, refetch } = useFetch('/api/maritime/transshipment?hours=720', 60000);
  const update = async (id, investigation_status) => {
    await apiPatch(`/api/maritime/transshipment/${id}`, { investigation_status, updated_by: 'analyst' });
    refetch();
  };
  return (
    <div>
      {loading && !data && <LoadingSpinner />}
      {error && <div className="text-sm text-red-700">{error.message}</div>}
      {data?.events?.length === 0 && (
        <p className="text-sm text-gray-500">No ship-to-ship candidates in the last 30 days. Detection: two slow cargo vessels within the proximity threshold, away from ports, for at least the configured duration.</p>
      )}
      <div className="space-y-2">
        {data?.events?.map((e) => (
          <div key={e.id} className="border border-gray-200 rounded-md p-3 text-sm bg-white">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex flex-wrap items-center gap-2">
                <ArrowLeftRight size={15} className="text-steel-600" aria-hidden="true" />
                <VesselChip v={e.vessel_a} /> <span className="text-gray-400">&harr;</span> <VesselChip v={e.vessel_b} />
              </span>
              <span className="text-xs text-gray-500">{new Date(e.timestamp).toLocaleString()}</span>
            </div>
            <div className="mt-1 text-xs text-gray-600">
              {e.proximity_meters != null && `${Math.round(e.proximity_meters)} m apart`} - {e.duration_minutes ?? '?'} min - confidence {Math.round((e.confidence_score || 0) * 100)}%
              {e.supporting_evidence?.zones?.length ? ` - inside ${e.supporting_evidence.zones.join(', ')}` : ''}
              {' - '}{e.location.lat.toFixed(3)}, {e.location.lon.toFixed(3)}
            </div>
            <div className="mt-2 flex items-center gap-2 text-xs">
              <span className="text-gray-500">status</span>
              <select value={e.investigation_status || 'possible'} onChange={(ev) => update(e.id, ev.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white">
                {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
