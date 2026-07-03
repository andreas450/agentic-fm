import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';
import { apiMiddleware } from './server/api';

export default defineConfig({
  plugins: [
    preact(),
    tailwindcss(),
    apiMiddleware(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 8090,
    strictPort: true,
  },
  build: {
    target: 'es2022',
  },
});
