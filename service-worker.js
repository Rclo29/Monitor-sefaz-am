/* =========================================================
   MONITOR — SERVICE WORKER DE RECUPERAÇÃO
   Versão: v17
   Objetivos:
   - remover caches antigos
   - não armazenar index.html
   - buscar sempre a versão atual na internet
   - ler dados.json e processos.json direto do branch main,
     sem aguardar o deploy do GitHub Pages
   - evitar preflight CORS desnecessário ao acessar o GitHub raw
   - forçar a substituição de versões antigas do app no iPhone
   ========================================================= */

const CACHE_NAME = "monitor-cache-v17";

const RAW_BASE =
  "https://raw.githubusercontent.com/Rclo29/Monitor-sefaz-am/main";

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
   DADOS DO MONITOR

   processos.json é a fonte oficial do cadastro.
   dados.json contém apenas os resultados de consulta.
   Ambos são lidos diretamente do branch main para impedir
   que um card já excluído continue aparecendo por atraso do
   GitHub Pages ou por cache antigo do Safari/PWA.
   ========================================================= */

async function fetchMonitorJson(request, fileName) {

  const rawUrl =
    `${RAW_BASE}/${fileName}?t=${Date.now()}`;

  try {

    const response = await fetch(rawUrl, {
      method: "GET",
      mode: "cors",
      cache: "no-store",
      redirect: "follow"
    });

    if (response.ok) {

      const body = await response.arrayBuffer();

      return new Response(body, {
        status: 200,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
          "Pragma": "no-cache",
          "Expires": "0"
        }
      });

    }

    console.warn(
      "Monitor: GitHub raw respondeu",
      response.status,
      fileName
    );

  } catch (error) {

    console.warn(
      "Monitor: falha ao consultar JSON no branch main",
      fileName,
      error
    );

  }

  return fetch(request, {
    cache: "no-store"
  });
}

/* =========================================================
   FETCH
   ========================================================= */

self.addEventListener("fetch", event => {

  if (event.request.method !== "GET") {
    return;
  }

  const url = new URL(event.request.url);

  if (url.origin === self.location.origin) {

    if (url.pathname.endsWith("/dados.json")) {
      event.respondWith(
        fetchMonitorJson(event.request, "dados.json")
      );
      return;
    }

    if (url.pathname.endsWith("/processos.json")) {
      event.respondWith(
        fetchMonitorJson(event.request, "processos.json")
      );
      return;
    }

  }

  event.respondWith(
    fetch(event.request, {
      cache: "no-store"
    })
  );

});
