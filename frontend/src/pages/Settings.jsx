import PageHeader from '../components/common/PageHeader';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useFetch } from '../hooks/useFetch';

function renderValue(value) {
  if (Array.isArray(value) || (value && typeof value === 'object')) {
    return <code className="text-xs">{JSON.stringify(value)}</code>;
  }
  return String(value);
}

export default function Settings() {
  const { data: config, error, loading } = useFetch('/api/admin/config', 0);

  return (
    <div>
      <PageHeader title="Settings" subtitle="Effective configuration (defaults merged with operator overrides)" />
      {loading && <LoadingSpinner />}
      {error && <div className="card border-red text-red-700 text-sm">{error.message}</div>}
      {config && (
        <div className="grid gap-4 md:grid-cols-2">
          {Object.entries(config).map(([section, values]) => (
            <div key={section} className="card">
              <div className="card-title">{section}</div>
              <table className="kv-table mt-2">
                <tbody>
                  {Object.entries(values || {}).map(([key, value]) => (
                    <tr key={key}>
                      <td>{key}</td>
                      <td>{renderValue(value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
      <p className="mt-4 text-xs text-gray-500">
        Values are read from <code>backend/settings.yaml</code>; editing from this page arrives in Phase 4. Until
        then use <code>POST /api/admin/config</code>.
      </p>
    </div>
  );
}
