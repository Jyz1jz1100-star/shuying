import { sites } from '@openai/sites-vite-plugin';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), sites()],
  server: {
    port: 3000,
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  build: { outDir: 'frontend_dist', emptyOutDir: true },
});
