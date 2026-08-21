const OWNER = "Rclo29";
const REPO = "Monitor-sefaz-am";
const BRANCH = "main";
const FILE = "processos.json";
const API = `https://api.github.com/repos/${OWNER}/${REPO}`;

function cors(origin = "*") {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
}
function json(data, status = 200, origin = "*") {
  return new Response(JSON.stringify(data, null, 2), { status, headers: { ...cors(origin), "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
}
function gh(token) {
  return { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "monitor-sefaz-am", "Content-Type": "application/json" };
}
function normalizarNumero(v) { return String(v || "").trim().replace(/\s+/g, ""); }
function validarSefaz(numero) { return /^\d{2}\.\d{2}\.\d{6}\.\d{6}\/\d{4}-\d{2}$/.test(numero); }
function decode64(v) { const bin = atob(String(v || "").replace(/\n/g, "")); return new TextDecoder().decode(Uint8Array.from(bin, c => c.charCodeAt(0))); }
function encode64(v) { const bytes = new TextEncoder().encode(v); let bin = ""; for (let i = 0; i < bytes.length; i += 8192) bin += String.fromCharCode(...bytes.subarray(i, i + 8192)); return btoa(bin); }

async function lerProcessos(token) {
  const r = await fetch(`${API}/contents/${FILE}?ref=${encodeURIComponent(BRANCH)}`, { headers: gh(token) });
  if (!r.ok) throw new Error(`GitHub HTTP ${r.status}: ${await r.text()}`);
  const f = await r.json();
  const d = JSON.parse(decode64(f.content));
  const processos = Array.isArray(d.processos) ? d.processos.map(item => typeof item === "string" ? { numero: normalizarNumero(item), origem: "sefaz" } : { numero: normalizarNumero(item?.numero), origem: "sefaz" }).filter(item => item.numero && validarSefaz(item.numero)) : [];
  return { sha: f.sha, processos };
}
async function gravarProcessos(token, processos, sha, message) {
  const conteudo = JSON.stringify({ processos }, null, 2) + "\n";
  const r = await fetch(`${API}/contents/${FILE}`, { method: "PUT", headers: gh(token), body: JSON.stringify({ message, content: encode64(conteudo), sha, branch: BRANCH }) });
  if (!r.ok) throw new Error(`GitHub HTTP ${r.status}: ${await r.text()}`);
  return r.json();
}
async function dispararWorkflow(token) {
  const r = await fetch(`${API}/actions/workflows/monitor.yml/dispatches`, { method: "POST", headers: gh(token), body: JSON.stringify({ ref: BRANCH }) });
  return { ok: r.status === 204, statusGitHub: r.status, detalhe: r.status === 204 ? "" : await r.text() };
}
async function adicionar(token, numero) {
  const atual = await lerProcessos(token);
  if (atual.processos.some(p => p.numero === numero)) return { ok: false, erro: "Este processo já está cadastrado." };
  const processos = [...atual.processos, { numero, origem: "sefaz" }];
  await gravarProcessos(token, processos, atual.sha, `Adiciona processo ${numero}`);
  const workflow = await dispararWorkflow(token);
  return { ok: true, mensagem: "Processo SEFAZ adicionado.", numero, total: processos.length, consultaIniciada: workflow.ok };
}
async function excluir(token, numero) {
  const atual = await lerProcessos(token);
  if (!atual.processos.some(p => p.numero === numero)) return { ok: false, erro: "Processo não encontrado." };
  const processos = atual.processos.filter(p => p.numero !== numero);
  await gravarProcessos(token, processos, atual.sha, `Remove processo ${numero}`);
  const workflow = await dispararWorkflow(token);
  return { ok: true, mensagem: "Processo removido.", numero, total: processos.length, consultaIniciada: workflow.ok };
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "*";
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(origin) });
    if (request.method !== "POST") return json({ ok: false, erro: "Método não permitido." }, 405, origin);
    let body; try { body = await request.json(); } catch { return json({ ok: false, erro: "Corpo JSON inválido." }, 400, origin); }
    if (!env.GITHUB_TOKEN) return json({ ok: false, erro: "GITHUB_TOKEN não configurado no Worker." }, 500, origin);
    const acao = String(body?.acao || "").trim().toLowerCase();
    const numero = normalizarNumero(body?.numero);
    try {
      if (acao === "atualizar") {
        const r = await dispararWorkflow(env.GITHUB_TOKEN);
        return json(r.ok ? { ok: true, mensagem: "Atualização iniciada." } : { ok: false, erro: "GitHub recusou a atualização.", ...r }, r.ok ? 200 : 500, origin);
      }
      if (acao === "adicionar") {
        if (!validarSefaz(numero)) return json({ ok: false, erro: "Formato SEFAZ inválido. Exemplo: 01.01.028101.030037/2026-43" }, 400, origin);
        const r = await adicionar(env.GITHUB_TOKEN, numero); return json(r, r.ok ? 200 : 400, origin);
      }
      if (acao === "excluir") {
        if (!numero) return json({ ok: false, erro: "Número do processo não informado." }, 400, origin);
        const r = await excluir(env.GITHUB_TOKEN, numero); return json(r, r.ok ? 200 : 400, origin);
      }
      return json({ ok: false, erro: "Ação desconhecida." }, 400, origin);
    } catch (e) {
      console.error("Erro no Worker:", e);
      return json({ ok: false, erro: "Erro interno do Worker.", detalhe: String(e?.message || e) }, 500, origin);
    }
  },
};
