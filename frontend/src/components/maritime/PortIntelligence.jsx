import { useState } from 'react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { useFetch } from '../../hooks/useFetch';
import LoadingSpinner from '../common/LoadingSpinner';

const RISK = { high: 'text-red-700', medium: 'text-orange-700', safe: 'text-green-700' };

/** Port activity: calls at sanctioned / high-risk facilities, dwell anomalies, per-port totals. */
export default function PortIntelligence() {
  const [onlyFlagged, setOnlyFlagged] = useState(true);
  const [hours, setHours] = useState(168);
  const { data, loading, error } = useFetch(`/api/maritime/port-calls?hours=${hours}&only_flagged=${onlyFlagged}&limit=200`, 60000);

  return (
    <div>
      <div className="flex flex-wrap gap-3 items-center mb-3 text-xs">
        <label className="flex items-center gap-1"><input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} /> high-risk facilities only</label>
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="border border-gray-300 rounded px-2 py-1 bg-white">
          {[24, 168, 720].map((h) => <option key={h} value={h}>last {h / 24} d</option>)}
        </select>
        <span className="text-gray-500 ml-auto">{data ? `${data.total} call(s)` : ''}</span>
      </div>
      {loading && !data && <LoadingSpinner />}
      {error && <div className="text-sm text-red-700">{error.message}</div>}
      {data && (
        <div className="grid gap-4 xl:grid-cols-3">
          <div className="xl:col-span-2 overflow-x-auto">
            {data.calls.length === 0 ? (
              <p className="text-sm text-gray-500">No port calls match.</p>
            ) : (
              <table className="w-full text-xs">
                <thead className="text-left text-gray-500 border-b border-gray-200">
                  <tr>{['Vessel', 'Port', 'Risk', 'Arrived', 'Departed', 'Dwell', 'Cargo (predicted)', 'Flags'].map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {data.calls.map((c) => (
                    <tr key={c.id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-1.5 pr-3 font-medium"><Link to={`/maritime/vessel/${c.mmsi}`} className="text-steel-700 hover:underline">{c.vessel_name || c.mmsi}</Link> <span className="text-gray-500">({c.flag})</span></td>
                      <td className="py-1.5 pr-3">{c.port_name} <span className="text-gray-500">{c.port_country}</span></td>
                      <td className={clsx('py-1.5 pr-3', RISK[c.facility_risk_level])}>{c.facility_risk_level}{c.is_sanctioned_facility ? ' (sanctioned)' : ''}</td>
                      <td className="py-1.5 pr-3 whitespace-nowrap">{new Date(c.arrival_time).toLocaleString()}</td>
                      <td className="py-1.5 pr-3 whitespace-nowrap">{c.departure_time ? new Date(c.departure_time).toLocaleString() : 'in port'}</td>
                      <td className="py-1.5 pr-3">{c.dwell_time_hours != null ? `${c.dwell_time_hours.toFixed(1)} h` : '-'}</td>
                      <td className="py-1.5 pr-3">{c.cargo_type_predicted || '-'}</td>
                      <td className="py-1.5 pr-3 text-gray-600">{(c.flags_raised || []).map((f) => f.replace(/_/g, ' ')).join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div>
            <div className="card-title mb-2">Calls by port</div>
            <table className="w-full text-xs">
              <tbody>
                {data.by_port.map((p) => (
                  <tr key={`${p.port}-${p.risk_level}`} className="border-b border-gray-100">
                    <td className="py-1 pr-2">{p.port}</td>
                    <td className={clsx('py-1 pr-2', RISK[p.risk_level])}>{p.risk_level}</td>
                    <td className="py-1 text-right font-mono">{p.calls}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
