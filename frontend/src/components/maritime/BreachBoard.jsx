import { useState } from 'react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { useFetch } from '../../hooks/useFetch';
import { apiPatch } from '../../services/api';
import LoadingSpinner from '../common/LoadingSpinner';
import StatusBadge from '../common/StatusBadge';

const SEVERITY_TEXT = { critical: 'text-red-900 font-semibold', high: 'text-red-700', medium: 'text-orange-700', low: 'text-gray-600' };
const AUTHORITY_TONE = { OFAC: 'error', EU: 'warn', UN: 'neutral' };
const STATUSES = ['flagged', 'review', 'investigating', 'escalated', 'cleared'];

/** Active sanctions matches with inline investigation-status updates. */
export default function BreachBoard({ onChange }) {
  const [authority, setAuthority] = useState('');
  const [status, setStatus] = useState('flagged,investigating,escalated');
  const params = new URLSearchParams({ limit: 200, status });
  if (authority) params.set('authority', authority);
  const { data, loading, error, refetch } = useFetch(`/api/maritime/breaches?${params}`, 30000);

  const update = async (id, investigation_status) => {
    await apiPatch(`/api/maritime/breach/${id}`, { investigation_status, updated_by: 'analyst' });
    refetch();
    onChange?.();
  };

  return (
    <div>
      <div className="flex flex-wrap gap-2 items-center mb-3 text-xs">
        <select value={authority} onChange={(e) => setAuthority(e.target.value)} className="border border-gray-300 rounded px-2 py-1 bg-white">
          <option value="">all authorities</option>
          <option value="OFAC">OFAC</option>
          <option value="EU">EU</option>
          <option value="UN">UN</option>
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="border border-gray-300 rounded px-2 py-1 bg-white">
          <option value="flagged,investigating,escalated">open</option>
          <option value="review">review queue (low confidence)</option>
          <option value="cleared">cleared</option>
          <option value="all">all</option>
        </select>
        <span className="text-gray-500 ml-auto">{data ? `${data.total} breach(es)` : ''}</span>
      </div>
      {loading && !data && <LoadingSpinner />}
      {error && <div className="text-sm text-red-700">{error.message}</div>}
      {data?.breaches?.length === 0 && <p className="text-sm text-gray-500">No sanctions matches in this view.</p>}
      {data?.breaches?.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-gray-500 border-b border-gray-200">
              <tr>
                {['Vessel', 'Flag', 'Authority', 'Match', 'Designated entity', 'Confidence', 'Severity', 'Detected', 'Status'].map((h) => (
                  <th key={h} className="py-2 pr-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.breaches.map((b) => (
                <tr key={b.id} className="border-b border-gray-100 hover:bg-gray-50" title={b.supporting_evidence?.summary || ''}>
                  <td className="py-1.5 pr-3 font-medium"><Link to={`/maritime/vessel/${b.mmsi}`} className="text-steel-700 hover:underline">{b.vessel_name}</Link></td>
                  <td className="py-1.5 pr-3">{b.flag}</td>
                  <td className="py-1.5 pr-3"><StatusBadge tone={AUTHORITY_TONE[b.sanctioning_authority]}>{b.sanctioning_authority}</StatusBadge></td>
                  <td className="py-1.5 pr-3">{b.breach_type.replace('_', ' ')}{b.supporting_evidence?.match_type ? ` (${b.supporting_evidence.match_type.replace('_', ' ')})` : ''}</td>
                  <td className="py-1.5 pr-3">{b.sanctioned_entity}</td>
                  <td className="py-1.5 pr-3 font-mono">{Math.round((b.match_confidence || 0) * 100)}%</td>
                  <td className={clsx('py-1.5 pr-3 uppercase', SEVERITY_TEXT[b.severity])}>{b.severity}</td>
                  <td className="py-1.5 pr-3 whitespace-nowrap">{new Date(b.detected_at).toLocaleString()}</td>
                  <td className="py-1.5 pr-3">
                    <select value={b.investigation_status || 'flagged'} onChange={(e) => update(b.id, e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white">
                      {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
