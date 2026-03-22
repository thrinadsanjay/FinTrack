self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", () => {
  // Passive for now.
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (_err) {
    payload = {};
  }

  const title = String(payload.title || "FinTracker");
  const body = String(payload.body || "You have a new alert.");
  const tag = String(payload.tag || "ft-alert");
  const data = payload.data || { url: "/" };

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      tag,
      renotify: true,
      badge: "/static/icons/favicon-32x32.png",
      icon: "/static/icons/android-chrome-192x192.png",
      data,
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = String((event.notification.data || {}).url || "/");

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientsArr) => {
      for (const client of clientsArr) {
        if (client.url.includes(self.location.origin)) {
          client.focus();
          client.postMessage({ type: "ft-open-url", url: targetUrl });
          return;
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
