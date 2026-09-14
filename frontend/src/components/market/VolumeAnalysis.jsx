import { useMemo } from 'react';
import { Bar } from 'react-chartjs-2';
import { baseOptions, exchangeColor, formatLabel } from '../../services/charts';

const SPIKE_MULTIPLIER = 2;

/** Volume per exchange; bars above 2x the exchange's average in the range are highlighted red. */
export default function VolumeAnalysis({ history, spanHours = 6 }) {
  const chart = useMemo(() => {
    if (!history?.candles?.length) return null;
    const labels = history.candles.map((c) => formatLabel(c.timestamp, spanHours));
    const datasets = history.exchanges.map((exchange) => {
      const data = history.candles.map((c) => c[exchange]?.volume ?? 0);
      const mean = data.reduce((s, v) => s + v, 0) / Math.max(1, data.filter((v) => v > 0).length);
      const base = exchangeColor(exchange);
      return {
        label: exchange,
        data,
        backgroundColor: data.map((v) => (v > mean * SPIKE_MULTIPLIER ? '#b91c1c' : `${base}99`)),
        borderWidth: 0,
        barPercentage: 0.9,
        categoryPercentage: 0.9,
      };
    });
    return { labels, datasets };
  }, [history, spanHours]);

  if (!chart) return <div className="h-40 flex items-center justify-center text-sm text-gray-500">No volume data.</div>;
  const options = { ...baseOptions, scales: { ...baseOptions.scales, x: { ...baseOptions.scales.x, stacked: false } } };
  return (
    <div>
      <div className="h-44">
        <Bar data={chart} options={options} />
      </div>
      <div className="mt-1 text-xs text-gray-500">Red bars: volume above {SPIKE_MULTIPLIER}x the exchange average for the selected range.</div>
    </div>
  );
}
