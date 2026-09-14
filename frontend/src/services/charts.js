// Chart.js registration (once) and the shared exchange colour scheme.
import {
  Chart,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';

Chart.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Tooltip, Legend, Filler);

// Legend colours from the brief: binance red, kraken blue, coinbase green.
export const EXCHANGE_COLORS = {
  binance: '#ef4444',
  kraken: '#2563eb',
  coinbase: '#22c55e',
  yfinance: '#6b7280',
};

export const SEVERITY_COLORS = {
  low: '#6b7280',
  medium: '#eab308',
  high: '#f39c12',
  critical: '#b91c1c',
};

export const exchangeColor = (name) => EXCHANGE_COLORS[name] || '#4a6fa5';

export const baseOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11 } } },
    tooltip: { titleFont: { size: 11 }, bodyFont: { size: 11 } },
  },
  scales: {
    x: { ticks: { maxTicksLimit: 10, font: { size: 10 } }, grid: { display: false } },
    y: { ticks: { font: { size: 10 } }, grid: { color: '#f3f4f6' } },
  },
};

export function formatLabel(iso, spanHours) {
  const d = new Date(iso);
  if (spanHours > 48) return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit' });
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}
