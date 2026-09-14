// Standard marking colours: UNCLASSIFIED green, CONFIDENTIAL blue, SECRET red.
const STYLES = {
  UNCLASSIFIED: 'bg-green-700 text-white',
  CONFIDENTIAL: 'bg-blue-700 text-white',
  SECRET: 'bg-red-700 text-white',
};

export default function ClassificationBanner({ level }) {
  const marking = (level || import.meta.env.VITE_CLASSIFICATION || 'UNCLASSIFIED').toUpperCase();
  return (
    <div
      role="note"
      aria-label={`Classification: ${marking}`}
      className={`${STYLES[marking] || STYLES.UNCLASSIFIED} text-center text-xs font-semibold tracking-[0.3em] py-0.5 select-none`}
    >
      {marking}
    </div>
  );
}
