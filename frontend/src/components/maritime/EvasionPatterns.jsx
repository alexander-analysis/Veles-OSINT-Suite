import { useState } from 'react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { EyeOff, Flag, Tag, Fingerprint, Radio, MapPinOff } from 'lucide-react';
import { useFetch } from '../../hooks/useFetch';
import LoadingSpinner from '../common/LoadingSpinner';

const ICONS = { ais_gap: Radio, name_change: Tag, flag_change: Flag, identity_conflict: Fingerprint, dark_in_zone: EyeOff, dark_vessel: EyeOff, position_anomaly: MapPinOff };
const SEVERITY = { critical: 'border-red-900 bg-red-50', high: 'border-red bg-red-50', medium: 'border-orange bg-orange-50', low: 'border-gray-300 bg-white' };
const LABEL = { ais_gap: 'AIS gap', name_change: 'name change', flag_change: 'flag change', identity_conflict: 'identity conflict', dark_in_zone: 'dark in zone', dark_vessel: 'dark vessel', position_anomaly: 'position anomaly (spoofing?)' };

/** AIS gaps, renames, re-flagging, identity conflicts and dark vessels. */
export default function EvasionPatterns() {
  const [type, setType] = useState('');
  const [hours, setHours] = useState(168);
  const params = new URLSearchParams({ hours, limit: 100 });
  if (type) params.set('event_type', type);
  const { data, loading, error } = useFetch(`/api/maritime/evasion-patterns?${params}`, 30000);

  return (
    <div>
      <div className="flex flex-wrap gap-2 items-center mb-3 text-xs">
        <select value={type} onChange={(e) => setType(e.target.value)} className="border border-gray-300 rounded px-2 py-1 bg-white">
          <option value="">all indicators</option>
          {Object.entries(LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="border border-gray-300 rounded px-2 py-1 bg-white">
          {[24, 72, 168, 720].map((h) => <option key={h} value={h}>last {h >= 24 ? `${h / 24} d` : `${h} h`}</option>)}
        </select>
        {data && (
          <span className="text-gray-500 ml-auto">
            {Object.entries(data.by_type).map(([k, n]) => `${LABEL[k] || k}: ${n}`).join(' - ') || 'no indicators'}
          </span>
        )}
      </div>
      {loading && !data && <LoadingSpinner />}
      {error && <div className="text-sm text-red-700">{error.message}</div>}
      {data?.events?.length === 0 && <p className="text-sm text-gray-500">No evasion indicators in this window. Detectors: AIS gaps over the configured threshold, renames, re-flagging, IMO conflicts, dark flagged vessels.</p>}
      <div className="space-y-2 max-h-[34rem] overflow-y-auto pr-1">
        {data?.events?.map((e) => {
          const Icon = ICONS[e.event_type] || EyeOff;
          return (
            <div key={e.id} className={clsx('border rounded-md p-3 text-sm', SEVERITY[e.severity] || SEVERITY.low)}>
              <div className="flex items-start justify-between gap-2">
                <span className="flex items-center gap-2 font-medium">
                  <Icon size={15} aria-hidden="true" />
                  <Link to={`/maritime/vessel/${e.mmsi}`} className="text-steel-700 hover:underline">{e.vessel_name || e.mmsi}</Link>
                  <span className="text-xs font-normal text-gray-500">{LABEL[e.event_type] || e.event_type} - {e.severity}</span>
                </span>
                <span className="text-xs text-gray-500 whitespace-nowrap">{new Date(e.timestamp).toLocaleString()}</span>
              </div>
              <p className="mt-1 text-gray-700">{e.summary}</p>
              <div className="mt-1 text-xs text-gray-500">confidence {Math.round((e.confidence_score || 0) * 100)}% - status {e.investigation_status}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
