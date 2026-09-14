export default function LoadingSpinner({ label = 'Loading' }) {
  return (
    <div className="flex items-center gap-2 text-sm text-gray-500" role="status">
      <span className="inline-block h-4 w-4 rounded-full border-2 border-gray-300 border-t-steel-600 animate-spin" />
      {label}
    </div>
  );
}
