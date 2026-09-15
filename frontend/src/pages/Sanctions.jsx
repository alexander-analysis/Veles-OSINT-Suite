import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import SanctionsSearchPanel from '../components/intelligence/SanctionsSearchPanel';
import SanctionsUpdatesTimeline from '../components/intelligence/SanctionsUpdatesTimeline';
import { useFetch } from '../hooks/useFetch';
import { apiPost } from '../services/api';

function ProgramsTable({ programs }) {
  const [authority, setAuthority] = useState('OFAC');
  const rows = (programs?.programs || []).filter((p) => p.authority === authority).slice(0, 25);
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <span className="card-title">Programmes</span>
        <select value={authority} onChange={(e) => setAuthority(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 text-xs bg-white">
          {['OFAC', 'EU', 'UN'].map((a) => (
            <option key={a} value={a}>
              {a} ({programs?.totals?.[a] ?? 0})
            </option>
          ))}
        </select>
      </div>
      {rows.length ? (
        <table className="w-full text-xs">
          <thead className="text-left text-gray-500 border-b border-gray-200">
            <tr>
              <th className="py-1 font-medium">Programme</th>
              <th className="py-1 font-medium text-right">Listings</th>
              <th className="py-1 font-medium text-right">Vessels</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={`${p.authority}-${p.program}`} className="border-b border-gray-100">
                <td className="py-1 pr-2">{p.program}</td>
                <td className="py-1 text-right font-mono">{p.entities_count}</td>
                <td className="py-1 text-right font-mono">{p.vessels_count || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-sm text-gray-500">No listings loaded yet for {authority}.</p>
      )}
    </div>
  );
}

export default function Sanctions() {
  const [params] = useSearchParams();
  const initialEntityId = params.get('entity') ? Number(params.get('entity')) : null;
  const { data: status, refetch } = useFetch('/api/sanctions/status', 15000);
  const { data: programs } = useFetch('/api/sanctions/programs', 60000);
  const [starting, setStarting] = useState(false);
  const totals = status?.active_listings || {};
  const total = Object.values(totals).reduce((s, v) => s + v, 0);

  const refresh = async () => {
    setStarting(true);
    try {
      await apiPost('/api/sanctions/refresh', {});
      setTimeout(refetch, 2000);
    } finally {
      setStarting(false);
    }
  };

  return (
    <div>
      <PageHeader title="Sanctions Intelligence" subtitle="OFAC SDN, EU consolidated list and UN Security Council designations">
        <StatusBadge tone={total ? 'ok' : 'warn'}>{total ? `${total.toLocaleString()} active listings` : 'lists not loaded'}</StatusBadge>
        <button
          type="button"
          onClick={refresh}
          disabled={starting || status?.refreshing}
          className="flex items-center gap-1 px-2 py-1 rounded border border-gray-300 bg-white text-xs hover:bg-gray-100 disabled:opacity-50"
        >
          <RefreshCw size={12} className={status?.refreshing ? 'animate-spin' : ''} aria-hidden="true" />
          {status?.refreshing ? 'Refreshing' : 'Refresh lists'}
        </button>
      </PageHeader>

      <div className="grid gap-3 md:grid-cols-3 mb-6 text-sm">
        {['OFAC', 'EU', 'UN'].map((a) => (
          <div key={a} className="card py-3">
            <div className="card-title">{a}</div>
            <div className="text-xl font-semibold">{(totals[a] || 0).toLocaleString()}</div>
            <div className="text-xs text-gray-500">
              refreshed {status?.last_refresh?.[a] ? new Date(status.last_refresh[a]).toLocaleString() : 'not yet this session'}
              {status?.last_result?.[a]?.new != null && ` - last run: +${status.last_result[a].new} / -${status.last_result[a].delisted}`}
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2 space-y-4">
          <SanctionsSearchPanel key={initialEntityId || 'search'} initialEntityId={initialEntityId} />
          <SanctionsUpdatesTimeline />
        </div>
        <ProgramsTable programs={programs} />
      </div>
    </div>
  );
}
