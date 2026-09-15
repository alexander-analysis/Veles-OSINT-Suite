import { useState } from 'react';
import { Search, ShieldAlert } from 'lucide-react';
import { apiGet, apiPost } from '../../services/api';
import LoadingSpinner from '../common/LoadingSpinner';
import StatusBadge from '../common/StatusBadge';
import EntityDossier from './EntityDossier';

const AUTHORITY_TONE = { OFAC: 'error', EU: 'warn', UN: 'neutral' };
const TYPES = ['any', 'vessel', 'company', 'person', 'aircraft'];

/** Search the consolidated lists and run an explicit (audited) screening check. */
export default function SanctionsSearchPanel({ initialEntityId = null }) {
  const [query, setQuery] = useState('');
  const [dossierId, setDossierId] = useState(initialEntityId);
  const [type, setType] = useState('any');
  const [authority, setAuthority] = useState('');
  const [results, setResults] = useState(null);
  const [check, setCheck] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = async (event) => {
    event?.preventDefault();
    if (query.trim().length < 2) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ query: query.trim(), limit: 25 });
      if (type !== 'any') params.set('type', type);
      if (authority) params.set('authority', authority);
      const [search, screening] = await Promise.all([
        apiGet(`/api/sanctions/entities?${params}`),
        apiPost('/api/sanctions/check-entity', { entity_name: query.trim(), entity_type: type === 'any' ? null : type, requested_by: 'analyst' }),
      ]);
      setResults(search);
      setCheck(screening);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card">
      <div className="card-title mb-3">Sanctions database search</div>
      <form onSubmit={run} className="flex flex-wrap gap-2 items-center mb-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Entity name, alias, IMO or MMSI"
          className="flex-1 min-w-[16rem] border border-gray-300 rounded px-3 py-1.5 text-sm"
        />
        <select value={type} onChange={(e) => setType(e.target.value)} className="border border-gray-300 rounded px-2 py-1.5 text-sm bg-white">
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select value={authority} onChange={(e) => setAuthority(e.target.value)} className="border border-gray-300 rounded px-2 py-1.5 text-sm bg-white">
          <option value="">all authorities</option>
          <option value="OFAC">OFAC</option>
          <option value="EU">EU</option>
          <option value="UN">UN</option>
        </select>
        <button type="submit" className="flex items-center gap-1 px-3 py-1.5 rounded bg-steel-600 text-white text-sm hover:bg-steel-700" disabled={loading}>
          <Search size={14} aria-hidden="true" /> Search
        </button>
      </form>
      {loading && <LoadingSpinner label="Searching lists" />}
      {error && <div className="text-sm text-red-700">{error}</div>}
      {dossierId && <div className="mb-3"><EntityDossier entityId={dossierId} onClose={() => setDossierId(null)} /></div>}

      {check && (
        <div className={`border rounded-md p-3 mb-3 text-sm ${check.is_sanctioned ? 'border-red bg-red-50' : 'border-green bg-green-50'}`}>
          <div className="flex items-center gap-2 font-medium">
            <ShieldAlert size={16} className={check.is_sanctioned ? 'text-red-700' : 'text-green-700'} aria-hidden="true" />
            {check.is_sanctioned ? 'Screening match' : 'No confident match'} - confidence {(check.confidence * 100).toFixed(0)}%
            {check.designating_authorities.map((a) => (
              <StatusBadge key={a} tone={AUTHORITY_TONE[a]}>
                {a}
              </StatusBadge>
            ))}
          </div>
          {check.matching_entries.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-gray-700">
              {check.matching_entries.slice(0, 5).map((m, i) => (
                <li key={i}>
                  <span className="font-mono">{(m.confidence * 100).toFixed(0)}%</span> {m.summary}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-1 text-xs text-gray-500">This check was written to the audit log.</div>
        </div>
      )}

      {results && (
        <div>
          <div className="text-xs text-gray-500 mb-2">
            {results.total} listing(s) match{results.total > results.entities.length ? ` - showing ${results.entities.length}` : ''}
          </div>
          <div className="space-y-2 max-h-[28rem] overflow-y-auto pr-1">
            {results.entities.map((e) => (
              <div key={e.id} className="border border-gray-200 rounded-md p-3 text-sm bg-white">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{e.name}</span>
                  <span className="flex gap-1">
                    {e.designating_authorities.map((a) => (
                      <StatusBadge key={a} tone={AUTHORITY_TONE[a]}>
                        {a}
                      </StatusBadge>
                    ))}
                    <StatusBadge>{e.entity_type}</StatusBadge>
                    <button type="button" onClick={() => setDossierId(e.id)} className="px-2 py-0.5 rounded border border-gray-300 bg-white text-xs hover:bg-gray-100">dossier</button>
                  </span>
                </div>
                <div className="mt-1 text-xs text-gray-600 grid gap-x-4 gap-y-0.5 sm:grid-cols-2">
                  <span>Programs: {e.programs?.join(', ') || 'n/a'}</span>
                  <span>Designated: {e.designation_date ? new Date(e.designation_date).toLocaleDateString() : 'n/a'}</span>
                  {e.imo && <span>IMO: {e.imo}</span>}
                  {e.vessel_flag && <span>Flag: {e.vessel_flag}</span>}
                  {e.vessel_owner && <span>Owner: {e.vessel_owner}</span>}
                  {e.country_linked && <span>Country: {e.country_linked}</span>}
                  {e.aliases?.length > 0 && <span className="sm:col-span-2">AKA: {e.aliases.slice(0, 4).join('; ')}</span>}
                </div>
                {e.remarks && <div className="mt-1 text-xs text-gray-500 line-clamp-2">{e.remarks}</div>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
