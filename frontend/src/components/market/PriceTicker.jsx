import clsx from 'clsx';
import { exchangeColor } from '../../services/charts';

/** Latest price per exchange for one asset. */
export default function PriceTicker({ quotes }) {
  if (!quotes?.length) return <p className="text-sm text-gray-500">No prices yet - the bot fetches every 60 s.</p>;
  return (
    <div className="grid gap-3 grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
      {quotes.map((q) => (
        <div key={q.exchange} className="card py-3">
          <div className="flex items-center justify-between">
            <span className="card-title" style={{ color: exchangeColor(q.exchange) }}>
              {q.exchange}
            </span>
            <span className="text-[10px] text-gray-400" title="Data freshness">
              q{q.signal_quality ?? '-'}
            </span>
          </div>
          <div className="mt-1 text-lg font-semibold font-mono">
            {q.price.toLocaleString(undefined, { maximumFractionDigits: q.price < 10 ? 4 : 2 })}
          </div>
          <div className="text-xs text-gray-500 flex justify-between">
            <span className={clsx(q['24h_change_percent'] > 0 && 'text-green-700', q['24h_change_percent'] < 0 && 'text-red-700')}>
              {q['24h_change_percent'] == null ? '24h: n/a' : `${q['24h_change_percent'] > 0 ? '+' : ''}${q['24h_change_percent'].toFixed(2)}% 24h`}
            </span>
            <span>{new Date(q.timestamp).toLocaleTimeString()}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
