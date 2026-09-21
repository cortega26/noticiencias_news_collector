/* No-op service worker: no offline/PWA behavior. Exists only so stray /service-worker.js requests (stale registrations) resolve 200 instead of 404 noise. Nothing registers this file. */
self.addEventListener("fetch", () => {});
