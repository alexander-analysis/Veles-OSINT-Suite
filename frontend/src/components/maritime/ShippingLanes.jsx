import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { useFetch } from '../../hooks/useFetch';
import LoadingSpinner from '../common/LoadingSpinner';

const SEVERITY = { high: 'text-red-700 font-semibold', medium: 'text-orange-700', low: 'text-gray-600' };

/** Zone entries and chokepoint transits by high-risk vessels. */
export default function ShippingLanes() {
  const { data, loading, error } = useFetch('/api/maritime/shipping-lanes/violations?hours=168&limit=200', 60000);
  return (
    <div>
      {loading && !data && <LoadingSpinner />}
      {error && <div className="text-sm text-red-700">{error.message}</div>}
      {data && (
        <div className="grid gap-4 xl:grid-cols-3">
          <div className="xl:col-span-2 overflow-x-auto">
            {data.violations.length === 0 ? (
              <p className="text-sm text-gray-500">No zone entries or chokepoint transits by high-risk vessels in the last 7 days.</p>
            ) : (
              <table className="w-full text-xs">
                <thead className="text-left text-gray-500 border-b border-gray-200">
                  <tr>{['Vessel', 'Zone / lane', 'Context', 'Severity', 'When', 'Assessment'].map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {data.violations.map((v) => (
                    <tr key={v.id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-1.5 pr-3 font-medium"><Link to={`/maritime/vessel/${v.mmsi}`} className="text-steel-700 hover:underline">{v.vessel_name || v.mmsi}</Link></td>
                      <td className="py-1.5 pr-3">{v.lane_name}</td>
                      <td className="py-1.5 pr-3">{v.context?.replace('_', ' ')}</td>
                      <td className={clsx('py-1.5 pr-3', SEVERITY[v.severity])}>{v.severity}</td>
                      <td className="py-1.5 pr-3 whitespace-nowrap">{new Date(v.timestamp).toLocaleString()}</td>
                      <td className="py-1.5 pr-3 text-gray-600">{v.reason_suspected}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div>
            <div className="card-title mb-2">Events by zone (7 d)</div>
            <table className="w-full text-xs">
              <tbody>
                {Object.entries(data.by_lane).sort((a, b) => b[1] - a[1]).map(([lane, n]) => (
                  <tr key={lane} className="border-b border-gray-100"><td className="py-1 pr-2">{lane}</td><td className="py-1 text-right font-mono">{n}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
