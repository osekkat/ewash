/* ewash PWA service worker
 * Strategy: network-first. Serve fresh from network when online; fall back
 * to cache only if the network fails (e.g. offline). The cache is kept
 * warm in the background so the PWA still works fully offline.
 *
 * Tradeoff: every request pays a network round-trip when online.
 * Win: no version-bump dance — code edits show up on the next reload.
 */
const CACHE = 'ewash';
const ASSETS = [
  './',
  './index.html',
  './styles.css',
  './i18n.js',
  './icons.jsx',
  './tweaks-panel.jsx',
  './components.jsx',
  './auth.jsx',
  './screens.jsx',
  './booking.jsx',
  './app.jsx',
  './manifest.webmanifest',
  './assets/ewash-logo.png',
  './assets/icon-192.png',
  './assets/icon-512.png',
  './assets/icon-maskable-512.png',
  './assets/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(
        ASSETS.map((url) => new Request(url, { cache: 'reload' }))
      ))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // CRITICAL: never let the SW touch /api/* requests. The PWA's bookings list,
  // catalog, and auth state must reflect server state on every read — caching
  // any of them produces stale-data bugs (latest booking missing, admin price
  // edits invisible, revoked token returning a cached 200). Applies to every
  // method: GETs to avoid stale reads, POSTs so the cross-origin booking
  // submission isn't accidentally cached, OPTIONS so preflight responses
  // pull live CORS headers when ALLOWED_ORIGINS rotates.
  let url;
  try {
    url = new URL(req.url);
  } catch (err) {
    url = null;
  }
  if (url && url.pathname.startsWith('/api/')) {
    return;
  }

  if (req.method !== 'GET') return;

  event.respondWith(
    fetch(req).then((response) => {
      if (response && response.status === 200 &&
          (response.type === 'basic' || response.type === 'cors')) {
        const clone = response.clone();
        caches.open(CACHE).then((c) => c.put(req, clone));
      }
      return response;
    }).catch(() => caches.match(req))
  );
});
