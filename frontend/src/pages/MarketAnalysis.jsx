import { useMemo, useState } from 'react';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import PriceTicker from '../components/market/PriceTicker';
import MarketChart from '../components/market/MarketChart';
import VolumeAnalysis from '../components/market/VolumeAnalysis';
import AnomalyAlert from '../components/market/AnomalyAlert';
import CoordinationBoard from '../components/market/CoordinationBoard';
import VolatilityPanel from '../components/market/VolatilityPanel';
import { useFetch } from '../hooks/useFetch';

// Range -> (hours, server-side resample timeframe)
const RANGES = {
  '1h': { hours: 1, timeframe: '1m' },
  '6h': { hours: 6, timeframe: '1m' },
  '24h': { hours: 24, timeframe: '5m' },
  '7d': { hours: 168, timeframe: '1h' },
};
const SEVERITIES = ['all', 'medium', 'high', 'critical'];
const SEVERITY_QUERY = { all: '', medium: 'medium,high,critical', high: 'high,critical', critical: 'critical' };

const Select = ({ value, onChange, options }) => (
  <select value={value} onChange={(e) => onChange(e.target.value)} className="border border-gray-300 rounded px-2 py-1 text-sm bg-white">
    {options.map((o) => (
      <option key={o} value={o}>
        {o}
      </option>
    ))}
  </select>
);

export default function MarketAnalysis() {
  const { data: config } = useFetch('/api/admin/config', 0);
  const { data: prices } = useFetch('/api/market/prices', 30000);
  const assets = useMemo(() => {
    const configured = config?.market?.assets || [];
    const seen = new Set([...configured, ...(prices?.data || []).map((q) => q.asset)]);
    return [...seen];
  }, [config, prices]);

  const [asset, setAsset] = useState('BTC');
  const [range, setRange] = useState('6h');
  const [severity, setSeverity] = useState('all');
  const { hours, timeframe } = RANGES[range];

  const { data: history, loading: historyLoading } = useFetch(`/api/market/history/${asset}?hours=${hours}&timeframe=${timeframe}`, 30000);
  const { data: volatility } = useFetch(`/api/market/volatility/${asset}?hours=${Math.max(hours, 6)}`, 60000);
  const sevQuery = SEVERITY_QUERY[severity] ? `&severity=${SEVERITY_QUERY[severity]}` : '';
  const { data: alerts, refetch: refetchAlerts } = useFetch(`/api/market/alerts?limit=30${sevQuery}`, 30000);
  const { data: coordination, refetch: refetchCoordination } = useFetch('/api/market/coordination?limit=100', 30000);

  const quotes = (prices?.data || []).filter((q) => q.asset === asset);
  const openAlerts = alerts?.alerts?.filter((a) => !a.acknowledged).length ?? 0;

  return (
    <div>
      <PageHeader title="Market Intelligence" subtitle="Multi-exchange monitoring, anomaly and coordination detection">
        <StatusBadge tone={openAlerts ? 'warn' : 'ok'}>{openAlerts} open alert(s)</StatusBadge>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-3 mb-4 text-sm">
        <label className="flex items-center gap-2">
          Asset <Select value={asset} onChange={setAsset} options={assets.length ? assets : ['BTC']} />
        </label>
        <label className="flex items-center gap-2">
          Range <Select value={range} onChange={setRange} options={Object.keys(RANGES)} />
        </label>
        <label className="flex items-center gap-2">
          Alert severity <Select value={severity} onChange={setSeverity} options={SEVERITIES} />
        </label>
        {historyLoading && <LoadingSpinner label="Loading candles" />}
      </div>

      <section className="mb-6">
        <PriceTicker quotes={quotes} />
      </section>

      <div className="grid gap-4 xl:grid-cols-3 mb-6">
        <div className="card xl:col-span-2">
          <div className="card-title mb-2">
            {asset} price by exchange - {range} ({timeframe} candles)
          </div>
          <MarketChart history={history} spanHours={hours} />
        </div>
        <div className="card">
          <div className="card-title mb-2">Volatility - last {Math.max(hours, 6)}h</div>
          <VolatilityPanel volatility={volatility} />
        </div>
      </div>

      <div className="card mb-6">
        <div className="card-title mb-2">Volume by exchange</div>
        <VolumeAnalysis history={history} spanHours={hours} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <div className="card">
          <div className="card-title mb-3">Anomaly alerts {alerts ? `(${alerts.total})` : ''}</div>
          {alerts?.alerts?.length ? (
            <div className="space-y-2 max-h-[32rem] overflow-y-auto pr-1">
              {alerts.alerts.map((a) => (
                <AnomalyAlert key={a.id} alert={a} onChange={refetchAlerts} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500">No alerts match. Detectors run every 5 minutes (3-sigma price, 2x volume, coordination, liquidation cascades).</p>
          )}
        </div>
        <div className="card">
          <div className="card-title mb-3">Cross-exchange coordination</div>
          <CoordinationBoard events={coordination?.events} onChange={refetchCoordination} />
        </div>
      </div>
    </div>
  );
}
