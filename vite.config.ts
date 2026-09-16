import { sites } from '@openai/sites-vite-plugin';
import { existsSync } from 'node:fs';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), ...(existsSync('.openai/hosting.json') ? [sites()] : [])],
  server: {
    port: 3000,
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  build: { outDir: 'frontend_dist', emptyOutDir: true },
});

