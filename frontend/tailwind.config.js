/** @type {import('tailwindcss').Config} */
// Light, agency-grade palette: white/cream surfaces, steel-blue accent,
// semantic colours for severity.  The palette is a full override (not
// `extend`) so components cannot drift outside it.
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      inherit: 'inherit',
      white: '#ffffff',
      black: '#000000',
      cream: '#f9f7f4',
      gray: {
        50: '#f9fafb',
        100: '#f3f4f6',
        200: '#e5e7eb',
        300: '#d1d5db',
        400: '#9ca3af',
        500: '#6b7280',
        600: '#4b5563',
        700: '#374151',
        800: '#1f2937',
        900: '#111827',
      },
      steel: {
        50: '#f0f4f8',
        100: '#d9e2ec',
        200: '#bcccdc',
        500: '#4a6fa5',
        600: '#3d5a80',
        700: '#2f4a6b',
        800: '#243b55',
      },
      blue: {
        600: '#2563eb',
        700: '#1d4ed8',
      },
      red: { DEFAULT: '#ef4444', 50: '#fef2f2', 700: '#b91c1c', 900: '#8b0000' },
      orange: { DEFAULT: '#f39c12', 50: '#fff7ed', 700: '#c2410c' },
      green: { DEFAULT: '#22c55e', 50: '#f0fdf4', 700: '#15803d' },
      yellow: { DEFAULT: '#eab308', 50: '#fefce8', 700: '#a16207' },
    },
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
};
