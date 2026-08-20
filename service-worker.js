const CACHE_VERSION =
  "monitor-sefaz-am-v12";

const STATIC_CACHE =
  `${CACHE_VERSION}-static`;

const DATA_CACHE =
  `${CACHE_VERSION}-data`;

const APP_SHELL = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png"
];


/* ============================================================
   INSTALAÇÃO
   ============================================================ */

self.addEventListener(
  "install",
  event => {

    self.skipWaiting();

    event.waitUntil(
      caches
        .open(
          STATIC_CACHE
        )
        .then(
          cache =>
            cache.addAll(
              APP_SHELL
            )
        )
        .catch(
          error => {

            console.error(
              "Erro ao criar cache inicial:",
              error
            );

          }
        )
    );

  }
);


/* ============================================================
   ATIVAÇÃO
   ============================================================ */

self.addEventListener(
  "activate",
  event => {

    event.waitUntil(

      Promise.all([

        /*
          Remove qualquer cache antigo do Monitor.
        */

        caches
          .keys()
          .then(
            cacheNames =>
              Promise.all(
                cacheNames.map(
                  cacheName => {

                    if (
                      cacheName !== STATIC_CACHE
                      &&
                      cacheName !== DATA_CACHE
                    ) {

                      return caches.delete(
                        cacheName
                      );

                    }

                    return Promise.resolve();

                  }
                )
              )
          ),

        /*
          Faz o novo Service Worker assumir
          as páginas abertas imediatamente.
        */

        self.clients.claim()

      ])

    );

  }
);


/* ============================================================
   UTILIDADES
   ============================================================ */

function isHtmlRequest(
  request,
  url
) {

  if (
    request.mode === "navigate"
  ) {

    return true;

  }

  if (
    url.pathname.endsWith(
      "/index.html"
    )
  ) {

    return true;

  }

  if (
    url.pathname.endsWith(
      "/"
    )
  ) {

    return true;

  }

  return false;

}


function isDynamicJson(
  url
) {

  return (
    url.pathname.endsWith(
      "/dados.json"
    )
    ||
    url.pathname.endsWith(
      "/processos.json"
    )
  );

}


function isStaticAsset(
  url
) {

  return (
    url.pathname.endsWith(
      "/manifest.json"
    )
    ||
    url.pathname.endsWith(
      "/icon-192.png"
    )
    ||
    url.pathname.endsWith(
      "/icon-512.png"
    )
  );

}


/* ============================================================
   NETWORK FIRST
   index.html
   dados.json
   processos.json
   ============================================================ */

async function networkFirst(
  request,
  cacheName
) {

  const cache =
    await caches.open(
      cacheName
    );

  try {

    /*
      Cria uma nova requisição com cache desabilitado
      para evitar que Safari/GitHub Pages entregue
      uma cópia antiga.
    */

    const freshRequest =
      new Request(
        request,
        {
          cache:
            "no-store"
        }
      );

    const response =
      await fetch(
        freshRequest
      );

    if (
      response
      &&
      response.ok
    ) {

      await cache.put(
        request,
        response.clone()
      );

    }

    return response;

  } catch(error) {

    const cached =
      await cache.match(
        request
      );

    if (cached) {

      return cached;

    }

    throw error;

  }

}


/* ============================================================
   CACHE FIRST
   somente arquivos estáticos
   ============================================================ */

async function cacheFirst(
  request
) {

  const cache =
    await caches.open(
      STATIC_CACHE
    );

  const cached =
    await cache.match(
      request
    );

  if (cached) {

    return cached;

  }

  const response =
    await fetch(
      request
    );

  if (
    response
    &&
    response.ok
  ) {

    await cache.put(
      request,
      response.clone()
    );

  }

  return response;

}


/* ============================================================
   FETCH
   ============================================================ */

self.addEventListener(
  "fetch",
  event => {

    const request =
      event.request;

    /*
      Só trabalhamos com GET.
    */

    if (
      request.method !== "GET"
    ) {

      return;

    }

    const url =
      new URL(
        request.url
      );

    /*
      Não interfere em sites externos,
      Worker, SEFAZ ou SEMEF.
    */

    if (
      url.origin !==
      self.location.origin
    ) {

      return;

    }


    /* ======================================================
       INDEX / NAVEGAÇÃO
       Sempre tenta a versão nova primeiro.
       ====================================================== */

    if (
      isHtmlRequest(
        request,
        url
      )
    ) {

      event.respondWith(
        networkFirst(
          request,
          STATIC_CACHE
        )
      );

      return;

    }


    /* ======================================================
       DADOS.JSON / PROCESSOS.JSON
       Nunca devem ficar presos em cache antigo.
       ====================================================== */

    if (
      isDynamicJson(
        url
      )
    ) {

      event.respondWith(
        networkFirst(
          request,
          DATA_CACHE
        )
      );

      return;

    }


    /* ======================================================
       ÍCONES / MANIFEST
       Podem usar cache normalmente.
       ====================================================== */

    if (
      isStaticAsset(
        url
      )
    ) {

      event.respondWith(
        cacheFirst(
          request
        )
      );

      return;

    }


    /* ======================================================
       DEMAIS ARQUIVOS
       Rede primeiro, sem bloquear atualização.
       ====================================================== */

    event.respondWith(
      fetch(
        request
      )
      .catch(
        () =>
          caches.match(
            request
          )
      )
    );

  }
);


/* ============================================================
   MENSAGEM PARA LIMPAR CACHE MANUALMENTE
   ============================================================ */

self.addEventListener(
  "message",
  event => {

    if (
      event.data
      &&
      event.data.type ===
      "CLEAR_MONITOR_CACHE"
    ) {

      event.waitUntil(

        caches
          .keys()
          .then(
            cacheNames =>
              Promise.all(
                cacheNames.map(
                  cacheName =>
                    caches.delete(
                      cacheName
                    )
                )
              )
          )

      );

    }

  }
);
