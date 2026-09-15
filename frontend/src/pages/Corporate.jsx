import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Building2, Search, RefreshCw, ExternalLink, GitBranch, ShieldAlert, EyeOff, Download } from 'lucide-react';
import clsx from 'clsx';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useFetch } from '../hooks/useFetch';
import { apiGet, apiPost } from '../services/api';

const MATCH_LABEL = {
  direct: 'listed',
  parent: 'subsidiary of listed',
  ultimate_parent: 'under listed group',
  child: 'parent of listed',
  vessel_owner: 'owns listed vessel',
  shareholder: 'sanctioned shareholder',
  director: 'sanctioned director',
};
const MATCH_TONE = { direct: 'error', parent: 'error', ultimate_parent: 'warn', child: 'warn', vessel_owner: 'error', shareholder: 'warn', director: 'warn' };
const pct = (v) => (v == null ? '-' : `${Math.round(v * 100)}%`);
const when = (iso) => (iso ? new Date(iso).toLocaleDateString() : '-');
const label = (s) => (s || '').replace(/_/g, ' ');

function Summary({ summary, status }) {
  if (!summary) return null;
  const enrich = status?.last_result?.enrich;
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5 mb-4">
      <div className="card py-3"><div className="card-title">Companies tracked</div><div className="text-xl font-semibold mt-1">{summary.companies.toLocaleString()}</div><div className="text-xs text-gray-500">{summary.with_lei} with LEI - {summary.enriched.toLocaleString()} checked against GLEIF</div></div>
      <div className="card py-3"><div className="card-title">Sanctions exposure</div><div className="text-xl font-semibold mt-1">{summary.exposure}</div><div className="text-xs text-gray-500">unlisted companies under / above a listed party</div></div>
      <div className="card py-3"><div className="card-title">Ownership chains</div><div className="text-xl font-semibold mt-1">{summary.ownership_chains}</div><div className="text-xs text-gray-500">{summary.chains_with_sanctioned} involve a sanctioned party</div></div>
      <div className="card py-3"><div className="card-title">Shell / opaque</div><div className="text-xl font-semibold mt-1">{summary.shell_companies}</div><div className="text-xs text-gray-500">{summary.opaque_ownership} with undisclosed parents</div></div>
      <div className="card py-3"><div className="card-title">Last GLEIF pass</div><div className="text-sm mt-1">{enrich ? `${enrich.checked} checked - ${enrich.matched} matched - ${enrich.exposure_found} exposure` : status?.enriching ? 'running' : 'pending'}</div><div className="text-xs text-gray-500">{(summary.top_countries || []).slice(0, 5).map((c) => `${c.country} ${c.companies}`).join(' - ')}</div></div>
    </div>
  );
}

function ChainView({ chain }) {
  if (!chain?.chain_path?.length) return null;
  return (
    <div className="text-xs">
      <div className="card-title mb-1 flex items-center gap-1"><GitBranch size={12} aria-hidden="true" /> Ownership chain <span className="text-gray-400 normal-case">(risk {pct(chain.risk_score)})</span></div>
      <ol className="space-y-1">
        {chain.chain_path.map((hop, i) => (
          <li key={`${hop.lei || hop.name}-${i}`} className={clsx('flex items-center gap-2 px-2 py-1 rounded border', hop.sanctioned ? 'border-red bg-red-50' : 'border-gray-200')}>
            <span className="text-gray-400 w-4">{i === 0 ? '●' : '↑'}</span>
            <span className="font-medium truncate">{hop.name}</span>
            <span className="text-gray-500">{hop.country || '?'}</span>
            <span className="text-gray-400 ml-auto whitespace-nowrap">{label(hop.relationship)}</span>
          </li>
        ))}
      </ol>
      <div className="text-gray-500 mt-1">{chain.involves_secrecy_jurisdiction && 'secrecy jurisdiction in chain - '}{chain.involves_shell_companies && 'shell indicators - '}{chain.involves_sanctioned ? 'sanctioned party in chain' : 'no sanctioned party found in chain'}</div>
    </div>
  );
}

function CompanyDetail({ id, onSelect, onClose }) {
  const { data, loading } = useFetch(id ? `/api/corporate/companies/${id}` : null, 0);
  if (!id) return null;
  if (loading && !data) return <div className="card"><LoadingSpinner label="Loading company" /></div>;
  if (!data) return null;
  const c = data.company;
  return (
    <div className="card space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-1">
            {c.linked_to_sanctioned && <StatusBadge tone={MATCH_TONE[c.sanctions_match_type] || 'warn'}>{MATCH_LABEL[c.sanctions_match_type] || c.sanctions_match_type}</StatusBadge>}
            {c.is_shell_company && <StatusBadge tone="warn">shell indicators {pct(c.shell_company_confidence)}</StatusBadge>}
            {c.ownership_opaque && <StatusBadge tone="neutral"><EyeOff size={10} className="inline mr-1" aria-hidden="true" />{c.parent_reporting_exception}</StatusBadge>}
          </div>
          <h3 className="text-base font-semibold mt-1">{c.company_name}</h3>
          <div className="text-xs text-gray-500">{[c.registration_country, c.company_type, c.entity_status, c.registration_status].filter(Boolean).join(' - ')}</div>
        </div>
        <button type="button" onClick={onClose} className="text-xs text-gray-500 hover:underline">close</button>
      </div>
      <table className="kv-table">
        <tbody>
          <tr><td>LEI</td><td>{c.lei ? <a href={data.gleif_url} target="_blank" rel="noreferrer noopener" className="font-mono text-steel-700 hover:underline inline-flex items-center gap-1">{c.lei} <ExternalLink size={11} aria-hidden="true" /></a> : <span className="text-gray-500">none found{c.last_enriched ? '' : ' (not checked yet)'}</span>}</td></tr>
          {c.registered_address && <tr><td>Address</td><td>{c.registered_address}</td></tr>}
          {c.industry_sector && <tr><td>Industry</td><td>{c.industry_sector} {c.website && <a href={c.website} target="_blank" rel="noreferrer noopener" className="text-steel-700 hover:underline">(EDGAR)</a>}</td></tr>}
          {c.registration_date && <tr><td>Formed</td><td>{when(c.registration_date)}</td></tr>}
          <tr><td>Risk</td><td>{pct(c.risk_score)} {c.shell_indicators?.length ? <span className="text-gray-500">- {c.shell_indicators.map(label).join(', ')}</span> : null}</td></tr>
          {data.sanctioned_entity && <tr><td>Listing</td><td><ShieldAlert size={12} className="inline text-red-700 mr-1" aria-hidden="true" />{data.sanctioned_entity.designating_authority}: {data.sanctioned_entity.name} <span className="text-gray-500">{(data.sanctioned_entity.programs || []).join(', ')}</span> {c.sanctions_confidence != null && <span className="text-gray-500">({pct(c.sanctions_confidence)})</span>}</td></tr>}
          <tr><td>Origin</td><td>{label(c.origin)} - {c.source}{c.source_ref ? ` (${c.source_ref})` : ''}</td></tr>
          <tr><td>Checked</td><td>{c.last_enriched ? new Date(c.last_enriched).toLocaleString() : 'queued for GLEIF lookup'}</td></tr>
        </tbody>
      </table>
      <ChainView chain={data.ownership_chain} />
      {data.parents.length > 0 && (
        <div className="text-xs">
          <div className="card-title mb-1">Parents ({data.parents.length})</div>
          <ul className="space-y-0.5">{data.parents.map((p) => <li key={p.id}><button type="button" onClick={() => onSelect(p.id)} className="text-steel-700 hover:underline font-medium">{p.company_name}</button> <span className="text-gray-500">{p.registration_country} - {label(p.relationship)}</span> {p.linked_to_sanctioned && <StatusBadge tone={MATCH_TONE[p.sanctions_match_type] || 'warn'}>{MATCH_LABEL[p.sanctions_match_type] || 'linked'}</StatusBadge>}</li>)}</ul>
        </div>
      )}
      {data.subsidiaries.length > 0 && (
        <div className="text-xs">
          <div className="card-title mb-1">Subsidiaries ({data.subsidiaries.length})</div>
          <ul className="space-y-0.5 max-h-60 overflow-y-auto">{data.subsidiaries.map((s) => <li key={s.id}><button type="button" onClick={() => onSelect(s.id)} className="text-steel-700 hover:underline font-medium">{s.company_name}</button> <span className="text-gray-500">{s.registration_country}</span> {s.linked_to_sanctioned && <StatusBadge tone={MATCH_TONE[s.sanctions_match_type] || 'warn'}>{MATCH_LABEL[s.sanctions_match_type] || 'linked'}</StatusBadge>}</li>)}</ul>
        </div>
      )}
      {data.directors.length > 0 && (
        <div className="text-xs">
          <div className="card-title mb-1">Officers ({data.directors.length})</div>
          <ul>{data.directors.map((d) => <li key={d.id}>{d.name} <span className="text-gray-500">{d.title}</span> {d.is_sanctioned && <StatusBadge tone="error">sanctioned</StatusBadge>}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

function LeiSearch({ onSelect, onIngested }) {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const run = async (e) => {
    e.preventDefault();
    if (q.trim().length < 2) return;
    setBusy(true);
    setMessage('');
    try {
      const result = await apiGet(`/api/corporate/search?q=${encodeURIComponent(q.trim())}&live=true`);
      setHits(result.hits);
      if (!result.hits.length) setMessage('No LEI records match - the entity may not have an LEI (most small shells do not).');
    } catch (err) {
      setMessage(err.message);
    } finally {
      setBusy(false);
    }
  };
  const ingest = async (lei) => {
    try {
      await apiPost('/api/corporate/ingest', { lei });
      setMessage(`Importing ${lei} with its parents and subsidiaries - refresh in ~10 s.`);
      setTimeout(onIngested, 10000);
    } catch (err) {
      setMessage(err.message);
    }
  };
  return (
    <div className="card text-xs space-y-2">
      <form onSubmit={run} className="flex gap-1">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Company name (live GLEIF search)" className="flex-1 border border-gray-300 rounded px-2 py-1" />
        <button type="submit" disabled={busy} className="inline-flex items-center gap-1 px-2 py-1 rounded border border-gray-300 bg-white hover:bg-gray-100 disabled:opacity-50"><Search size={12} aria-hidden="true" /> Search</button>
      </form>
      {message && <div className="text-gray-600">{message}</div>}
      {hits?.length ? (
        <ul className="space-y-1 max-h-72 overflow-y-auto">
          {hits.map((h) => (
            <li key={h.lei} className="border border-gray-200 rounded px-2 py-1">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium truncate">{h.name}</div>
                  <div className="text-gray-500">{[h.country, h.city, h.status, h.registration_status].filter(Boolean).join(' - ')}{h.other_names?.length ? ` - aka ${h.other_names.slice(0, 2).join(', ')}` : ''}</div>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  {h.sanctions_hits > 0 && <StatusBadge tone="error">screens positive</StatusBadge>}
                  {h.tracked_company_id ? <button type="button" onClick={() => onSelect(h.tracked_company_id)} className="text-steel-700 hover:underline">tracked - open</button> : <button type="button" onClick={() => ingest(h.lei)} className="inline-flex items-center gap-1 text-steel-700 hover:underline"><Download size={11} aria-hidden="true" /> import + walk</button>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export default function Corporate() {
  const [params0] = useSearchParams();
  const [view, setView] = useState(params0.get('q') ? 'all' : 'exposure');
  const [q, setQ] = useState(params0.get('q') || '');
  const [country, setCountry] = useState('');
  const [selected, setSelected] = useState(null);
  const [starting, setStarting] = useState(false);

  const params = useMemo(() => {
    const p = new URLSearchParams({ limit: '150', sort: 'risk' });
    if (view === 'exposure') p.set('exposure_only', 'true');
    if (view === 'shell') p.set('shell', 'true');
    if (view === 'opaque') p.set('opaque', 'true');
    if (view === 'lei') p.set('has_lei', 'true');
    if (view === 'owners') p.set('origin', 'vessel_owner');
    if (q.trim()) p.set('q', q.trim());
    if (country.trim()) p.set('country', country.trim().toUpperCase());
    return p.toString();
  }, [view, q, country]);

  const { data: summary, refetch: refetchSummary } = useFetch('/api/corporate/summary', 60000);
  const { data: status } = useFetch('/api/corporate/status', 30000);
  const { data: companies, loading, refetch } = useFetch(`/api/corporate/companies?${params}`, 60000);
  const { data: chainRows } = useFetch('/api/corporate/chains?sanctioned_only=true&limit=40', 120000);
  const chains = (chainRows || []).filter((ch) => ch.chain_length > 0).slice(0, 8);

  const refreshAll = () => { refetch(); refetchSummary(); };
  const enrichNow = async () => {
    setStarting(true);
    try {
      await apiPost('/api/corporate/refresh?job=enrich', {});
      setTimeout(refreshAll, 20000);
    } catch (err) {
      alert(err.message);
    } finally {
      setStarting(false);
    }
  };

  return (
    <div>
      <PageHeader title="Corporate Intelligence" subtitle="Sanctioned companies and vessel owners resolved through GLEIF - parents, subsidiaries, shell indicators and indirect sanctions exposure">
        {status?.last_run?.enrich && <span className="text-xs text-gray-500">Last GLEIF pass {new Date(status.last_run.enrich).toLocaleTimeString()}</span>}
        <button type="button" onClick={enrichNow} disabled={starting || status?.enriching} className="flex items-center gap-1 px-2 py-1 rounded border border-gray-300 bg-white text-xs hover:bg-gray-100 disabled:opacity-50">
          <RefreshCw size={12} className={starting || status?.enriching ? 'animate-spin' : ''} aria-hidden="true" /> {status?.enriching ? 'Enriching' : 'Run GLEIF batch'}
        </button>
      </PageHeader>

      <Summary summary={summary} status={status} />

      <div className="card mb-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
          <div className="flex gap-1">
            {[['exposure', 'Sanctions exposure'], ['shell', 'Shell indicators'], ['opaque', 'Opaque ownership'], ['lei', 'Resolved (LEI)'], ['owners', 'Vessel owners'], ['all', 'All']].map(([key, text]) => (
              <button key={key} type="button" onClick={() => setView(key)} className={clsx('px-2 py-0.5 rounded border', view === key ? 'bg-steel-700 text-white border-steel-700' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-100')}>{text}</button>
            ))}
          </div>
          <label className="flex items-center gap-1">Search <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="name, LEI, address" className="border border-gray-300 rounded px-1 py-0.5 w-44" /></label>
          <label className="flex items-center gap-1">Country <input value={country} onChange={(e) => setCountry(e.target.value)} placeholder="ISO-2" maxLength={2} className="border border-gray-300 rounded px-1 py-0.5 w-14 uppercase" /></label>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2 space-y-4">
          <div className="card overflow-x-auto">
            <div className="flex items-center justify-between mb-2"><span className="card-title flex items-center gap-1"><Building2 size={12} aria-hidden="true" /> Companies ({companies?.total ?? 0})</span>{loading && <span className="text-xs text-gray-400">loading</span>}</div>
            <table className="w-full text-xs">
              <thead className="text-left text-gray-500 border-b border-gray-200">
                <tr><th className="py-1 pr-2 font-medium">Company</th><th className="py-1 pr-2 font-medium">Country</th><th className="py-1 pr-2 font-medium">Link</th><th className="py-1 pr-2 font-medium">LEI</th><th className="py-1 pr-2 font-medium text-right">Risk</th><th className="py-1 pr-2 font-medium text-right">Shell</th><th className="py-1 font-medium">Checked</th></tr>
              </thead>
              <tbody>
                {(companies?.companies || []).map((c) => (
                  <tr key={c.id} onClick={() => setSelected(c.id)} className={clsx('border-b border-gray-100 cursor-pointer hover:bg-gray-50', selected === c.id && 'bg-steel-50')}>
                    <td className="py-1 pr-2 max-w-[320px]"><div className="truncate font-medium" title={c.company_name}>{c.company_name}</div>{c.registered_address && <div className="text-gray-400 truncate">{c.registered_address}</div>}</td>
                    <td className="py-1 pr-2 font-mono">{c.registration_country || '-'}</td>
                    <td className="py-1 pr-2">{c.linked_to_sanctioned ? <StatusBadge tone={MATCH_TONE[c.sanctions_match_type] || 'warn'}>{MATCH_LABEL[c.sanctions_match_type] || c.sanctions_match_type}</StatusBadge> : <span className="text-gray-400">-</span>}</td>
                    <td className="py-1 pr-2 font-mono text-gray-500">{c.lei ? c.lei.slice(0, 8) + '…' : '-'}</td>
                    <td className="py-1 pr-2 text-right font-mono">{pct(c.risk_score)}</td>
                    <td className="py-1 pr-2 text-right font-mono">{c.shell_company_confidence ? pct(c.shell_company_confidence) : '-'}</td>
                    <td className="py-1 text-gray-500 whitespace-nowrap">{c.last_enriched ? when(c.last_enriched) : 'queued'}</td>
                  </tr>
                ))}
                {!companies?.companies?.length && !loading && <tr><td colSpan={7} className="py-2 text-gray-500">{view === 'exposure' ? 'No indirect exposure found yet - GLEIF lookups run in batches of 40 every 10 minutes across ~11,000 listed companies.' : 'Nothing matches.'}</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
        <div className="space-y-4">
          {selected ? <CompanyDetail id={selected} onSelect={setSelected} onClose={() => setSelected(null)} /> : (
            <div className="card text-sm text-gray-500">Select a company to see its LEI record, ownership chain, parents and subsidiaries. Exposure = companies that are not listed themselves but sit directly under (or above) a listed party in the GLEIF ownership tree - the EU / OFAC 50 % rule starting point.</div>
          )}
          <LeiSearch onSelect={setSelected} onIngested={refreshAll} />
          {chains?.length ? (
            <div className="card text-xs">
              <div className="card-title mb-2 flex items-center gap-1"><GitBranch size={12} aria-hidden="true" /> Highest-risk ownership chains</div>
              <ul className="space-y-1">
                {chains.map((ch) => (
                  <li key={ch.id}><button type="button" onClick={() => setSelected(ch.subsidiary_id)} className="text-steel-700 hover:underline font-medium">{ch.subsidiary_name}</button> <span className="text-gray-500">→ {ch.ultimate_owner_name} ({ch.ultimate_owner_country || '?'}) - {ch.chain_length} hop(s) - risk {pct(ch.risk_score)}</span></li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
