/* =========================================================
   MONITOR — SERVICE WORKER DE RECUPERAÇÃO
   Versão: v14
   Objetivo:
   - remover caches antigos
   - não armazenar index.html
   - buscar sempre a versão atual na internet
   ========================================================= */

const CACHE_NAME = "monitor-cache-v14";

/* =========================================================
   INSTALAÇÃO
   ========================================================= */

self.addEventListener("install", event => {
  self.skipWaiting();
});

/* =========================================================
   ATIVAÇÃO
   Remove TODOS os caches antigos
   ========================================================= */

self.addEventListener("activate", event => {

  event.waitUntil(
    caches.keys()
      .then(cacheNames => {
        return Promise.all(
          cacheNames.map(cacheName => {
            return caches.delete(cacheName);
          })
        );
      })
      .then(() => self.clients.claim())
  );

});

/* =========================================================
   FETCH
   Não interfere nas requisições.
   Tudo será carregado diretamente da internet.
   ========================================================= */

self.addEventListener("fetch", event => {

  if (event.request.method !== "GET") {
    return;
  }

  event.respondWith(
    fetch(event.request)
  );

});
