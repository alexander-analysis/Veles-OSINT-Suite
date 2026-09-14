import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the API is proxied to the FastAPI server so the app can use
// relative /api URLs; in production Nginx does the same job.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true, // WebSocket stream (Phase 3)
      },
    },
  },
  build: {
    sourcemap: false,
  },
});
