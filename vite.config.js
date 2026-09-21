import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    chunkSizeWarningLimit: 1500,
    target: 'es2020',
    rollupOptions: {
      // three.js in its own long-lived chunk: an app-only redeploy does not invalidate it in the browser cache
      output: { manualChunks: (id) => (id.includes('node_modules/three') ? 'three' : undefined) },
    },
  },
  server: { host: true },
  test: { include: ['tests/**/*.test.js'] },
});
