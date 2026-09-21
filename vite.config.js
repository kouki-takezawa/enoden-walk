import { defineConfig } from 'vite';

// model files keep their names, so the requests carry a build id: a redeploy can never be paired with stale cached data
const BUILD = (process.env.VERCEL_GIT_COMMIT_SHA || Date.now().toString(36)).slice(0, 10);

export default defineConfig({
  define: { __BUILD__: JSON.stringify(BUILD) },
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
