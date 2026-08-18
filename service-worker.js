const CACHE_NAME = "monitor-sefaz-am-v1";

const APP_SHELL = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png",
  "./icon-512-maskable.png"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(APP_SHELL);
    })
  );

  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      );
    })
  );

  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const request = event.request;

  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  /*
    dados.json e processos.json devem sempre tentar
    buscar a versão mais recente na internet.
  */
  if (
    url.pathname.endsWith("/dados.json") ||
    url.pathname.endsWith("/processos.json")
  ) {
    event.respondWith(
      fetch(request, {
        cache: "no-store"
      }).catch(() => caches.match(request))
    );

    return;
  }

  /*
    Demais arquivos do aplicativo:
    tenta cache primeiro e atualiza pela internet.
  */
  event.respondWith(
    caches.match(request).then(cached => {
      const networkFetch = fetch(request)
        .then(response => {
          if (
            response &&
            response.status === 200 &&
            response.type === "basic"
          ) {
            const copy = response.clone();

            caches.open(CACHE_NAME).then(cache => {
              cache.put(request, copy);
            });
          }

          return response;
        });

      return cached || networkFetch;
    })
  );
});
