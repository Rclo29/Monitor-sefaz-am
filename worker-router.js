import workerEntry from "./worker-entry.js";

const VERSION = "router-sefaz-only-v2-status";
const GITHUB_API = "https://api.github.com/repos/Rclo29/Monitor-sefaz-am";
const WORKFLOW = "monitor.yml";
const BRANCH = "main";

function json(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}

function gh(token) {
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "monitor-sefaz-am",
    "Content-Type": "application/json",
  };
}

async function disparar(token) {
  if (!token) return { ok: false, erro: "GITHUB_TOKEN não configurado." };
  const dispatchedAt = new Date().toISOString();
  const r = await fetch(`${GITHUB_API}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: gh(token),
    body: JSON.stringify({ ref: BRANCH }),
  });
  const detalhe = r.status === 204 ? "" : await r.text();
  console.log("[monitor-sefaz] workflow_dispatch", { status: r.status, ok: r.status === 204, detalhe });
  return r.status === 204
    ? { ok: true, mensagem: "Atualização SEFAZ iniciada.", metodo: "workflow_dispatch", dispatched_at: dispatchedAt, version: VERSION }
    : { ok: false, erro: "GitHub recusou o disparo do monitor.", statusGitHub: r.status, detalhe, version: VERSION };
}

async function statusAtualizacao(token, since) {
  if (!token) return { ok: false, erro: "GITHUB_TOKEN não configurado." };
  const r = await fetch(`${GITHUB_API}/actions/workflows/${WORKFLOW}/runs?branch=${encodeURIComponent(BRANCH)}&per_page=10`, {
    headers: gh(token),
  });
  if (!r.ok) {
    return { ok: false, erro: "Não foi possível consultar o status do GitHub Actions.", statusGitHub: r.status, detalhe: await r.text() };
  }
  const dados = await r.json();
  const limite = since ? Date.parse(since) - 5000 : 0;
  const run = (dados.workflow_runs || []).find(item =>
    item.event === "workflow_dispatch" && (!limite || Date.parse(item.created_at) >= limite)
  );
  if (!run) return { ok: true, encontrado: false, version: VERSION };
  return {
    ok: true,
    encontrado: true,
    run_id: run.id,
    status: run.status,
    conclusion: run.conclusion,
    created_at: run.created_at,
    updated_at: run.updated_at,
    html_url: run.html_url,
    version: VERSION,
  };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400" } });
    }
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "monitor-sefaz-am", mode: "sefaz-only", version: VERSION, github_token_configurado: Boolean(env.GITHUB_TOKEN), timestamp: new Date().toISOString() });
    }
    if (request.method === "GET" && url.pathname === "/status-atualizacao") {
      const r = await statusAtualizacao(env.GITHUB_TOKEN, url.searchParams.get("since") || "");
      return json(r, r.ok ? 200 : 500);
    }
    if (request.method === "POST") {
      try {
        const body = await request.clone().json();
        if (String(body?.acao || "").trim().toLowerCase() === "atualizar") {
          const r = await disparar(env.GITHUB_TOKEN);
          return json(r, r.ok ? 200 : 500);
        }
      } catch (e) {
        console.error("[monitor-sefaz] POST inválido", String(e?.message || e));
      }
    }
    return workerEntry.fetch(request, env, ctx);
  },
};
