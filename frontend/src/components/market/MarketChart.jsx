import { useMemo } from 'react';
import { Line } from 'react-chartjs-2';
import { baseOptions, exchangeColor, formatLabel, SEVERITY_COLORS } from '../../services/charts';

/**
 * Multi-exchange close-price chart with alert markers.
 * `history` is the /api/market/history response.
 */
export default function MarketChart({ history, spanHours = 6 }) {
  const chart = useMemo(() => {
    if (!history?.candles?.length) return null;
    const labels = history.candles.map((c) => formatLabel(c.timestamp, spanHours));
    const datasets = history.exchanges.map((exchange) => ({
      label: exchange,
      data: history.candles.map((c) => c[exchange]?.close ?? null),
      borderColor: exchangeColor(exchange),
      backgroundColor: exchangeColor(exchange),
      borderWidth: 1.5,
      pointRadius: 0,
      spanGaps: true,
      tension: 0.1,
    }));
    // Alert markers: nearest candle to each anomaly timestamp
    const times = history.candles.map((c) => new Date(c.timestamp).getTime());
    const markers = new Array(labels.length).fill(null);
    const colors = new Array(labels.length).fill('transparent');
    for (const a of history.anomalies_in_period || []) {
      const t = new Date(a.timestamp).getTime();
      let best = 0;
      for (let i = 1; i < times.length; i += 1) if (Math.abs(times[i] - t) < Math.abs(times[best] - t)) best = i;
      markers[best] = a.price ?? history.candles[best].composite?.close ?? null;
      colors[best] = SEVERITY_COLORS[a.severity] || '#b91c1c';
    }
    if (markers.some((m) => m != null)) {
      datasets.push({
        label: 'alerts',
        data: markers,
        type: 'line',
        showLine: false,
        pointRadius: 6,
        pointStyle: 'triangle',
        pointBackgroundColor: colors,
        pointBorderColor: colors,
        borderColor: 'transparent',
      });
    }
    return { labels, datasets };
  }, [history, spanHours]);

  if (!chart) {
    return <div className="h-64 flex items-center justify-center text-sm text-gray-500">No candle data for this range yet.</div>;
  }
  return (
    <div className="h-72">
      <Line data={chart} options={baseOptions} />
    </div>
  );
}
