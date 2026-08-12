import react from '@vitejs/plugin-react';
// vitest/config, not vite: only its defineConfig accepts the `test` block.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The backend owns every number the UI renders; nothing is computed here.
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
});
