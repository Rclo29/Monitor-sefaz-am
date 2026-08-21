import workerOriginal from "./worker.js";

const SEMEF_HOME_URL = "https://sigedweb.manaus.am.gov.br/protonweb/";
const SEMEF_DETALHE_URL = "https://sigedweb.manaus.am.gov.br/protonweb/detalhe.aspx";
const SEMEF_TIMEOUT_MS = 10000;
const VERSION = "semef-proxy-v1";

function normalizarNumero(valor) {
  return String(valor || "").trim().replace(/\s+/g, "");
}

function normalizarProtocolo(valor) {
  return String(valor || "").replace(/\D/g, "");
}

function textoVisivel(html) {
  return String(html || "")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function semAcentos(valor) {
  return String(valor || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function avaliarPagina(html, numero) {
  const visivel = textoVisivel(html);
  const texto = semAcentos(visivel);
  const numeroNormalizado = normalizarNumero(numero);
  const numeroCompacto = numeroNormalizado.replace(/\D/g, "");
  const textoCompacto = texto.replace(/\D/g, "");

  const numeroEncontrado = Boolean(numeroNormalizado) && (
    texto.includes(numeroNormalizado.toLowerCase()) ||
    (numeroCompacto.length >= 10 && textoCompacto.includes(numeroCompacto))
  );

  const sinais = {
    numero_processo: numeroEncontrado,
    semef: texto.includes("semef"),
    processo: texto.includes("processo"),
    situacao: texto.includes("situacao"),
    interessado: texto.includes("interessado"),
    assunto: texto.includes("assunto"),
    localizacao: texto.includes("localizacao"),
    historico: texto.includes("historico"),
    despacho: texto.includes("despacho"),
    tramitando: texto.includes("tramitando"),
    consulta_documentos: texto.includes("consulta de documentos"),
  };

  let pontos = 0;
  for (const [chave, valor] of Object.entries(sinais)) {
    if (chave !== "numero_processo" && valor) pontos += 1;
  }

  const valida =
    html.length > 5000 &&
    sinais.semef &&
    sinais.processo &&
    (numeroEncontrado || pontos >= 4);

  return { valida, sinais, preview: visivel.slice(0, 700) };
}

function jsonResponse(dados, status, origin) {
  return new Response(JSON.stringify(dados, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": origin || "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
    },
  });
}

async function fetchComTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function extrairCookie(headers) {
  try {
    if (typeof headers.getSetCookie === "function") {
      const cookies = headers.getSetCookie();
      if (Array.isArray(cookies)) {
        return cookies.map(v => String(v).split(";")[0]).filter(Boolean).join("; ");
      }
    }
  } catch {}

  const valor = headers.get("set-cookie");
  if (!valor) return "";
  return valor.split(",").map(v => v.trim().split(";")[0]).filter(Boolean).join("; ");
}

async function consultarSemef(numero, protocolo) {
  const url = `${SEMEF_DETALHE_URL}?origem=1&cod_protocolo=${encodeURIComponent(protocolo)}`;
  const inicio = Date.now();
  const diagnostico = [];

  const headersBase = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": SEMEF_HOME_URL,
  };

  async function tentar(etapa, headers) {
    const ini = Date.now();
    const resposta = await fetchComTimeout(url, {
      method: "GET",
      headers,
      redirect: "follow",
    }, SEMEF_TIMEOUT_MS);

    const html = await resposta.text();
    const avaliacao = avaliarPagina(html, numero);
    diagnostico.push({
      etapa,
      status: resposta.status,
      sucesso_http: resposta.ok,
      tamanho_resposta: html.length,
      duracao_ms: Date.now() - ini,
      pagina_semef_valida: avaliacao.valida,
      sinais: avaliacao.sinais,
      preview: avaliacao.preview,
    });

    if (resposta.ok && avaliacao.valida) {
      return { html, resposta };
    }
    return null;
  }

  try {
    const direto = await tentar("detalhe_direto", headersBase);
    if (direto) {
      return {
        ok: true,
        via: "cloudflare-direto",
        version: VERSION,
        numero,
        cod_protocolo: protocolo,
        status: direto.resposta.status,
        duracao_total_ms: Date.now() - inicio,
        diagnostico,
        html: direto.html,
      };
    }
  } catch (erro) {
    diagnostico.push({ etapa: "detalhe_direto", erro: String(erro?.message || erro) });
  }

  let cookie = "";
  try {
    const ini = Date.now();
    const home = await fetchComTimeout(SEMEF_HOME_URL, {
      method: "GET",
      headers: headersBase,
      redirect: "follow",
    }, SEMEF_TIMEOUT_MS);
    await home.text();
    cookie = extrairCookie(home.headers);
    diagnostico.push({
      etapa: "pagina_inicial",
      status: home.status,
      sucesso_http: home.ok,
      cookie_recebido: Boolean(cookie),
      duracao_ms: Date.now() - ini,
    });
  } catch (erro) {
    diagnostico.push({ etapa: "pagina_inicial", erro: String(erro?.message || erro) });
  }

  try {
    const headers = { ...headersBase };
    if (cookie) headers.Cookie = cookie;
    const sessao = await tentar("detalhe_com_sessao", headers);
    if (sessao) {
      return {
        ok: true,
        via: cookie ? "cloudflare-sessao" : "cloudflare-segunda-tentativa",
        version: VERSION,
        numero,
        cod_protocolo: protocolo,
        status: sessao.resposta.status,
        duracao_total_ms: Date.now() - inicio,
        diagnostico,
        html: sessao.html,
      };
    }
  } catch (erro) {
    diagnostico.push({ etapa: "detalhe_com_sessao", erro: String(erro?.message || erro) });
  }

  return {
    ok: false,
    erro: "A SEMEF respondeu, mas a página do processo não pôde ser validada.",
    version: VERSION,
    numero,
    cod_protocolo: protocolo,
    duracao_total_ms: Date.now() - inicio,
    diagnostico,
  };
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return workerOriginal.fetch(request, env, ctx);
    }

    if (request.method === "POST") {
      try {
        const body = await request.clone().json();
        const acao = String(body?.acao || "").trim().toLowerCase();

        if (acao === "consultar_semef") {
          const origin = request.headers.get("Origin") || "*";
          const numero = normalizarNumero(body.numero || "");
          const protocolo = normalizarProtocolo(body.cod_protocolo || body.codProtocolo || "");

          if (!/^\d{4}\.\d{5}\.\d{5}\.\d\.\d{6}$/.test(numero)) {
            return jsonResponse({ ok: false, erro: "Número de processo SEMEF inválido.", version: VERSION }, 400, origin);
          }
          if (!protocolo) {
            return jsonResponse({ ok: false, erro: "Código interno do protocolo SEMEF não informado.", version: VERSION }, 400, origin);
          }

          const resultado = await consultarSemef(numero, protocolo);
          return jsonResponse(resultado, resultado.ok ? 200 : 502, origin);
        }
      } catch {
        // Para qualquer outra ação, mantém exatamente a lógica existente.
      }
    }

    return workerOriginal.fetch(request, env, ctx);
  },
};
