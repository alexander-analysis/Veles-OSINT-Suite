import { Link } from 'react-router-dom';
import { TrendingUp, Ship, Activity, Database, Clock } from 'lucide-react';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useFetch } from '../hooks/useFetch';

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

function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString() : 'no data yet';
}

function StatCard({ icon: Icon, title, value, detail, tone }) {
  const label = tone === 'ok' ? 'healthy' : tone === 'warn' ? 'attention' : 'down';
  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <span className="card-title">{title}</span>
        <Icon size={16} className="text-gray-400" aria-hidden="true" />
      </div>
      <div className="mt-2 flex items-center gap-2">
        <span className="text-xl font-semibold">{value}</span>
        {tone && <StatusBadge tone={tone}>{label}</StatusBadge>}
      </div>
      {detail && <div className="mt-1 text-xs text-gray-500">{detail}</div>}
    </div>
  );
}

function ModuleCard({ icon: Icon, title, phase, to, lastUpdate, description }) {
  return (
    <div className="card flex flex-col">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 font-medium">
          <Icon size={18} className="text-steel-600" aria-hidden="true" />
          {title}
        </span>
        <StatusBadge tone={lastUpdate ? 'ok' : 'neutral'}>{lastUpdate ? 'live' : phase}</StatusBadge>
      </div>
      <p className="mt-2 text-sm text-gray-600 flex-1">{description}</p>
      <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <Clock size={12} aria-hidden="true" /> Last data: {formatTime(lastUpdate)}
        </span>
        <Link to={to} className="text-steel-600 hover:underline">
          Open &rarr;
        </Link>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { data: health, error, loading, updatedAt } = useFetch('/api/health', 15000);
  const backendTone = error ? 'error' : health?.status === 'ok' ? 'ok' : 'warn';

  return (
    <div>
      <PageHeader title="Intelligence Dashboard" subtitle="System status and module summary">
        {updatedAt && <span className="text-xs text-gray-500">Refreshed {updatedAt.toLocaleTimeString()}</span>}
      </PageHeader>

      {loading && <LoadingSpinner label="Contacting backend" />}
      {error && (
        <div className="card border-red mb-6">
          <div className="card-title text-red-700">Backend unreachable</div>
          <div className="mt-1 text-sm text-red-700">{error.message}</div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 mb-6">
        <StatCard
          icon={Activity}
          title="Backend"
          value={health ? `v${health.version}` : '-'}
          detail={health ? `${health.environment} - up ${formatUptime(health.uptime_seconds)}` : undefined}
          tone={health ? backendTone : undefined}
        />
        <StatCard
          icon={Database}
          title="Database"
          value={health ? health.database.dialect : '-'}
          detail={health ? formatBytes(health.database.size_bytes) : undefined}
          tone={health ? (health.database.ok ? 'ok' : 'error') : undefined}
        />
        <StatCard
          icon={Clock}
          title="Scheduler"
          value={health ? `${health.scheduler.jobs.length} jobs` : '-'}
          detail={health ? (health.scheduler.running ? 'running' : 'stopped') : undefined}
          tone={health ? (health.scheduler.running ? 'ok' : 'warn') : undefined}
        />
        <StatCard
          icon={Activity}
          title="Server time"
          value={health ? new Date(health.timestamp).toLocaleTimeString() : '-'}
          detail="UTC timestamps on all data"
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <ModuleCard
          icon={TrendingUp}
          title="Market Intelligence"
          phase="Phase 2"
          to="/market"
          lastUpdate={health?.last_market_update}
          description="Multi-exchange price monitoring, 3-sigma anomaly detection, volume spikes and cross-exchange coordination patterns."
        />
        <ModuleCard
          icon={Ship}
          title="Maritime Intelligence"
          phase="Phase 3"
          to="/maritime"
          lastUpdate={health?.last_ais_update}
          description="AIS vessel tracking, OFAC / EU / UN sanctions cross-referencing, evasion and transshipment detection with an immutable audit trail."
        />
      </div>
    </div>
  );
}
