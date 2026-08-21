import workerOriginal from "./worker.js";

const SEMEF_HOME_URL = "https://sigedweb.manaus.am.gov.br/protonweb/";
const SEMEF_DETALHE_URL = "https://sigedweb.manaus.am.gov.br/protonweb/detalhe.aspx";
const SEMEF_TIMEOUT_MS = 12000;
const VERSION = "semef-proxy-v2-fast-fail";

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

  const sinaisDetalhe = [
    sinais.situacao,
    sinais.interessado,
    sinais.assunto,
    sinais.localizacao,
    sinais.historico,
    sinais.despacho,
  ].filter(Boolean).length;

  const valida =
    html.length > 5000 &&
    sinais.semef &&
    sinais.processo &&
    (numeroEncontrado || sinaisDetalhe >= 3);

  return {
    valida,
    sinais,
    preview: visivel.slice(0, 700),
  };
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
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (erro) {
    if (controller.signal.aborted) {
      const e = new Error(`Timeout após ${timeoutMs} ms`);
      e.name = "TimeoutError";
      throw e;
    }
    throw erro;
  } finally {
    clearTimeout(timer);
  }
}

function extrairCookie(headers) {
  try {
    if (typeof headers.getSetCookie === "function") {
      const cookies = headers.getSetCookie();
      if (Array.isArray(cookies)) {
        return cookies
          .map(v => String(v).split(";")[0])
          .filter(Boolean)
          .join("; ");
      }
    }
  } catch {}

  const valor = headers.get("set-cookie");
  if (!valor) return "";

  return valor
    .split(",")
    .map(v => v.trim().split(";")[0])
    .filter(Boolean)
    .join("; ");
}

function headersBase() {
  return {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": SEMEF_HOME_URL,
  };
}

async function tentarDetalhe(url, numero, headers, etapa, diagnostico) {
  const inicio = Date.now();

  try {
    const resposta = await fetchComTimeout(
      url,
      {
        method: "GET",
        headers,
        redirect: "follow",
      },
      SEMEF_TIMEOUT_MS
    );

    const html = await resposta.text();
    const avaliacao = avaliarPagina(html, numero);

    diagnostico.push({
      etapa,
      status: resposta.status,
      sucesso_http: resposta.ok,
      tamanho_resposta: html.length,
      duracao_ms: Date.now() - inicio,
      pagina_semef_valida: avaliacao.valida,
      sinais: avaliacao.sinais,
      preview: avaliacao.preview,
    });

    if (resposta.ok && avaliacao.valida) {
      return {
        ok: true,
        html,
        status: resposta.status,
      };
    }

    return {
      ok: false,
      timeout: false,
    };
  } catch (erro) {
    const timeout = erro?.name === "TimeoutError";

    diagnostico.push({
      etapa,
      timeout,
      erro: String(erro?.message || erro),
      duracao_ms: Date.now() - inicio,
    });

    return {
      ok: false,
      timeout,
    };
  }
}

async function consultarSemef(numero, protocolo) {
  const url = `${SEMEF_DETALHE_URL}?origem=1&cod_protocolo=${encodeURIComponent(protocolo)}`;
  const inicioTotal = Date.now();
  const diagnostico = [];
  const base = headersBase();

  // 1) Acesso direto. Quando o próprio host não responde, encerramos rápido.
  const direto = await tentarDetalhe(
    url,
    numero,
    base,
    "detalhe_direto",
    diagnostico
  );

  if (direto.ok) {
    return {
      ok: true,
      via: "cloudflare-direto",
      version: VERSION,
      numero,
      cod_protocolo: protocolo,
      status: direto.status,
      duracao_total_ms: Date.now() - inicioTotal,
      diagnostico,
      html: direto.html,
    };
  }

  // Se nem a conexão direta foi estabelecida, abrir home/sessão só triplica o tempo
  // e não melhora a disponibilidade. Retornamos imediatamente para o monitor usar
  // os últimos dados válidos sem atrasar toda a atualização.
  if (direto.timeout) {
    return {
      ok: false,
      indisponivel: true,
      erro: "Servidor da SEMEF não respondeu dentro do tempo limite.",
      version: VERSION,
      numero,
      cod_protocolo: protocolo,
      duracao_total_ms: Date.now() - inicioTotal,
      diagnostico,
    };
  }

  // 2) O host respondeu, porém a página direta não foi validada. Nesse caso vale
  // tentar estabelecer sessão/cookie e repetir o detalhe.
  let cookie = "";
  let referer = SEMEF_HOME_URL;

  try {
    const inicio = Date.now();
    const home = await fetchComTimeout(
      SEMEF_HOME_URL,
      {
        method: "GET",
        headers: base,
        redirect: "follow",
      },
      SEMEF_TIMEOUT_MS
    );

    await home.text();
    cookie = extrairCookie(home.headers);
    referer = home.url || SEMEF_HOME_URL;

    diagnostico.push({
      etapa: "pagina_inicial",
      status: home.status,
      sucesso_http: home.ok,
      cookie_recebido: Boolean(cookie),
      duracao_ms: Date.now() - inicio,
    });
  } catch (erro) {
    diagnostico.push({
      etapa: "pagina_inicial",
      timeout: erro?.name === "TimeoutError",
      erro: String(erro?.message || erro),
    });
  }

  const headersSessao = {
    ...base,
    Referer: referer,
  };

  if (cookie) {
    headersSessao.Cookie = cookie;
  }

  const sessao = await tentarDetalhe(
    url,
    numero,
    headersSessao,
    "detalhe_com_sessao",
    diagnostico
  );

  if (sessao.ok) {
    return {
      ok: true,
      via: cookie ? "cloudflare-sessao" : "cloudflare-segunda-tentativa",
      version: VERSION,
      numero,
      cod_protocolo: protocolo,
      status: sessao.status,
      duracao_total_ms: Date.now() - inicioTotal,
      diagnostico,
      html: sessao.html,
    };
  }

  return {
    ok: false,
    indisponivel: Boolean(sessao.timeout),
    erro: sessao.timeout
      ? "Servidor da SEMEF não respondeu dentro do tempo limite."
      : "A SEMEF respondeu, mas a página do processo não pôde ser validada.",
    version: VERSION,
    numero,
    cod_protocolo: protocolo,
    duracao_total_ms: Date.now() - inicioTotal,
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
          const protocolo = normalizarProtocolo(
            body.cod_protocolo || body.codProtocolo || ""
          );

          if (!/^\d{4}\.\d{5}\.\d{5}\.\d\.\d{6}$/.test(numero)) {
            return jsonResponse(
              {
                ok: false,
                erro: "Número de processo SEMEF inválido.",
                version: VERSION,
              },
              400,
              origin
            );
          }

          if (!protocolo) {
            return jsonResponse(
              {
                ok: false,
                erro: "Código interno do protocolo SEMEF não informado.",
                version: VERSION,
              },
              400,
              origin
            );
          }

          const resultado = await consultarSemef(numero, protocolo);

          return jsonResponse(
            resultado,
            resultado.ok ? 200 : (resultado.indisponivel ? 503 : 502),
            origin
          );
        }
      } catch {
        // Qualquer outra ação continua usando exatamente a lógica existente.
      }
    }

    return workerOriginal.fetch(request, env, ctx);
  },
};
