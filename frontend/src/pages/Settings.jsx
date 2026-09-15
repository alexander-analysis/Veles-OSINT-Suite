import { useEffect, useState } from 'react';
import { Save, KeyRound } from 'lucide-react';
import PageHeader from '../components/common/PageHeader';
import LoadingSpinner from '../components/common/LoadingSpinner';
import StatusBadge from '../components/common/StatusBadge';
import { useFetch } from '../hooks/useFetch';
import { apiPost, getApiToken, setApiToken } from '../services/api';

const SECTION_HELP = {
  market: 'Assets, exchanges and detection thresholds for the market bot. Applied on the next run.',
  maritime: 'AIS polling, screening cadence, confidence floors, transshipment and gap thresholds. Source toggles need a restart.',
  sanctions: 'List refresh cadence and screening similarity floor.',
  geopolitical: 'GDELT event filter (mentions floor, watchlist), DOC topic pacing, official / state-media feeds, correlation window.',
  blockchain: 'Wallet polling batches, Ethereum block sampling, Bitcoin mempool stream and whale thresholds.',
  corporate: 'GLEIF enrichment batch size, re-check cadence and the name similarity needed to attach an LEI.',
  energy: 'Facility visit speed floor, shipment / dark-oil cadences, STS loitering threshold.',
  correlation: 'Fusion engine window, minimum pair score and how many domains make a composite alert.',
  aviation: 'ADS-B sweep batch and cadence, OpenSky daily budget.',
  leaks: 'Breach feeds, minimum relevance score to store and watch keywords.',
  narratives: 'State-media clustering window and minimum items per narrative.',
  infra: 'Domain footprinting batch and re-check cadence.',
  legal: 'Enforcement / DOJ polling and CourtListener docket search batch.',
  psc: 'Port state control sources (Paris MoU THETIS, Tokyo MoU APCIS) and cadence.',
  watchlist: 'Watchlist check cadence and whether hits fire instant alerts.',
  notifications: 'Instant alerts and the daily digest (channels need NOTIFY_WEBHOOK_URL / SMTP_* in .env).',
  retention: 'How long raw data is kept before purge/thinning (audit log is never purged).',
  classification: 'Marking shown on every page and on generated reports.',
};

function parseValue(original, raw) {
  if (typeof original === 'boolean') return raw === true || raw === 'true';
  if (typeof original === 'number') {
    const n = Number(raw);
    return Number.isFinite(n) ? n : original;
  }
  if (Array.isArray(original)) {
    if (original.length && typeof original[0] === 'object') {
      try {
        return JSON.parse(raw);
      } catch {
        return original;
      }
    }
    return String(raw).split(',').map((s) => s.trim()).filter(Boolean);
  }
  if (original && typeof original === 'object') {
    try {
      return JSON.parse(raw);
    } catch {
      return original;
    }
  }
  return raw;
}

function displayValue(value) {
  if (Array.isArray(value)) return value.length && typeof value[0] === 'object' ? JSON.stringify(value) : value.join(', ');
  if (value && typeof value === 'object') return JSON.stringify(value);
  return value ?? '';
}

function SectionForm({ name, values, onSaved }) {
  const [draft, setDraft] = useState({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => setDraft({}), [values]);

  const save = async () => {
    if (!Object.keys(draft).length) return;
    setSaving(true);
    setMessage(null);
    try {
      const patch = Object.fromEntries(Object.entries(draft).map(([k, raw]) => [k, parseValue(values[k], raw)]));
      await apiPost('/api/admin/config', { [name]: patch });
      setMessage('saved');
      onSaved?.();
    } catch (err) {
      setMessage(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-1">
        <span className="card-title">{name}</span>
        <button type="button" onClick={save} disabled={saving || !Object.keys(draft).length} className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100 disabled:opacity-40">
          <Save size={12} aria-hidden="true" /> {saving ? 'Saving' : 'Save'}
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-2">{SECTION_HELP[name]}</p>
      <table className="kv-table w-full">
        <tbody>
          {Object.entries(values || {}).map(([key, value]) => (
            <tr key={key}>
              <td className="w-56">{key}</td>
              <td>
                {typeof value === 'boolean' ? (
                  <input type="checkbox" checked={key in draft ? draft[key] === true || draft[key] === 'true' : value} onChange={(e) => setDraft({ ...draft, [key]: e.target.checked })} />
                ) : (
                  <input
                    className="w-full border border-gray-300 rounded px-2 py-0.5 text-xs font-mono"
                    value={key in draft ? draft[key] : displayValue(value)}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {message && <div className={`mt-2 text-xs ${message === 'saved' ? 'text-green-700' : 'text-red-700'}`}>{message}</div>}
    </div>
  );
}

export default function Settings() {
  const { data: config, error, loading, refetch } = useFetch('/api/admin/config', 0);
  const { data: health } = useFetch('/api/health', 0);
  const [token, setToken] = useState(getApiToken());
  const tokenRequired = health?.bots?.auth?.token_required;

  return (
    <div>
      <PageHeader title="Settings" subtitle="Thresholds, cadences, notifications and access">
        {health && <StatusBadge tone={tokenRequired ? 'warn' : 'neutral'}>{tokenRequired ? 'API token required' : 'API open (no token configured)'}</StatusBadge>}
      </PageHeader>

      <div className="card mb-4">
        <div className="card-title mb-1 flex items-center gap-1"><KeyRound size={12} aria-hidden="true" /> API access token</div>
        <p className="text-xs text-gray-500 mb-2">
          When the backend has <code>VELES_API_TOKEN</code> set, every request needs it. The token is kept in this browser only.
        </p>
        <div className="flex gap-2">
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="token" className="border border-gray-300 rounded px-2 py-1 text-sm w-80" />
          <button type="button" onClick={() => { setApiToken(token); refetch(); }} className="px-3 py-1 text-sm rounded bg-steel-600 text-white hover:bg-steel-700">Use token</button>
          <button type="button" onClick={() => { setToken(''); setApiToken(''); }} className="px-3 py-1 text-sm rounded border border-gray-300 bg-white hover:bg-gray-100">Clear</button>
        </div>
      </div>

      {loading && <LoadingSpinner />}
      {error && <div className="card border-red text-red-700 text-sm">{error.message}</div>}
      {config && (
        <div className="grid gap-4 xl:grid-cols-2">
          {Object.entries(config).map(([section, values]) => (
            <SectionForm key={section} name={section} values={values} onSaved={refetch} />
          ))}
        </div>
      )}
      <p className="mt-4 text-xs text-gray-500">
        Changes are written to <code>backend/settings.local.yaml</code> and recorded in the audit log. Lists are comma-separated; structured values (AIS sources) are JSON.
      </p>
    </div>
  );
}
