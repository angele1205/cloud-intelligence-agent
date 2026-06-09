import { defineConfig } from 'vite';

export default defineConfig({
  build: { outDir: 'dist' },
  define: { global: 'globalThis' }
});
