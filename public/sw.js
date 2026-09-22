// Cache-first store for the heavy, build-addressed files (models carry ?v=<build id>, draco is immutable).
const NAME = 'enoden-walk-assets-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin || !/^\/(models|draco)\//.test(url.pathname)) return;
  e.respondWith(
    caches.open(NAME).then(async (cache) => {
      const hit = await cache.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok && res.status === 200) {
        cache.put(req, res.clone());
        // drop entries of older builds for the same file
        for (const k of await cache.keys()) {
          const u = new URL(k.url);
          if (u.pathname === url.pathname && u.search !== url.search) cache.delete(k);
        }
      }
      return res;
    }),
  );
});
