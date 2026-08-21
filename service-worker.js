/* =========================================================
   MONITOR — SERVICE WORKER
   Versão: v18
   - sem cache persistente
   - dados.json/processos.json lidos diretamente pelo Worker
   - evita espera de publicação do GitHub Pages
   - aplica divisórias visuais no Quadro geral
   ========================================================= */

const CACHE_NAME = "monitor-cache-v18";
const WORKER_BASE = "https://monitor-sefaz-am.8dryc8ph6w.workers.dev";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(names => Promise.all(names.map(name => caches.delete(name))))
      .then(() => self.clients.claim())
  );
});

async function fetchJsonDireto(request, endpoint) {
  try {
    const response = await fetch(`${WORKER_BASE}/${endpoint}?t=${Date.now()}`, {
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
  } catch (error) {
    console.warn("Monitor: falha ao buscar JSON direto pelo Worker", endpoint, error);
  }

  return fetch(request, { cache: "no-store" });
}

async function fetchPaginaComAjuste(request) {
  const response = await fetch(request, { cache: "no-store" });
  if (!response.ok) return response;

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("text/html")) return response;

  let html = await response.text();
  const extraCss = `
<style id="quadro-geral-divisorias-v18">
.summary-head,.summary-line{grid-template-columns:185px 76px 1fr!important;column-gap:0!important}
.summary-head>div,.summary-line>div{min-width:0}
.summary-sector,.summary-head>div:nth-child(2){border-left:1px solid #d8dee6;padding-left:9px;padding-right:7px}
.summary-move,.summary-head>div:nth-child(3){border-left:1px solid #d8dee6;padding-left:9px}
@media(max-width:390px){.summary-head,.summary-line{grid-template-columns:178px 72px 1fr!important}}
</style>`;

  html = html.replace("</head>", `${extraCss}</head>`);

  return new Response(html, {
    status: response.status,
    statusText: response.statusText,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"
    }
  });
}

self.addEventListener("fetch", event => {
  if (event.request.method !== "GET") return;

  const url = new URL(event.request.url);

  if (url.origin === self.location.origin) {
    if (url.pathname.endsWith("/dados.json")) {
      event.respondWith(fetchJsonDireto(event.request, "dados-atualizados"));
      return;
    }

    if (url.pathname.endsWith("/processos.json")) {
      event.respondWith(fetchJsonDireto(event.request, "processos-atualizados"));
      return;
    }

    if (event.request.mode === "navigate" || url.pathname.endsWith("/index.html") || url.pathname.endsWith("/Monitor-sefaz-am/")) {
      event.respondWith(fetchPaginaComAjuste(event.request));
      return;
    }
  }

  event.respondWith(fetch(event.request, { cache: "no-store" }));
});
