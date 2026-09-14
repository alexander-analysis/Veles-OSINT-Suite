/** Realised volatility per exchange and detected high-volatility clusters. */
export default function VolatilityPanel({ volatility }) {
  const exchanges = Object.entries(volatility?.exchanges || {});
  if (!exchanges.length) return <p className="text-sm text-gray-500">Not enough candles for volatility metrics yet.</p>;
  return (
    <div className="text-xs">
      <table className="w-full">
        <thead className="text-left text-gray-500 border-b border-gray-200">
          <tr>
            <th className="py-1 pr-2 font-medium">Exchange</th>
            <th className="py-1 pr-2 font-medium">Daily vol</th>
            <th className="py-1 pr-2 font-medium">Annualised</th>
            <th className="py-1 pr-2 font-medium">Max {volatility.window_minutes}m move</th>
            <th className="py-1 pr-2 font-medium">Extreme windows</th>
          </tr>
        </thead>
        <tbody>
          {exchanges.map(([name, m]) => (
            <tr key={name} className="border-b border-gray-100">
              <td className="py-1 pr-2 font-medium">{name}</td>
              <td className="py-1 pr-2 font-mono">{m.realized_volatility_daily_percent}%</td>
              <td className="py-1 pr-2 font-mono">{m.realized_volatility_annualized_percent}%</td>
              <td className="py-1 pr-2 font-mono">{m.max_window_move_percent ?? '-'}%</td>
              <td className="py-1 pr-2">{m.extreme_windows}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2">
        <span className="text-gray-500">Volatility clusters ({volatility.clusters.length}):</span>
        {volatility.clusters.length ? (
          <ul className="mt-1 space-y-0.5">
            {volatility.clusters.slice(0, 6).map((c) => (
              <li key={`${c.exchange}-${c.start}`}>
                <span className="font-medium">{c.exchange}</span> {new Date(c.start).toLocaleTimeString()} - {new Date(c.end).toLocaleTimeString()}:{' '}
                {c.windows} window(s), peak {c.multiple_of_median ?? '-'}x median
              </li>
            ))}
          </ul>
        ) : (
          <span className="ml-1 text-gray-500">none in range</span>
        )}
      </div>
    </div>
  );
}
