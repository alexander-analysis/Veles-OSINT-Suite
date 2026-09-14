import { useState } from 'react';
import clsx from 'clsx';
import { AlertTriangle, Activity, Link2, Flame, Check } from 'lucide-react';
import { apiPost } from '../../services/api';

const SEVERITY = {
  low: 'border-gray-300 bg-white',
  medium: 'border-yellow bg-yellow-50',
  high: 'border-orange bg-orange-50',
  critical: 'border-red bg-red-50',
};
const SEVERITY_TEXT = { low: 'text-gray-600', medium: 'text-yellow-700', high: 'text-orange-700', critical: 'text-red-700' };
const TYPE_ICON = { price_anomaly: Activity, volume_spike: AlertTriangle, coordination: Link2, liquidation: Flame };

/** One market alert card with an acknowledge action. */
export default function AnomalyAlert({ alert, onChange }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const Icon = TYPE_ICON[alert.alert_type] || AlertTriangle;

  const acknowledge = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/api/market/alerts/${alert.id}/acknowledge`, { acknowledged_by: 'analyst' });
      onChange?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={clsx('border rounded-md p-3 text-sm', SEVERITY[alert.severity] || SEVERITY.low, alert.acknowledged && 'opacity-60')}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 font-medium">
          <Icon size={16} className={SEVERITY_TEXT[alert.severity]} aria-hidden="true" />
          <span>{alert.asset}</span>
          <span className="text-xs font-normal text-gray-500">{alert.alert_type.replace('_', ' ')}</span>
          <span className={clsx('text-xs uppercase tracking-wide font-semibold', SEVERITY_TEXT[alert.severity])}>{alert.severity}</span>
        </div>
        <span className="text-xs text-gray-500 whitespace-nowrap">{new Date(alert.timestamp).toLocaleString()}</span>
      </div>
      <p className="mt-1 text-gray-700">{alert.intelligence_summary || 'No summary'}</p>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500">
        <span>
          {(alert.exchanges_involved || []).join(', ')}
          {alert.price_change_percent != null && ` - ${alert.price_change_percent > 0 ? '+' : ''}${alert.price_change_percent.toFixed(2)}%`}
          {alert.volume_multiplier != null && ` - ${alert.volume_multiplier.toFixed(1)}x volume`}
          {alert.confidence_score != null && ` - confidence ${(alert.confidence_score * 100).toFixed(0)}%`}
        </span>
        {alert.acknowledged ? (
          <span className="flex items-center gap-1 text-green-700">
            <Check size={12} aria-hidden="true" /> acknowledged by {alert.acknowledged_by}
          </span>
        ) : (
          <button
            type="button"
            onClick={acknowledge}
            disabled={busy}
            className="px-2 py-1 rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-700 disabled:opacity-50"
          >
            {busy ? 'Saving' : 'Acknowledge'}
          </button>
        )}
      </div>
      {error && <div className="mt-1 text-xs text-red-700">{error}</div>}
    </div>
  );
}
