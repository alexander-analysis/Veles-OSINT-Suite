import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Network, Search } from 'lucide-react';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { statusTone } from '../components/maritime/VesselTable';
import { useFetch } from '../hooks/useFetch';
import { apiGet } from '../services/api';

const REASON_LABEL = {
  shared_owner: 'shared owner',
  shared_operator: 'shared operator',
  shared_beneficial_owner: 'shared beneficial owner',
  shared_sanctions_entity: 'same designated entity',
  transshipment_partner: 'STS rendezvous',
  shared_high_risk_port: 'same high-risk port',
};

/** Entity linkage explorer: pick a vessel, see what it is connected to; plus declared-owner fleets. */
export default function Correlation() {
  const [query, setQuery] = useState('');
  const [candidates, setCandidates] = useState(null);
  const [selected, setSelected] = useState(null);
  const [linked, setLinked] = useState(null);
  const [loading, setLoading] = useState(false);
  const { data: fleets } = useFetch('/api/maritime/fleets?min_size=2', 0);

  const search = async (event) => {
    event?.preventDefault();
    if (query.trim().length < 2) return;
    setLoading(true);
    try {
      const result = await apiGet(`/api/maritime/vessels/table?q=${encodeURIComponent(query.trim())}&limit=15&max_age_hours=720`);
      setCandidates(result.vessels);
    } finally {
      setLoading(false);
    }
  };

  const explore = async (vessel) => {
    setSelected(vessel);
    setLinked(null);
    const result = await apiGet(`/api/maritime/vessel-correlation/${vessel.mmsi}?days=30`);
    setLinked(result.linked);
  };

  return (
    <div>
      <PageHeader title="Correlation & Linkage" subtitle="Find vessels connected by ownership, designations, rendezvous and port patterns" />
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="card">
          <div className="card-title mb-2">Find a vessel</div>
          <form onSubmit={search} className="flex gap-2 mb-3">
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="name, MMSI, IMO or owner" className="flex-1 border border-gray-300 rounded px-2 py-1 text-sm" />
            <button type="submit" className="px-2 py-1 rounded bg-steel-600 text-white text-sm hover:bg-steel-700"><Search size={14} aria-hidden="true" /></button>
          </form>
          {loading && <LoadingSpinner />}
          {candidates && (
            <ul className="space-y-1 text-sm max-h-96 overflow-y-auto">
              {candidates.length === 0 && <li className="text-gray-500">No vessels match.</li>}
              {candidates.map((v) => (
                <li key={v.mmsi}>
                  <button type="button" onClick={() => explore(v)} className={`w-full text-left px-2 py-1 rounded hover:bg-gray-100 ${selected?.mmsi === v.mmsi ? 'bg-steel-50' : ''}`}>
                    <span className="font-medium">{v.name}</span> <span className="text-xs text-gray-500">({v.flag_state}) {v.mmsi} - {v.sanctioned_status}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card xl:col-span-2">
          <div className="card-title mb-2 flex items-center gap-1"><Network size={12} aria-hidden="true" /> Linked vessels {selected ? `- ${selected.name}` : ''}</div>
          {!selected && <p className="text-sm text-gray-500">Select a vessel to explore its network.</p>}
          {selected && !linked && <LoadingSpinner />}
          {linked && linked.length === 0 && <p className="text-sm text-gray-500">No linkage found in the last 30 days. Ownership fields populate from enriched sources (MarineTraffic / registries); AIS alone carries no owner data.</p>}
          {linked?.length > 0 && (
            <table className="w-full text-xs">
              <thead className="text-left text-gray-500 border-b border-gray-200">
                <tr>{['Vessel', 'Flag', 'Status', 'Risk', 'Link strength', 'Reasons'].map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {linked.map((c) => (
                  <tr key={c.mmsi} className="border-b border-gray-100">
                    <td className="py-1.5 pr-3 font-medium"><Link to={`/maritime/vessel/${c.mmsi}`} className="text-steel-700 hover:underline">{c.name}</Link></td>
                    <td className="py-1.5 pr-3">{c.flag}</td>
                    <td className="py-1.5 pr-3"><StatusBadge tone={statusTone(c.sanctioned_status)}>{c.sanctioned_status || 'clear'}</StatusBadge></td>
                    <td className="py-1.5 pr-3 font-mono">{c.risk_score != null ? `${Math.round(c.risk_score * 100)}%` : '-'}</td>
                    <td className="py-1.5 pr-3 font-mono">{Math.round(c.link_strength * 100)}%</td>
                    <td className="py-1.5 pr-3 text-gray-600">{c.reasons.map((r) => `${REASON_LABEL[r.type] || r.type}: ${r.detail}`).join('; ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="card mt-4">
        <div className="card-title mb-2">Declared fleets (vessels sharing an owner / operator / beneficial owner)</div>
        {fleets?.groups?.length ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 text-sm">
            {fleets.groups.map((g) => (
              <div key={`${g.link}-${g.entity}`} className="border border-gray-200 rounded p-2">
                <div className="font-medium">{g.entity}</div>
                <div className="text-xs text-gray-500">{g.link.replace(/_/g, ' ')} - {g.size} vessel(s) - {g.flagged} flagged - max risk {Math.round(g.max_risk * 100)}%</div>
                <ul className="mt-1 text-xs">
                  {g.vessels.slice(0, 6).map((v) => (
                    <li key={v.mmsi}><Link to={`/maritime/vessel/${v.mmsi}`} className="text-steel-700 hover:underline">{v.name}</Link> ({v.flag}) {v.sanctioned_status !== 'clear' ? `- ${v.sanctioned_status}` : ''}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : <p className="text-sm text-gray-500">No declared-ownership groups yet - owner/operator data arrives with enriched sources.</p>}
      </div>
    </div>
  );
}
