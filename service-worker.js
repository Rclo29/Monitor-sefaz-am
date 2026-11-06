/* Monitor SEFAZ-AM: rede sempre atualizada, sem injeção de scripts. */
const CACHE_NAME = "monitor-clean-v25";
self.addEventListener("install", event => { self.skipWaiting(); });
self.addEventListener("activate", event => { event.waitUntil((async () => { const keys = await caches.keys(); await Promise.all(keys.map(k => caches.delete(k))); await self.clients.claim(); })()); });
self.addEventListener("fetch", event => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  event.respondWith(fetch(event.request, {cache:"no-store"}));
});
