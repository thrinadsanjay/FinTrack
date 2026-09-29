/* FinTracker service worker.
 *
 * Finance-safe caching:
 *  - Pages (navigations) and all API/data requests are NEVER cached. They always go
 *    to the network; only when the network fails is a static offline page shown.
 *  - Only public static assets (CSS, JS, icons, fonts) are cached, stale-while-revalidate.
 *  - /static/uploads/ (user files) is never cached.
 *  - Logout (or a "clear" message) wipes every cache.
 */
const VERSION = "ft-v1";
const STATIC_CACHE = `${VERSION}-static`;
const OFFLINE_URL = "/static/offline.html";
const PRECACHE = [OFFLINE_URL, "/static/icons/FinTracker_exact.svg", "/static/icons/android-chrome-192x192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "clear") {
    event.waitUntil(caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k)))));
  }
});

function isCacheableAsset(url) {
  if (url.origin === self.location.origin) {
    return url.pathname.startsWith("/static/") && !url.pathname.startsWith("/static/uploads/");
  }
  // Public CDNs used for fonts/icons.
  return ["fonts.googleapis.com", "fonts.gstatic.com", "cdnjs.cloudflare.com"].includes(url.hostname);
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return; // writes always hit the server directly

  const url = new URL(req.url);

  if (req.mode === "navigate") {
    // Network only; offline fallback page if unreachable. Never serve stale financial pages.
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  if (!isCacheableAsset(url)) return; // APIs, data, uploads: straight to the network

  event.respondWith(
    caches.open(STATIC_CACHE).then(async (cache) => {
      const cached = await cache.match(req);
      const network = fetch(req)
        .then((res) => {
          if (res && (res.ok || res.type === "opaque")) cache.put(req, res.clone());
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
