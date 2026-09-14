import { useMemo, useState } from 'react';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { ArrowUpDown } from 'lucide-react';
import { apiPatch } from '../../services/api';

const STATUSES = ['flagged', 'investigating', 'cleared', 'escalated'];
const helper = createColumnHelper();

/** Sortable / filterable table of cross-exchange coordination events with inline status updates. */
export default function CoordinationBoard({ events, onChange }) {
  const [sorting, setSorting] = useState([{ id: 'detected_at', desc: true }]);
  const [filter, setFilter] = useState('');

  const columns = useMemo(() => {
    const updateStatus = async (id, status) => {
      await apiPatch(`/api/market/coordination/${id}`, { investigation_status: status, updated_by: 'analyst' });
      onChange?.();
    };
    return [
      helper.accessor('asset', { header: 'Asset' }),
      helper.accessor((row) => row.exchanges.join(', '), { id: 'exchanges', header: 'Exchanges' }),
      helper.accessor('detected_at', { header: 'Time', cell: (info) => new Date(info.getValue()).toLocaleString() }),
      helper.accessor('time_delta_seconds', { header: 'Delta (s)' }),
      helper.accessor('correlated_price_move', { header: 'Move %', cell: (info) => info.getValue()?.toFixed(2) }),
      helper.accessor('volume_coordination', { header: 'Vol x', cell: (info) => info.getValue()?.toFixed(1) ?? '-' }),
      helper.accessor('confidence_score', {
        header: 'Confidence',
        cell: (info) => (
          <span className={info.getValue() >= 0.8 ? 'text-red-700 font-semibold' : ''}>{(info.getValue() * 100).toFixed(0)}%</span>
        ),
      }),
      helper.accessor('investigation_status', {
        header: 'Status',
        cell: (info) => (
          <select
            className="border border-gray-300 rounded px-1 py-0.5 text-xs bg-white"
            value={info.getValue() || 'flagged'}
            onChange={(e) => updateStatus(info.row.original.id, e.target.value)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        ),
      }),
    ];
  }, [onChange]);

  const table = useReactTable({
    data: events || [],
    columns,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter (asset, exchange, status)"
          className="border border-gray-300 rounded px-2 py-1 text-xs w-64"
        />
        <span className="text-xs text-gray-500">{table.getRowModel().rows.length} event(s)</span>
      </div>
      {events?.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-gray-500 border-b border-gray-200">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h) => (
                    <th key={h.id} className="py-2 pr-3 font-medium cursor-pointer select-none" onClick={h.column.getToggleSortingHandler()}>
                      <span className="inline-flex items-center gap-1">
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        <ArrowUpDown size={10} className="text-gray-400" aria-hidden="true" />
                      </span>
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="border-b border-gray-100 hover:bg-gray-50" title={row.original.analyst_assessment || ''}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="py-1.5 pr-3">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-gray-500">
          No coordination events detected. Thresholds: {'>'}2% synchronised move with return correlation {'>'}0.85.
        </p>
      )}
    </div>
  );
}
