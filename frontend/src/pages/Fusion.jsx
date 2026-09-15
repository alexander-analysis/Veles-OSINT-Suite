import { useMemo, useState } from 'react';
import { Bar } from 'react-chartjs-2';
import { Layers, RefreshCw, CheckCircle2, Link2, Radar } from 'lucide-react';
import clsx from 'clsx';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import { useFetch } from '../hooks/useFetch';
import { apiPost } from '../services/api';
import { baseOptions } from '../services/charts';

const DOMAINS = ['market', 'maritime', 'sanctions', 'geopolitical', 'blockchain', 'corporate', 'energy'];
const DOMAIN_COLOR = { market: '#2563eb', maritime: '#0e7490', sanctions: '#7f1d1d', geopolitical: '#7c3aed', blockchain: '#b45309', corporate: '#065f46', energy: '#c2410c' };
const DOMAIN_LINK = { market: '/market', maritime: '/maritime', sanctions: '/sanctions', geopolitical: '/geopolitical', blockchain: '/blockchain', corporate: '/corporate', energy: '/energy' };
const SEVERITY_TONE = { critical: 'error', high: 'error', medium: 'warn', low: 'neutral' };
const label = (s) => (s || '').replace(/_/g, ' ');
const when = (iso) => (iso ? new Date(iso).toLocaleString() : '-');

function signalLink(item) {
  if (item.type === 'sanctions_breach' || item.type === 'evasion_event' || item.type === 'port_call' || item.type === 'dark_oil' || item.type === 'oil_shipment' || item.type === 'transshipment') {
    const mmsi = item.keys?.vessel?.[0];
    return mmsi ? `/maritime/vessel/${mmsi}` : DOMAIN_LINK[item.domain];
  }
  return DOMAIN_LINK[item.domain] || '/';
}

function Timeline({ data }) {
  if (!data?.buckets?.length) return <p className="text-sm text-gray-500">No signals in the window yet.</p>;
  const labels = data.buckets.map((b) => new Date(b.time).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit' }));
  const chart = {
    labels,
    datasets: data.domains.map((d) => ({ label: d, data: data.buckets.map((b) => b[d] || 0), backgroundColor: DOMAIN_COLOR[d] || '#6b7280', stack: 'signals' })),
  };
  const options = { ...baseOptions, scales: { x: { ...baseOptions.scales.x, stacked: true }, y: { ...baseOptions.scales.y, stacked: true, beginAtZero: true } } };
  return <div className="h-52"><Bar data={chart} options={options} /></div>;
}

function CompositeAlertCard({ alert, onAck }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={clsx('border rounded p-3', alert.acknowledged ? 'border-gray-200 opacity-70' : alert.severity === 'critical' ? 'border-red bg-red-50/40' : 'border-gray-200')}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1 mb-1">
            <StatusBadge tone={SEVERITY_TONE[alert.severity] || 'neutral'}>{alert.severity}</StatusBadge>
            <span className="text-xs text-gray-500">confidence {Math.round((alert.confidence || 0) * 100)}%</span>
            {alert.domains.map((d) => <span key={d} className="text-[10px] px-1.5 py-0.5 rounded text-white" style={{ background: DOMAIN_COLOR[d] || '#6b7280' }}>{d}</span>)}
          </div>
          <div className="font-semibold text-sm">{alert.title}</div>
          <div className="text-xs text-gray-500">{alert.signals.length} signals - {when(alert.window_start)} → {when(alert.window_end)} - detected {when(alert.detected_at)}{alert.acknowledged && ` - acknowledged by ${alert.acknowledged_by}`}</div>
        </div>
        <div className="flex gap-1 shrink-0">
          <button type="button" onClick={() => setOpen(!open)} className="text-xs px-2 py-1 rounded border border-gray-300 bg-white hover:bg-gray-100">{open ? 'hide' : 'details'}</button>
          {!alert.acknowledged && <button type="button" onClick={() => onAck(alert.id)} className="text-xs px-2 py-1 rounded border border-green bg-green-50 text-green-700 hover:bg-green-100 inline-flex items-center gap-1"><CheckCircle2 size={12} aria-hidden="true" /> acknowledge</button>}
        </div>
      </div>
      {open && (
        <div className="mt-2 text-xs space-y-2">
          <p className="text-gray-700 whitespace-pre-wrap">{alert.intelligence_summary}</p>
          <div className="text-gray-500">Shared keys: {(alert.shared_keys || []).join(', ') || '-'}</div>
          <ul className="space-y-0.5">
            {alert.signals.map((s) => (
              <li key={`${s.type}-${s.id}`} className="flex flex-wrap gap-x-2">
                <span className="text-[10px] px-1 rounded text-white" style={{ background: DOMAIN_COLOR[s.domain] || '#6b7280' }}>{s.domain}</span>
                <span className="text-gray-500">{when(s.time)}</span>
                <StatusBadge tone={SEVERITY_TONE[s.severity] || 'neutral'}>{s.severity}</StatusBadge>
                <span>{s.summary}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function Fusion() {
  const [tab, setTab] = useState('alerts');
  const [hours, setHours] = useState(48);
  const [minSeverity, setMinSeverity] = useState('medium');
  const [domainFilter, setDomainFilter] = useState([]);
  const [starting, setStarting] = useState(false);

  const queueParams = useMemo(() => {
    const p = new URLSearchParams({ hours: String(hours), min_severity: minSeverity, limit: '300' });
    if (domainFilter.length) p.set('domains', domainFilter.join(','));
    return p.toString();
  }, [hours, minSeverity, domainFilter]);

  const { data: summary, refetch: refetchSummary } = useFetch(`/api/fusion/summary?hours=${hours}`, 60000);
  const { data: alerts, refetch: refetchAlerts } = useFetch(`/api/fusion/composite-alerts?hours=${Math.max(hours, 168)}&min_severity=low`, 60000);
  const { data: queue, loading: queueLoading } = useFetch(`/api/fusion/queue?${queueParams}`, 60000);
  const { data: pairs } = useFetch(`/api/fusion/correlations?hours=${hours}&limit=100`, 120000);
  const { data: timeline } = useFetch(`/api/fusion/timeline?hours=${hours}&bucket_hours=${hours > 96 ? 6 : 1}`, 120000);
  const { data: status } = useFetch('/api/fusion/status', 30000);

  const runNow = async () => {
    setStarting(true);
    try {
      await apiPost('/api/fusion/refresh', {});
      setTimeout(() => { refetchSummary(); refetchAlerts(); }, 8000);
    } catch (err) {
      alert(err.message);
    } finally {
      setStarting(false);
    }
  };
  const ack = async (id) => {
    try {
      await apiPost(`/api/fusion/composite-alerts/${id}/acknowledge`, {});
      refetchAlerts();
      refetchSummary();
    } catch (err) {
      alert(err.message);
    }
  };
  const toggleDomain = (d) => setDomainFilter((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]));
  const last = status?.last_result;

  return (
    <div>
      <PageHeader title="Intelligence Fusion" subtitle="Every bot's output in one queue, cross-domain correlations on shared vessels, listed parties, wallets, companies, facilities and countries, and composite alerts when three or more domains light up together">
        {status?.last_run && <span className="text-xs text-gray-500">Last pass {new Date(status.last_run).toLocaleTimeString()}{last ? ` - ${last.signals} signals, ${last.pairs} links, ${last.clusters} clusters` : ''}</span>}
        <button type="button" onClick={runNow} disabled={starting} className="flex items-center gap-1 px-2 py-1 rounded border border-gray-300 bg-white text-xs hover:bg-gray-100 disabled:opacity-50"><RefreshCw size={12} className={starting ? 'animate-spin' : ''} aria-hidden="true" /> Correlate now</button>
      </PageHeader>

      {summary && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 mb-4">
          <div className="card py-3"><div className="card-title">Open composite alerts</div><div className="text-xl font-semibold mt-1">{summary.open_composite_alerts}</div><div className="text-xs text-gray-500">{summary.critical_open} critical - {summary.composite_alerts} raised in {summary.hours} h - {summary.stored_alerts_total} all time</div></div>
          <div className="card py-3"><div className="card-title">Cross-domain links ({summary.hours} h)</div><div className="text-xl font-semibold mt-1">{summary.correlations}</div><div className="text-xs text-gray-500">{Object.entries(summary.correlations_by_type || {}).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, n]) => `${label(k)} ${n}`).join(' - ') || 'none yet'}</div></div>
          <div className="card py-3"><div className="card-title">Queue</div><div className="text-xl font-semibold mt-1">{queue?.total ?? '-'}</div><div className="text-xs text-gray-500">{Object.entries(queue?.by_domain || {}).map(([d, n]) => `${d} ${n}`).join(' - ') || 'no signals'}</div></div>
          <div className="card py-3"><div className="card-title">Window</div><div className="mt-1 flex flex-wrap gap-1 text-xs"><select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="border border-gray-300 rounded px-1 py-0.5 bg-white">{[6, 12, 24, 48, 72, 168].map((h) => <option key={h} value={h}>{h < 48 ? `${h} h` : `${h / 24} d`}</option>)}</select><select value={minSeverity} onChange={(e) => setMinSeverity(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white">{['low', 'medium', 'high', 'critical'].map((s) => <option key={s} value={s}>min {s}</option>)}</select></div></div>
        </div>
      )}

      <div className="card mb-4">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <div className="flex gap-1">
            {[['alerts', 'Composite alerts'], ['queue', 'Unified queue'], ['links', 'Correlations'], ['timeline', 'Timeline']].map(([key, text]) => (
              <button key={key} type="button" onClick={() => setTab(key)} className={clsx('px-2 py-0.5 rounded border', tab === key ? 'bg-steel-700 text-white border-steel-700' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-100')}>{text}</button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1 ml-auto">
            {DOMAINS.map((d) => (
              <button key={d} type="button" onClick={() => toggleDomain(d)} className={clsx('px-2 py-0.5 rounded border', domainFilter.length === 0 || domainFilter.includes(d) ? 'text-white border-transparent' : 'bg-white text-gray-400 border-gray-300')} style={domainFilter.length === 0 || domainFilter.includes(d) ? { background: DOMAIN_COLOR[d] } : undefined}>{d}</button>
            ))}
          </div>
        </div>
      </div>

      {tab === 'alerts' && (
        <div className="space-y-2">
          {alerts?.length ? alerts.filter((a) => !domainFilter.length || a.domains.some((d) => domainFilter.includes(d))).map((a) => <CompositeAlertCard key={a.id} alert={a} onAck={ack} />) : (
            <div className="card text-sm text-gray-500"><Layers size={14} className="inline mr-1" aria-hidden="true" />No composite alerts yet. They appear when signals from three or more bots (for example a sanctions match, a dark-oil indicator and a geopolitical event on the same vessel, facility or country) coincide inside the correlation window.</div>
          )}
        </div>
      )}

      {tab === 'queue' && (
        <div className="card overflow-x-auto">
          <div className="flex items-center justify-between mb-2"><span className="card-title flex items-center gap-1"><Radar size={12} aria-hidden="true" /> Unified signal queue ({queue?.total ?? 0})</span>{queueLoading && <span className="text-xs text-gray-400">loading</span>}</div>
          <table className="w-full text-xs">
            <thead className="text-left text-gray-500 border-b border-gray-200"><tr><th className="py-1 pr-2 font-medium">Severity</th><th className="py-1 pr-2 font-medium">Domain</th><th className="py-1 pr-2 font-medium">Time</th><th className="py-1 pr-2 font-medium">Signal</th><th className="py-1 pr-2 font-medium">Keys</th><th className="py-1 font-medium text-right">Links</th></tr></thead>
            <tbody>
              {(queue?.items || []).map((i) => (
                <tr key={`${i.type}-${i.id}`} className="border-b border-gray-100">
                  <td className="py-1 pr-2"><StatusBadge tone={SEVERITY_TONE[i.severity] || 'neutral'}>{i.severity}</StatusBadge></td>
                  <td className="py-1 pr-2"><span className="text-[10px] px-1.5 py-0.5 rounded text-white" style={{ background: DOMAIN_COLOR[i.domain] || '#6b7280' }}>{i.domain}</span> <span className="text-gray-500">{label(i.type)}</span></td>
                  <td className="py-1 pr-2 whitespace-nowrap text-gray-500">{when(i.time)}</td>
                  <td className="py-1 pr-2 max-w-[420px]"><a href={signalLink(i)} className="hover:underline">{i.summary}</a></td>
                  <td className="py-1 pr-2 text-gray-500 max-w-[220px] truncate">{Object.entries(i.keys || {}).map(([k, v]) => `${k}: ${v.join(', ')}`).join(' - ')}</td>
                  <td className="py-1 text-right font-mono">{i.correlations || '-'}</td>
                </tr>
              ))}
              {!queue?.items?.length && !queueLoading && <tr><td colSpan={6} className="py-2 text-gray-500">Nothing at or above this severity in the window.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'links' && (
        <div className="card">
          <div className="card-title mb-2 flex items-center gap-1"><Link2 size={12} aria-hidden="true" /> Pairwise correlations ({pairs?.length ?? 0})</div>
          {pairs?.length ? (
            <ul className="space-y-1 text-xs">
              {pairs.filter((p) => !domainFilter.length || domainFilter.some((d) => (p.correlation_type || '').includes(d))).map((p) => (
                <li key={p.id} className="border border-gray-200 rounded px-2 py-1">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{Math.round((p.confidence || 0) * 100)}%</span><span className="text-gray-500">{label(p.correlation_type)}</span><span className="text-gray-500">{p.time_delta_minutes} min apart</span><span className="text-gray-400">{(p.shared_keys || []).join(', ')}</span></div>
                  <div className="text-gray-700">{p.signal_a_summary}</div>
                  <div className="text-gray-700">↔ {p.signal_b_summary}</div>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-gray-500">No pairwise correlations recorded in the window.</p>}
        </div>
      )}

      {tab === 'timeline' && (
        <div className="card">
          <div className="card-title mb-2">Signals per {timeline?.bucket_hours || 1} h by domain</div>
          <Timeline data={timeline} />
        </div>
      )}
    </div>
  );
}
