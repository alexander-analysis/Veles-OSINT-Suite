import PageHeader from '../components/common/PageHeader';
import AuditLog from '../components/intelligence/AuditLog';

export default function AuditLogPage() {
  return (
    <div>
      <PageHeader title="Audit & Compliance Log" subtitle="Immutable record of every detection, screening, review and export" />
      <div className="card">
        <AuditLog />
      </div>
    </div>
  );
}
