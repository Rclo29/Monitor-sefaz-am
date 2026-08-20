const CACHE_NAME = "monitor-cache-v13";

/* ============================================================
   INSTALAÇÃO
   ============================================================ */

self.addEventListener("install", event => {
  self.skipWaiting();
});


/* ============================================================
   ATIVAÇÃO
   ============================================================ */

self.addEventListener("activate", event => {

  event.waitUntil(
    caches.keys().then(cacheNames => {

      return Promise.all(
        cacheNames.map(cacheName => {

          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }

          return Promise.resolve();

        })
      );

    }).then(() => self.clients.claim())
  );

});


/* ============================================================
   FUNÇÕES AUXILIARES
   ============================================================ */

function isHtmlRequest(request, url) {

  return (
    request.mode === "navigate"
    ||
    url.pathname.endsWith("/")
    ||
    url.pathname.endsWith("/index.html")
  );

}


function isDynamicFile(url) {

  return (
    url.pathname.endsWith("/dados.json")
    ||
    url.pathname.endsWith("/processos.json")
  );

}


/* ============================================================
   NETWORK FIRST
   ============================================================ */

async function networkFirst(request) {

  const cache = await caches.open(CACHE_NAME);

  try {

    const response = await fetch(
      new Request(
        request,
        {
          cache: "no-store"
        }
      )
    );

    if (
      response
      &&
      response.ok
    ) {

      try {
        await cache.put(
          request,
          response.clone()
        );
      } catch {}

    }

    return response;

  } catch (error) {

    const cached = await cache.match(request);

    if (cached) {
      return cached;
    }

    throw error;

  }

}


/* ============================================================
   FETCH
   ============================================================ */

self.addEventListener("fetch", event => {

  const request = event.request;

  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  /*
    Não interfere em domínios externos,
    Worker, SEFAZ ou SEMEF.
  */
  if (url.origin !== self.location.origin) {
    return;
  }

  /*
    index.html / navegação:
    sempre tenta a rede primeiro.
  */
  if (isHtmlRequest(request, url)) {

    event.respondWith(
      networkFirst(request)
    );

    return;
  }

  /*
    dados.json e processos.json:
    sempre tenta buscar a versão mais recente.
  */
  if (isDynamicFile(url)) {

    event.respondWith(
      networkFirst(request)
    );

    return;
  }

  /*
    Outros arquivos:
    rede primeiro, cache como fallback.
  */
  event.respondWith(
    fetch(request)
      .then(async response => {

        if (
          response
          &&
          response.ok
        ) {

          try {

            const cache =
              await caches.open(CACHE_NAME);

            await cache.put(
              request,
              response.clone()
            );

          } catch {}

        }

        return response;

      })
      .catch(async () => {

        const cached =
          await caches.match(request);

        if (cached) {
          return cached;
        }

        return new Response(
          "",
          {
            status: 504,
            statusText: "Offline"
          }
        );

      })
  );

});


/* ============================================================
   LIMPEZA MANUAL DE CACHE
   ============================================================ */

self.addEventListener("message", event => {

  if (
    event.data
    &&
    event.data.type === "CLEAR_CACHE"
  ) {

    event.waitUntil(
      caches.keys().then(cacheNames => {

        return Promise.all(
          cacheNames.map(
            cacheName =>
              caches.delete(cacheName)
          )
        );

      })
    );

  }

});
