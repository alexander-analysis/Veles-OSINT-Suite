import { Link } from 'react-router-dom';
import { TrendingUp, Ship, Activity, Database, Clock, ShieldAlert, FileDown, AlertTriangle, Globe, Coins, Building2, Fuel, Layers, Eye } from 'lucide-react';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useFetch } from '../hooks/useFetch';
import { downloadFile } from '../services/api';

function formatUptime(seconds) {
  if (seconds == null) return '-';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m ${Math.floor(seconds % 60)}s`;
}

function formatBytes(bytes) {
  if (bytes == null) return '-';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const time = (iso) => (iso ? new Date(iso).toLocaleString() : 'no data yet');

function Tile({ icon: Icon, title, value, detail, tone, to }) {
  const body = (
    <div className="card h-full">
      <div className="flex items-center justify-between">
        <span className="card-title">{title}</span>
        <Icon size={16} className="text-gray-400" aria-hidden="true" />
      </div>
      <div className="mt-2 flex items-center gap-2">
        <span className="text-xl font-semibold">{value}</span>
        {tone && <StatusBadge tone={tone}>{tone === 'ok' ? 'healthy' : tone === 'warn' ? 'attention' : tone === 'error' ? 'alert' : 'idle'}</StatusBadge>}
      </div>
      {detail && <div className="mt-1 text-xs text-gray-500">{detail}</div>}
    </div>
  );
  return to ? <Link to={to} className="block hover:opacity-90">{body}</Link> : body;
}

const SIGNIFICANT = 'breach_detected,transshipment_detected,high_risk_port_call,escalated,cleared,sanctions_list_refreshed,alert_acknowledged,export,config_updated';

export default function Dashboard() {
  const { data: health, error, loading, updatedAt } = useFetch('/api/health', 15000);
  const { data: alerts } = useFetch('/api/market/alerts?acknowledged=false&limit=5&severity=high,critical', 30000);
  const { data: breaches } = useFetch('/api/maritime/breaches?limit=5', 30000);
  const { data: events } = useFetch(`/api/maritime/audit-log?action_type=${SIGNIFICANT}&limit=12`, 30000);
  const { data: geo } = useFetch('/api/geopolitical/summary?hours=24', 60000);
  const { data: geoAlerts } = useFetch('/api/geopolitical/alerts?hours=48&limit=5', 60000);
  const { data: chain } = useFetch('/api/blockchain/summary?hours=24', 60000);
  const { data: corp } = useFetch('/api/corporate/summary', 120000);
  const { data: energy } = useFetch('/api/energy/summary?days=7', 120000);
  const { data: fusion } = useFetch('/api/fusion/summary?hours=48', 60000);
  const { data: aviationSummary } = useFetch('/api/aviation/summary?days=7', 120000);
  const { data: leaksSummary } = useFetch('/api/leaks/summary?days=7', 120000);
  const market = health?.bots?.market;
  const maritime = health?.bots?.maritime;
  const sanctions = health?.bots?.sanctions;
  const listings = sanctions ? Object.values(sanctions.active_listings || {}).reduce((s, v) => s + v, 0) : 0;
  const backendTone = error ? 'error' : health?.status === 'ok' ? 'ok' : 'warn';

  const report = (path, name) => downloadFile(path, name).catch((err) => alert(err.message));

  return (
    <div>
      <PageHeader title="Intelligence Dashboard" subtitle="Live status across market, sanctions and maritime collection">
        {updatedAt && <span className="text-xs text-gray-500">Refreshed {updatedAt.toLocaleTimeString()}</span>}
      </PageHeader>

      {loading && !health && <LoadingSpinner label="Contacting backend" />}
      {error && (
        <div className="card border-red mb-6">
          <div className="card-title text-red-700">Backend unreachable</div>
          <div className="mt-1 text-sm text-red-700">{error.message}</div>
        </div>
      )}

      {fusion?.top_alerts?.length ? (
        <div className="card mb-4 border-red">
          <div className="card-title mb-2 flex items-center gap-1 text-red-700"><Layers size={12} aria-hidden="true" /> Composite alerts - multiple domains lit up together</div>
          <ul className="space-y-1 text-sm">
            {fusion.top_alerts.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2">
                <StatusBadge tone={a.severity === 'critical' || a.severity === 'high' ? 'error' : 'warn'}>{a.severity}</StatusBadge>
                <Link to="/fusion" className="font-medium text-steel-700 hover:underline">{a.title}</Link>
                <span className="text-xs text-gray-500">{a.signals} signals - {a.domains.join(', ')} - {Math.round((a.confidence || 0) * 100)}% - {new Date(a.detected_at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6 mb-4">
        <Tile icon={Eye} title="Monitors (7d)" value={aviationSummary ? aviationSummary.seen_recently : '-'} detail={aviationSummary && leaksSummary ? `listed aircraft seen - ${leaksSummary.events} relevant breaches, ${leaksSummary.tracked_company_hits} on tracked companies` : undefined} tone={aviationSummary ? (aviationSummary.seen_recently ? 'warn' : 'ok') : undefined} to="/monitors" />
        <Tile icon={Layers} title="Fusion (48h)" value={fusion ? fusion.open_composite_alerts : '-'} detail={fusion ? `${fusion.critical_open} critical composite - ${fusion.correlations} cross-domain links` : undefined} tone={fusion ? (fusion.critical_open ? 'error' : fusion.open_composite_alerts ? 'warn' : 'ok') : undefined} to="/fusion" />
        <Tile icon={Fuel} title="Sanctioned oil shipments (7d)" value={energy ? energy.sanctioned_shipments : '-'} detail={energy ? `${Object.values(energy.dark_oil_indicators || {}).reduce((s, n) => s + n, 0)} dark-oil indicators - ${energy.tankers_at_facilities_now} tankers at watched facilities` : undefined} tone={energy ? (Object.values(energy.dark_oil_indicators || {}).reduce((s, n) => s + n, 0) ? 'warn' : 'ok') : undefined} to="/energy" />
        <Tile icon={Building2} title="Corporate exposure" value={corp ? corp.exposure : '-'} detail={corp ? `${corp.companies.toLocaleString()} companies - ${corp.with_lei} resolved - ${corp.shell_companies} shell indicators` : undefined} tone={corp ? (corp.exposure ? 'warn' : 'ok') : undefined} to="/corporate" />
        <Tile icon={Coins} title="Sanctioned crypto wallets" value={chain ? chain.sanctioned_wallets_total : '-'} detail={chain ? `$${Math.round(chain.sanctioned_balance_usd || 0).toLocaleString()} held - ${chain.sanctioned_wallets_active} active 24h` : undefined} tone={chain ? (chain.sanctioned_wallets_active ? 'error' : 'ok') : undefined} to="/blockchain" />
        <Tile icon={Globe} title="Geopolitical events (24h)" value={geo ? geo.total : '-'} detail={geo ? `${(geo.by_severity?.critical || 0) + (geo.by_severity?.high || 0)} high/critical - ${geo.correlations} cross-domain links` : undefined} tone={geo ? ((geo.by_severity?.critical || 0) ? 'error' : (geo.by_severity?.high || 0) ? 'warn' : 'ok') : undefined} to="/geopolitical" />
        <Tile icon={Ship} title="Vessels tracked" value={maritime ? maritime.vessels_tracked.toLocaleString() : '-'} detail={maritime ? `${maritime.vessels_active_1h} active last hour - ${Object.keys(maritime.sources).join(', ') || 'no sources'}` : undefined} tone={maritime ? (maritime.vessels_active_1h ? 'ok' : 'warn') : undefined} to="/maritime" />
        <Tile icon={ShieldAlert} title="Open sanctions breaches" value={maritime ? maritime.open_breaches : '-'} detail={sanctions ? `${listings.toLocaleString()} active listings indexed` : undefined} tone={maritime ? (maritime.open_breaches ? 'error' : 'ok') : undefined} to="/maritime" />
        <Tile icon={TrendingUp} title="Open market alerts" value={market ? market.open_alerts : '-'} detail={market ? `${market.candles_stored.toLocaleString()} candles - last fetch ${market.last_fetch_at ? new Date(market.last_fetch_at).toLocaleTimeString() : '-'}` : undefined} tone={market ? (market.open_alerts ? 'warn' : 'ok') : undefined} to="/market" />
        <Tile icon={Activity} title="Backend" value={health ? `v${health.version}` : '-'} detail={health ? `${health.environment} - up ${formatUptime(health.uptime_seconds)} - ${health.scheduler.jobs.length} jobs` : undefined} tone={health ? backendTone : undefined} />
      </div>

      <div className="grid gap-4 md:grid-cols-3 mb-6 text-xs">
        <div className="card py-3"><div className="card-title flex items-center gap-1"><Database size={12} aria-hidden="true" /> Database</div><div className="mt-1">{health ? `${health.database.dialect} - ${formatBytes(health.database.size_bytes)}` : '-'}</div><div className="text-gray-500">market {time(health?.last_market_update)} - AIS {time(health?.last_ais_update)}</div></div>
        <div className="card py-3"><div className="card-title flex items-center gap-1"><Clock size={12} aria-hidden="true" /> Streams</div><div className="mt-1">{maritime ? `${maritime.stream.clients} live map client(s), ${maritime.stream.messages_sent} frames` : '-'}</div><div className="text-gray-500">{market?.liquidation_stream?.connected ? 'Binance liquidation stream connected' : 'liquidation stream offline'}</div></div>
        <div className="card py-3">
          <div className="card-title flex items-center gap-1"><FileDown size={12} aria-hidden="true" /> Intelligence reports</div>
          <div className="mt-1 flex flex-wrap gap-1">
            <button type="button" onClick={() => report('/api/maritime/report?days=7&format=pdf', 'VELES_Maritime_Report.pdf')} className="px-2 py-0.5 border border-gray-300 rounded bg-white hover:bg-gray-100">Maritime 7d (PDF)</button>
            <button type="button" onClick={() => report('/api/sanctions/report/7days?format=pdf', 'VELES_Sanctions_Report.pdf')} className="px-2 py-0.5 border border-gray-300 rounded bg-white hover:bg-gray-100">Sanctions 7d (PDF)</button>
            <button type="button" onClick={() => report('/api/market/export/7d?format=pdf', 'VELES_Market_Brief.pdf')} className="px-2 py-0.5 border border-gray-300 rounded bg-white hover:bg-gray-100">Market 7d (PDF)</button>
            <button type="button" onClick={() => report('/api/fusion/brief?hours=24&format=pdf', 'VELES_Intelligence_Brief.pdf')} className="px-2 py-0.5 border border-steel-700 text-steel-700 rounded bg-white hover:bg-steel-50 font-medium">Cross-domain brief 24h (PDF)</button>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-4">
        <div className="card">
          <div className="card-title mb-2 flex items-center gap-1"><Globe size={12} aria-hidden="true" /> Geopolitical alerts</div>
          {geoAlerts?.events?.length ? (
            <ul className="space-y-1 text-sm">
              {geoAlerts.events.map((e) => (
                <li key={e.id}>
                  <Link to="/geopolitical" className="font-medium text-steel-700 hover:underline line-clamp-2">{e.title}</Link>
                  <span className="text-xs text-gray-500">{e.event_type.replace(/_/g, ' ')} - {e.severity} - {e.country_primary || '-'} - {new Date(e.event_date).toLocaleTimeString()}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-gray-500">No high/critical events in the last 48 h.</p>}
        </div>
        <div className="card">
          <div className="card-title mb-2 flex items-center gap-1"><ShieldAlert size={12} aria-hidden="true" /> Top sanctions matches</div>
          {breaches?.breaches?.length ? (
            <ul className="space-y-1 text-sm">
              {breaches.breaches.map((b) => (
                <li key={b.id}>
                  <Link to={`/maritime/vessel/${b.mmsi}`} className="font-medium text-steel-700 hover:underline">{b.vessel_name}</Link>
                  <span className="text-xs text-gray-500"> ({b.flag}) - {b.sanctioning_authority} {Math.round((b.match_confidence || 0) * 100)}% - {b.sanctioned_entity}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-gray-500">No open matches.</p>}
        </div>
        <div className="card">
          <div className="card-title mb-2 flex items-center gap-1"><AlertTriangle size={12} aria-hidden="true" /> Unacknowledged market alerts</div>
          {alerts?.alerts?.length ? (
            <ul className="space-y-1 text-sm">
              {alerts.alerts.map((a) => (
                <li key={a.id}><span className="font-medium">{a.asset}</span> <span className="text-xs text-gray-500">{a.alert_type.replace('_', ' ')} - {a.severity} - {new Date(a.timestamp).toLocaleTimeString()}</span><div className="text-xs text-gray-600">{a.intelligence_summary}</div></li>
              ))}
            </ul>
          ) : <p className="text-sm text-gray-500">No high/critical alerts pending.</p>}
        </div>
        <div className="card">
          <div className="card-title mb-2 flex items-center gap-1"><Clock size={12} aria-hidden="true" /> Recent significant events</div>
          {events?.entries?.length ? (
            <ul className="space-y-1 text-xs">
              {events.entries.map((e) => (
                <li key={e.id}><span className="text-gray-500">{new Date(e.timestamp).toLocaleString()}</span> <span className="font-medium">{e.action_type.replace(/_/g, ' ')}</span> <span className="text-gray-500">by {e.user}</span><div className="text-gray-600 line-clamp-2">{e.rationale}</div></li>
              ))}
            </ul>
          ) : <p className="text-sm text-gray-500">Nothing recorded yet.</p>}
          <Link to="/audit" className="mt-2 inline-block text-xs text-steel-600 hover:underline">Open audit log &rarr;</Link>
        </div>
      </div>
    </div>
  );
}
