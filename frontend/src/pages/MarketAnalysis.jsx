import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import { useFetch } from '../hooks/useFetch';

export default function MarketAnalysis() {
  const { data } = useFetch('/api/market/prices', 30000);
  const quotes = data?.data ?? [];

  return (
    <div>
      <PageHeader title="Market Intelligence" subtitle="Multi-exchange monitoring and anomaly detection">
        <StatusBadge tone={quotes.length ? 'ok' : 'neutral'}>
          {quotes.length ? `${quotes.length} quotes` : 'awaiting Phase 2'}
        </StatusBadge>
      </PageHeader>
      <div className="card">
        <div className="card-title">Status</div>
        <p className="mt-2 text-sm text-gray-600">
          The market bot (Phase 2) will populate this page with live prices from Binance, Kraken and Coinbase,
          3-sigma price anomalies, volume spikes and cross-exchange coordination events.
        </p>
        {quotes.length > 0 && (
          <ul className="mt-3 text-sm font-mono">
            {quotes.map((q) => (
              <li key={`${q.asset}-${q.exchange}`}>
                {q.asset} / {q.exchange}: {q.price}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
