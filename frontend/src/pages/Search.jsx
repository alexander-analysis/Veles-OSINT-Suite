import { Link, useSearchParams } from 'react-router-dom';
import { Ship, ShieldAlert, Building2, Coins, Plane, Globe2, Newspaper, Scale, Anchor, Globe } from 'lucide-react';
import PageHeader from '../components/common/PageHeader';
import LoadingSpinner from '../components/common/LoadingSpinner';
import StatusBadge from '../components/common/StatusBadge';
import { useFetch } from '../hooks/useFetch';

const GROUPS = {
  vessels: { label: 'Vessels', icon: Ship },
  listings: { label: 'Sanctions listings', icon: ShieldAlert },
  companies: { label: 'Companies', icon: Building2 },
  wallets: { label: 'Wallets', icon: Coins },
  aircraft: { label: 'Aircraft', icon: Plane },
  domains: { label: 'Domains and hosts', icon: Globe2 },
  events: { label: 'Geopolitical events', icon: Globe },
  narratives: { label: 'Narratives', icon: Newspaper },
  legal: { label: 'Legal events', icon: Scale },
  port_state_control: { label: 'Port state control', icon: Anchor },
};
const AUTHORITY_TONE = { OFAC: 'error', EU: 'warn', UN: 'neutral' };

/** One query across every domain; each hit links to the page that owns it. */
export default function Search() {
  const [params] = useSearchParams();
  const q = (params.get('q') || '').trim();
  const { data, loading, error } = useFetch(q.length >= 2 ? `/api/search?q=${encodeURIComponent(q)}&per_kind=10` : null, 0);
  return (
    <div>
      <PageHeader title="Search" subtitle={q ? `"${q}" across vessels, listings, companies, wallets, aircraft, domains, events, narratives, legal and port state control` : 'Type at least two characters in the search box'}>
        {data && <StatusBadge tone={data.total ? 'ok' : 'neutral'}>{data.total} hit(s)</StatusBadge>}
      </PageHeader>
      {loading && !data && <LoadingSpinner label="Searching" />}
      {error && <div className="card border-red text-red-700 text-sm">{error.message}</div>}
      {data && data.total === 0 && <p className="text-sm text-gray-500">Nothing matches. Names are matched as substrings; MMSI, IMO and LEI exactly.</p>}
      <div className="grid gap-4 xl:grid-cols-2">
        {data && Object.entries(data.groups).map(([key, hits]) => {
          const meta = GROUPS[key] || { label: key, icon: Globe };
          const Icon = meta.icon;
          return (
            <div key={key} className="card">
              <div className="card-title mb-2 flex items-center gap-2"><Icon size={14} aria-hidden="true" /> {meta.label} ({hits.length})</div>
              <ul className="space-y-1.5 text-sm">
                {hits.map((h) => (
                  <li key={`${h.kind}-${h.id}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <Link to={h.href} className="font-medium text-steel-700 hover:underline">{h.title}</Link>
                      {h.authority && <StatusBadge tone={AUTHORITY_TONE[h.authority]}>{h.authority}</StatusBadge>}
                      {h.status && h.status !== 'clear' && <StatusBadge tone={h.status.startsWith('breach') ? 'error' : 'warn'}>{h.status}</StatusBadge>}
                      {h.url && <a href={h.url} target="_blank" rel="noreferrer" className="text-xs text-gray-500 hover:underline">source</a>}
                    </div>
                    <div className="text-xs text-gray-600">{h.subtitle}</div>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}
