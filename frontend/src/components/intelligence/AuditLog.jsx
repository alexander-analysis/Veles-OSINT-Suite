import { useState } from 'react';
import { Download } from 'lucide-react';
import { useFetch } from '../../hooks/useFetch';
import LoadingSpinner from '../common/LoadingSpinner';
import StatusBadge from '../common/StatusBadge';

const CLASSIFICATION_TONE = { UNCLASSIFIED: 'ok', CONFIDENTIAL: 'warn', SECRET: 'error' };

/** Immutable compliance log with filters and JSON/CSV export. */
export default function AuditLog({ vesselId, compact = false }) {
  const [action, setAction] = useState('');
  const [user, setUser] = useState('');
  const [offset, setOffset] = useState(0);
  const limit = compact ? 25 : 100;
  const params = new URLSearchParams({ limit, offset });
  if (action) params.set('action_type', action);
  if (user) params.set('user', user);
  if (vesselId) params.set('vessel_id', vesselId);
  const { data, loading, error } = useFetch(`/api/maritime/audit-log?${params}`, 30000);
  const { data: actions } = useFetch('/api/maritime/audit-log/actions', 0);

  const exportLog = async (format) => {
    const response = await fetch('/api/maritime/audit-log/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format, action_type: action || null, vessel_id: vesselId || null, requested_by: 'analyst' }),
    });
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `VELES_Audit_Log.${format}`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  return (
    <div>
      <div className="flex flex-wrap gap-2 items-center mb-3 text-xs">
        <select value={action} onChange={(e) => { setAction(e.target.value); setOffset(0); }} className="border border-gray-300 rounded px-2 py-1 bg-white">
          <option value="">all actions</option>
          {actions && Object.entries(actions).map(([k, n]) => <option key={k} value={k}>{k} ({n})</option>)}
        </select>
        <input value={user} onChange={(e) => { setUser(e.target.value); setOffset(0); }} placeholder="operator" className="border border-gray-300 rounded px-2 py-1 w-32" />
        <span className="ml-auto flex gap-1">
          <button type="button" onClick={() => exportLog('json')} className="flex items-center gap-1 px-2 py-1 border border-gray-300 rounded bg-white hover:bg-gray-100"><Download size={12} aria-hidden="true" /> JSON</button>
          <button type="button" onClick={() => exportLog('csv')} className="flex items-center gap-1 px-2 py-1 border border-gray-300 rounded bg-white hover:bg-gray-100"><Download size={12} aria-hidden="true" /> CSV</button>
        </span>
      </div>
      {loading && !data && <LoadingSpinner />}
      {error && <div className="text-sm text-red-700">{error.message}</div>}
      {data && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-gray-500 border-b border-gray-200">
                <tr>{['#', 'Timestamp', 'Action', 'Operator', 'Authorities', 'Rationale', 'Classification'].map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {data.entries.map((e) => (
                  <tr key={e.id} className="border-b border-gray-100 align-top" title={e.supporting_data ? JSON.stringify(e.supporting_data) : ''}>
                    <td className="py-1.5 pr-3 font-mono text-gray-500">{e.id}</td>
                    <td className="py-1.5 pr-3 whitespace-nowrap">{new Date(e.timestamp).toLocaleString()}</td>
                    <td className="py-1.5 pr-3 font-medium">{e.action_type}</td>
                    <td className="py-1.5 pr-3">{e.user}</td>
                    <td className="py-1.5 pr-3">{(e.sanctioning_authorities || []).join(', ')}</td>
                    <td className="py-1.5 pr-3 text-gray-700 max-w-xl">{e.rationale}</td>
                    <td className="py-1.5 pr-3"><StatusBadge tone={CLASSIFICATION_TONE[e.classification_level] || 'neutral'}>{e.classification_level}</StatusBadge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!compact && (
            <div className="flex justify-between items-center mt-2 text-xs text-gray-500">
              <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))} className="px-2 py-1 border border-gray-300 rounded disabled:opacity-40 bg-white">Previous</button>
              <span>{data.total ? `${offset + 1}-${Math.min(offset + limit, data.total)} of ${data.total}` : 'no entries'} - entries are append-only (immutable)</span>
              <button type="button" disabled={offset + limit >= data.total} onClick={() => setOffset(offset + limit)} className="px-2 py-1 border border-gray-300 rounded disabled:opacity-40 bg-white">Next</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
