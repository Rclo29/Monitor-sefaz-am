import workerEntry from "./worker-entry.js";

const ROUTER_VERSION = "router-v1";

function json(dados, status = 200) {
  return new Response(JSON.stringify(dados, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/health") {
      return json({
        ok: true,
        service: "monitor-sefaz-am",
        router_version: ROUTER_VERSION,
        timestamp: new Date().toISOString(),
      });
    }

    if (request.method === "GET" && url.pathname === "/semef-test") {
      const numero = url.searchParams.get("numero") || "";
      const protocolo = url.searchParams.get("cod_protocolo") || "";

      if (!numero || !protocolo) {
        return json({
          ok: false,
          erro: "Informe numero e cod_protocolo.",
          router_version: ROUTER_VERSION,
        }, 400);
      }

      const interno = new Request(request.url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Origin": "https://diagnostico.local",
        },
        body: JSON.stringify({
          acao: "consultar_semef",
          numero,
          cod_protocolo: protocolo,
        }),
      });

      return workerEntry.fetch(interno, env, ctx);
    }

    return workerEntry.fetch(request, env, ctx);
  },
};
