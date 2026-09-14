import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import { useFetch } from '../hooks/useFetch';

export default function Maritime() {
  const { data } = useFetch('/api/maritime/vessels', 30000);

  return (
    <div>
      <PageHeader title="Maritime Intelligence" subtitle="Vessel tracking and sanctions monitoring">
        <StatusBadge tone={data?.vessel_count ? 'ok' : 'neutral'}>
          {data ? `${data.vessel_count} vessels / ${data.breach_count} breaches` : 'awaiting Phase 3'}
        </StatusBadge>
      </PageHeader>
      <div className="card">
        <div className="card-title">Status</div>
        <p className="mt-2 text-sm text-gray-600">
          The maritime bot (Phase 3) will populate this page with an interactive vessel map, sanctions breach board,
          evasion patterns, transshipment alerts and the compliance audit log.
        </p>
      </div>
    </div>
  );
}
