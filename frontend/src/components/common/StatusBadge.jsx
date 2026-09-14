import clsx from 'clsx';

const TONES = {
  ok: 'bg-green-50 text-green-700 border-green',
  warn: 'bg-yellow-50 text-yellow-700 border-yellow',
  error: 'bg-red-50 text-red-700 border-red',
  neutral: 'bg-gray-100 text-gray-700 border-gray-300',
};

export default function StatusBadge({ tone = 'neutral', children }) {
  return (
    <span className={clsx('inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium', TONES[tone])}>
      {children}
    </span>
  );
}
