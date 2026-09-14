import { useState } from 'react';
import clsx from 'clsx';
import { useFetch } from '../../hooks/useFetch';
import LoadingSpinner from '../common/LoadingSpinner';

const TYPE_STYLE = {
  new_designation: 'border-red',
  relisted: 'border-red',
  delisting: 'border-green',
  program_change: 'border-yellow',
  name_change: 'border-orange',
  identifier_change: 'border-orange',
  initial_import: 'border-gray-300',
};
const LABEL = {
  new_designation: 'new designation',
  relisted: 'relisted',
  delisting: 'delisted',
  program_change: 'programme change',
  name_change: 'name change',
  identifier_change: 'identifier change',
  initial_import: 'initial import',
};

/** Recent changes across OFAC / EU / UN with a per-authority summary. */
export default function SanctionsUpdatesTimeline() {
  const [days, setDays] = useState(7);
  const [authority, setAuthority] = useState('');
  const query = `/api/sanctions/updates?timeframe=${days}${authority ? `&authority=${authority}` : ''}&limit=100`;
  const { data, loading, error } = useFetch(query, 60000);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <span className="card-title">Recent sanctions updates</span>
        <span className="flex gap-2 text-xs">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="border border-gray-300 rounded px-1 py-0.5 bg-white">
            {[1, 7, 30, 90].map((d) => (
              <option key={d} value={d}>
                last {d} day{d > 1 ? 's' : ''}
              </option>
            ))}
          </select>
          <select value={authority} onChange={(e) => setAuthority(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white">
            <option value="">all</option>
            <option value="OFAC">OFAC</option>
            <option value="EU">EU</option>
            <option value="UN">UN</option>
          </select>
        </span>
      </div>
      {loading && <LoadingSpinner />}
      {error && <div className="text-sm text-red-700">{error.message}</div>}
      {data && (
        <>
          <div className="grid grid-cols-3 gap-3 mb-3 text-xs">
            {['OFAC', 'EU', 'UN'].map((auth) => {
              const counts = data.summary[auth] || {};
              return (
                <div key={auth} className="bg-gray-50 rounded p-2">
                  <div className="font-semibold">{auth}</div>
                  <div>New: {counts.new_designation || 0}</div>
                  <div>Delisted: {counts.delisting || 0}</div>
                  <div>Changed: {(counts.program_change || 0) + (counts.name_change || 0) + (counts.identifier_change || 0)}</div>
                </div>
              );
            })}
          </div>
          <div className="text-xs text-gray-500 mb-2">
            {data.total_updates} update(s) in {data.period}
          </div>
          <div className="space-y-2 max-h-[26rem] overflow-y-auto pr-1">
            {data.updates.map((u) => (
              <div key={u.id} className={clsx('border-l-4 bg-gray-50 rounded-r px-3 py-2 text-sm', TYPE_STYLE[u.update_type] || 'border-gray-300')}>
                <div className="flex justify-between gap-2">
                  <span className="font-medium">{u.entity_name}</span>
                  <span className="text-xs text-gray-500 whitespace-nowrap">{new Date(u.timestamp).toLocaleString()}</span>
                </div>
                <div className="text-xs text-gray-600">
                  {u.authority} - {LABEL[u.update_type] || u.update_type}
                  {u.entity_type ? ` - ${u.entity_type}` : ''}
                  {u.new_status?.programs?.length ? ` - ${u.new_status.programs.join(', ')}` : ''}
                  {u.update_type === 'name_change' && u.previous_status?.name ? ` - was "${u.previous_status.name}"` : ''}
                </div>
              </div>
            ))}
            {data.updates.length === 0 && <p className="text-sm text-gray-500">No changes recorded in this window.</p>}
          </div>
        </>
      )}
    </div>
  );
}
