import { useState } from 'react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { useFetch } from '../../hooks/useFetch';
import LoadingSpinner from '../common/LoadingSpinner';
import StatusBadge from '../common/StatusBadge';

const STATUS_TONE = { clear: 'ok', flagged: 'warn' };

export function statusTone(status) {
  if (!status) return 'neutral';
  if (status.startsWith('breach')) return 'error';
  return STATUS_TONE[status] || 'neutral';
}

/** Searchable, sortable vessel grid backed by /api/maritime/vessels/table. */
export default function VesselTable() {
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [sort, setSort] = useState('risk');
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const params = new URLSearchParams({ sort, limit, offset });
  if (q) params.set('q', q);
  if (status) params.set('status', status);
  const { data, loading, error } = useFetch(`/api/maritime/vessels/table?${params}`, 30000);

  return (
    <div>
      <div className="flex flex-wrap gap-2 items-center mb-3 text-xs">
        <input value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder="Search name / MMSI / IMO / owner" className="border border-gray-300 rounded px-2 py-1 w-64" />
        <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className="border border-gray-300 rounded px-2 py-1 bg-white">
          <option value="">any status</option>
          <option value="breach">breach</option>
          <option value="flagged">flagged</option>
          <option value="clear">clear</option>
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} className="border border-gray-300 rounded px-2 py-1 bg-white">
          <option value="risk">sort: risk</option>
          <option value="recent">sort: most recent</option>
          <option value="name">sort: name</option>
        </select>
        <span className="text-gray-500 ml-auto">{data ? `${data.total} vessel(s)` : ''}</span>
      </div>
      {loading && !data && <LoadingSpinner />}
      {error && <div className="text-sm text-red-700">{error.message}</div>}
      {data && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-gray-500 border-b border-gray-200">
              <tr>
                {['Vessel', 'Flag', 'Type', 'MMSI / IMO', 'Speed', 'Destination', 'Last seen', 'Status', 'Risk'].map((h) => (
                  <th key={h} className="py-2 pr-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.vessels.map((v) => (
                <tr key={v.mmsi} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-1.5 pr-3 font-medium"><Link to={`/maritime/vessel/${v.mmsi}`} className="text-steel-700 hover:underline">{v.name}</Link></td>
                  <td className="py-1.5 pr-3">{v.flag_state}</td>
                  <td className="py-1.5 pr-3">{v.ship_type || '-'}</td>
                  <td className="py-1.5 pr-3 font-mono">{v.mmsi}{v.imo ? ` / ${v.imo}` : ''}</td>
                  <td className="py-1.5 pr-3">{v.current_speed != null ? `${v.current_speed.toFixed(1)} kn` : '-'}</td>
                  <td className="py-1.5 pr-3">{v.destination || '-'}</td>
                  <td className="py-1.5 pr-3 whitespace-nowrap">{v.last_ais_update ? new Date(v.last_ais_update).toLocaleString() : '-'}</td>
                  <td className="py-1.5 pr-3"><StatusBadge tone={statusTone(v.sanctioned_status)}>{v.sanctioned_status || 'clear'}</StatusBadge></td>
                  <td className={clsx('py-1.5 pr-3 font-mono', (v.risk_score || 0) >= 0.6 && 'text-red-700 font-semibold')}>{v.risk_score != null ? `${Math.round(v.risk_score * 100)}%` : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex justify-between items-center mt-2 text-xs text-gray-500">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))} className="px-2 py-1 border border-gray-300 rounded disabled:opacity-40 bg-white">Previous</button>
            <span>{offset + 1}-{Math.min(offset + limit, data.total)} of {data.total}</span>
            <button type="button" disabled={offset + limit >= data.total} onClick={() => setOffset(offset + limit)} className="px-2 py-1 border border-gray-300 rounded disabled:opacity-40 bg-white">Next</button>
          </div>
        </div>
      )}
    </div>
  );
}
