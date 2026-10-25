import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/telemetry': 'http://127.0.0.1:8000',
      '/faults': 'http://127.0.0.1:8000',
      '/alerts': 'http://127.0.0.1:8000',
      '/consent': 'http://127.0.0.1:8000',
      '/stations': 'http://127.0.0.1:8000',
      '/me': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
});
