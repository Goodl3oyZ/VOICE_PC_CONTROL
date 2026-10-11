// Voice PC Remote — PWA Service Worker
// Strictly caches the application shell only.
// API calls, WebSocket streams, tokens, and remote execution data are NEVER cached (§6).

const CACHE_NAME = "voicepc-shell-v3"; // bump: purges anything cached by older versions
const SHELL_ASSETS = ["/", "/index.html", "/manifest.webmanifest", "/icon.svg"];
const NETWORK_ONLY_PREFIXES = [
  "/command", "/jobs", "/confirm", "/stop", "/status", "/events", "/health",
  "/auth", "/audit", "/capabilities", "/agent",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Strictly skip non-GET requests, third-party requests, and all PC1 API endpoints
  if (
    event.request.method !== "GET" ||
    url.origin !== location.origin ||
    NETWORK_ONLY_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))
  ) {
    return; // Pass straight to network
  }

  // Stale-while-revalidate / Network-fallback for App Shell static assets
  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200 && networkResponse.type === "basic") {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(async () => {
        const cached = await caches.match(event.request);
        if (cached) return cached;
        if (event.request.mode === "navigate") {
          return caches.match("/index.html");
        }
        return new Response("Offline", { status: 503, statusText: "Offline" });
      })
  );
});
