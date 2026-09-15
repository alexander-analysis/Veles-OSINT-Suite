import { Link } from 'react-router-dom';
import { X } from 'lucide-react';
import StatusBadge from '../common/StatusBadge';
import LoadingSpinner from '../common/LoadingSpinner';
import { useFetch } from '../../hooks/useFetch';

const AUTHORITY_TONE = { OFAC: 'error', EU: 'warn', UN: 'neutral' };
const fmtDate = (d) => (d ? new Date(d).toLocaleDateString() : '-');
const usd = (n) => (n == null ? '-' : `$${Math.round(n).toLocaleString()}`);

function Section({ title, count, children }) {
  if (!count) return null;
  return (
    <div>
      <div className="text-xs font-semibold text-steel-700 mb-1">{title} ({count})</div>
      {children}
    </div>
  );
}

/** Everything VELES holds on one listed party, pulled from every domain bot. */
export default function EntityDossier({ entityId, onClose }) {
  const { data, loading, error } = useFetch(entityId ? `/api/sanctions/entities/${entityId}/dossier` : null, 120000);
  if (!entityId) return null;
  const e = data?.entity;
  const total = data ? ['vessels', 'companies', 'wallets', 'domains', 'legal_events', 'aircraft'].reduce((s, k) => s + (data[k]?.length || 0), 0) : 0;
  return (
    <div className="card border-steel-300">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <div className="card-title">Entity dossier</div>
          {e && (
            <div className="text-sm font-medium flex flex-wrap items-center gap-2">
              {e.name}
              {e.designating_authorities?.map((a) => <StatusBadge key={a} tone={AUTHORITY_TONE[a]}>{a}</StatusBadge>)}
              <StatusBadge>{e.entity_type}</StatusBadge>
              <span className="text-xs text-gray-500">{(e.programs || []).join(', ')} - designated {fmtDate(e.designation_date)}</span>
            </div>
          )}
        </div>
        {onClose && <button type="button" onClick={onClose} className="text-gray-500 hover:text-gray-800" aria-label="close dossier"><X size={14} /></button>}
      </div>
      {loading && !data && <LoadingSpinner label="Compiling dossier" />}
      {error && <div className="text-sm text-red-700">{error.message}</div>}
      {data && (
        <div className="space-y-3 text-sm">
          {data.other_listings?.length > 0 && (
            <div className="text-xs text-gray-600">Also listed by {data.other_listings.map((o) => `${o.authority} (${(o.programs || []).join(', ') || 'n/a'})`).join('; ')}</div>
          )}
          {total === 0 && <p className="text-sm text-gray-500">No vessel, company, wallet, domain, legal event or aircraft is linked to this listing yet - the domain bots attach records as they find them.</p>}
          <div className="grid gap-4 xl:grid-cols-2">
            <Section title="Vessels" count={data.vessels?.length}>
              <ul className="space-y-1">{data.vessels.map((b) => <li key={b.id}><Link to={`/maritime/vessel/${b.mmsi}`} className="font-medium text-steel-700 hover:underline">{b.vessel_name}</Link> <span className="text-xs text-gray-500">({b.flag}{b.imo ? `, IMO ${b.imo}` : ''}) {b.breach_type.replace(/_/g, ' ')} {Math.round((b.match_confidence || 0) * 100)}% - {b.severity} - {b.status}</span></li>)}</ul>
            </Section>
            <Section title="Companies" count={data.companies?.length}>
              <ul className="space-y-1">{data.companies.map((c) => <li key={c.id}><span className="font-medium">{c.company_name}</span> <span className="text-xs text-gray-500">{c.registration_country || '?'}{c.lei ? ` - LEI ${c.lei}` : ''} - {c.sanctions_match_type || 'linked'}{c.risk_score != null ? ` - risk ${Math.round(c.risk_score * 100)}%` : ''}</span>{c.is_shell_company ? <StatusBadge tone="warn">shell</StatusBadge> : null}{c.ownership_opaque ? <StatusBadge tone="neutral">opaque</StatusBadge> : null}</li>)}</ul>
              {data.ownership_chains?.length > 0 && <ul className="mt-1 space-y-0.5 text-xs text-gray-600">{data.ownership_chains.map((ch, i) => <li key={i}>{ch.subsidiary_name} {'->'} {ch.ultimate_owner_name} ({ch.ultimate_owner_country || '?'}), {ch.chain_length} hop(s){ch.involves_sanctioned ? ' - sanctioned party in chain' : ''}</li>)}</ul>}
            </Section>
            <Section title={`Wallets - ${usd(data.wallet_balance_usd)}`} count={data.wallets?.length}>
              <ul className="space-y-1">{data.wallets.map((w) => <li key={w.id}><span className="font-mono text-xs">{w.address}</span> <span className="text-xs text-gray-500">{w.blockchain} - {usd(w.balance_usd)} - {w.transaction_count ?? 0} tx{w.last_active ? ` - active ${fmtDate(w.last_active)}` : ''}</span></li>)}</ul>
              {data.transfers?.length > 0 && <ul className="mt-1 space-y-0.5 text-xs text-gray-600">{data.transfers.slice(0, 10).map((t) => <li key={t.id}>{fmtDate(t.timestamp)} {usd(t.amount_usd)} {t.token || ''} {t.pattern ? `- ${t.pattern.replace(/_/g, ' ')}` : ''}{t.destination_entity ? ` -> ${t.destination_entity}` : ''}</li>)}</ul>}
            </Section>
            <Section title="Domains" count={data.domains?.length}>
              <ul className="space-y-1">{data.domains.map((d) => <li key={d.id}><span className="font-mono text-xs">{d.value}</span> <span className="text-xs text-gray-500">{d.is_live ? 'live' : 'down'}{d.hosting_country ? ` - ${d.hosting_country}` : ''}{d.asn_org ? ` - ${d.asn_org}` : ''}{d.registrar ? ` - ${d.registrar}` : ''}{d.certificate_count ? ` - ${d.certificate_count} certs` : ''}{d.risk_score != null ? ` - risk ${Math.round(d.risk_score * 100)}%` : ''}</span></li>)}</ul>
            </Section>
            <Section title="Legal events" count={data.legal_events?.length}>
              <ul className="space-y-1">{data.legal_events.map((l) => <li key={l.id}><span className="text-xs text-gray-500">{fmtDate(l.event_date)}</span> {l.url ? <a href={l.url} target="_blank" rel="noreferrer" className="text-steel-700 hover:underline">{l.title}</a> : l.title} <span className="text-xs text-gray-500">{l.source.replace(/_/g, ' ')}{l.event_type ? ` - ${l.event_type}` : ''}{l.court ? ` - ${l.court}` : ''}{l.penalty_usd ? ` - ${usd(l.penalty_usd)}` : ''}</span></li>)}</ul>
            </Section>
            <Section title="Aircraft" count={data.aircraft?.length}>
              <ul className="space-y-1">{data.aircraft.map((a) => <li key={a.id}><span className="font-medium">{a.registration}</span> <span className="text-xs text-gray-500">{a.model || ''}{a.operator ? ` - ${a.operator}` : ''} - {a.sightings_count || 0} sightings{a.last_seen ? ` - last ${fmtDate(a.last_seen)}` : ''}</span></li>)}</ul>
            </Section>
          </div>
        </div>
      )}
    </div>
  );
}
