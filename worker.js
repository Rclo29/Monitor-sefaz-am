// ============================================================
// MONITOR SEFAZ-AM + SEMEF
// Cloudflare Worker
// ============================================================

export default {
  async fetch(request, env) {

    const origin = request.headers.get("Origin") || "*";

    const corsHeaders = {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
    };

    const jsonHeaders = {
      ...corsHeaders,
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    };

    // --------------------------------------------------------
    // CORS
    // --------------------------------------------------------

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders,
      });
    }

    // --------------------------------------------------------
    // SOMENTE POST
    // --------------------------------------------------------

    if (request.method !== "POST") {
      return respostaJSON(
        {
          ok: false,
          erro: "Método não permitido.",
        },
        405,
        jsonHeaders
      );
    }

    // --------------------------------------------------------
    // JSON
    // --------------------------------------------------------

    let body = {};

    try {
      body = await request.json();
    } catch {
      return respostaJSON(
        {
          ok: false,
          erro: "Corpo JSON inválido.",
        },
        400,
        jsonHeaders
      );
    }

    const acao = String(body.acao || "")
      .trim()
      .toLowerCase();

    try {

      // ======================================================
      // CONSULTAR SEMEF
      // ======================================================

      if (acao === "consultar_semef") {

        const numero = normalizarNumero(
          body.numero || ""
        );

        let codProtocolo = normalizarProtocolo(
          body.cod_protocolo ||
          body.codProtocolo ||
          ""
        );

        if (!codProtocolo && numero) {
          codProtocolo =
            protocoloSemefConhecido(numero);
        }

        if (
          numero &&
          !validarNumero(numero, "semef")
        ) {
          return respostaJSON(
            {
              ok: false,
              erro:
                "Número de processo SEMEF inválido.",
            },
            400,
            jsonHeaders
          );
        }

        if (!codProtocolo) {
          return respostaJSON(
            {
              ok: false,
              erro:
                "Código interno do protocolo SEMEF não informado.",
            },
            400,
            jsonHeaders
          );
        }

        const resultado =
          await consultarSemefPorWorker(
            codProtocolo
          );

        return respostaJSON(
          {
            ...resultado,
            numero,
            cod_protocolo: codProtocolo,
          },
          resultado.ok ? 200 : 502,
          jsonHeaders
        );
      }

      // ======================================================
      // DAQUI PARA BAIXO PRECISA DO GITHUB_TOKEN
      // ======================================================

      if (!env.GITHUB_TOKEN) {
        return respostaJSON(
          {
            ok: false,
            erro:
              "GITHUB_TOKEN não configurado no Worker.",
          },
          500,
          jsonHeaders
        );
      }

      // ======================================================
      // ATUALIZAR
      // ======================================================

      if (acao === "atualizar") {

        const resultado =
          await dispararWorkflow(
            env.GITHUB_TOKEN
          );

        return respostaJSON(
          resultado,
          resultado.ok ? 200 : 500,
          jsonHeaders
        );
      }

      // ======================================================
      // ADICIONAR
      // ======================================================

      if (acao === "adicionar") {

        const numero =
          normalizarNumero(body.numero);

        if (!numero) {
          return respostaJSON(
            {
              ok: false,
              erro:
                "Número do processo não informado.",
            },
            400,
            jsonHeaders
          );
        }

        const origem =
          normalizarOrigem(
            body.origem ||
            detectarOrigem(numero)
          );

        if (
          !validarNumero(
            numero,
            origem
          )
        ) {
          return respostaJSON(
            {
              ok: false,

              erro:
                origem === "semef"
                  ? "Formato SEMEF inválido. Exemplo: 2026.18000.19951.0.024703"
                  : "Formato SEFAZ inválido. Exemplo: 01.01.028101.030037/2026-43",
            },
            400,
            jsonHeaders
          );
        }

        let codProtocolo =
          normalizarProtocolo(
            body.cod_protocolo ||
            body.codProtocolo ||
            ""
          );

        if (
          origem === "semef" &&
          !codProtocolo
        ) {
          codProtocolo =
            protocoloSemefConhecido(
              numero
            );
        }

        if (
          origem === "semef" &&
          !codProtocolo
        ) {
          return respostaJSON(
            {
              ok: false,
              erro:
                "Ainda não conhecemos o código interno deste processo SEMEF.",
            },
            400,
            jsonHeaders
          );
        }

        const resultado =
          await adicionarProcesso(
            env.GITHUB_TOKEN,
            numero,
            origem,
            codProtocolo
          );

        return respostaJSON(
          resultado,
          resultado.ok ? 200 : 400,
          jsonHeaders
        );
      }

      // ======================================================
      // EXCLUIR
      // ======================================================

      if (acao === "excluir") {

        const numero =
          normalizarNumero(body.numero);

        if (!numero) {
          return respostaJSON(
            {
              ok: false,
              erro:
                "Número do processo não informado.",
            },
            400,
            jsonHeaders
          );
        }

        const resultado =
          await excluirProcesso(
            env.GITHUB_TOKEN,
            numero
          );

        return respostaJSON(
          resultado,
          resultado.ok ? 200 : 400,
          jsonHeaders
        );
      }

      // ======================================================
      // AÇÃO DESCONHECIDA
      // ======================================================

      return respostaJSON(
        {
          ok: false,
          erro: "Ação desconhecida.",
          acao_recebida: acao,
        },
        400,
        jsonHeaders
      );

    } catch (erro) {

      console.error(
        "Erro no Worker:",
        erro
      );

      return respostaJSON(
        {
          ok: false,
          erro:
            "Erro interno do Worker.",

          detalhe:
            formatarErro(erro),
        },
        500,
        jsonHeaders
      );
    }
  },
};


// ============================================================
// GITHUB
// ============================================================

const OWNER = "Rclo29";
const REPO = "Monitor-sefaz-am";
const BRANCH = "main";

const WORKFLOW =
  "monitor.yml";

const ARQUIVO_PROCESSOS =
  "processos.json";

const API_BASE =
  `https://api.github.com/repos/${OWNER}/${REPO}`;


// ============================================================
// SEMEF
// ============================================================

const SEMEF_HOST =
  "sigedweb.manaus.am.gov.br";

const SEMEF_HOME_URL =
  `https://${SEMEF_HOST}/protonweb/`;

const SEMEF_DETALHE_URL =
  `https://${SEMEF_HOST}/protonweb/detalhe.aspx`;


// Timeout curto proposital.
// Se a SEMEF não responder, não queremos travar
// o Worker por muito tempo.
const SEMEF_TIMEOUT_MS = 8000;


// ============================================================
// PROTOCOLOS SEMEF
// ============================================================

const SEMEF_PROTOCOLS = {

  "2024.18000.19012.0.008302":
    "7954846",

  "2026.18000.19951.0.024703":
    "11442112",

  "2026.18000.19951.0.014382":
    "11037580",

};


// ============================================================
// JSON
// ============================================================

function respostaJSON(
  dados,
  status,
  headers
) {

  return new Response(
    JSON.stringify(
      dados,
      null,
      2
    ),
    {
      status,
      headers,
    }
  );
}


// ============================================================
// NORMALIZAÇÃO
// ============================================================

function normalizarNumero(valor) {

  return String(valor || "")
    .trim()
    .replace(/\s+/g, "");
}


function normalizarOrigem(valor) {

  const origem =
    String(valor || "")
      .trim()
      .toLowerCase();

  if (
    origem === "semef" ||
    origem === "siged"
  ) {
    return "semef";
  }

  return "sefaz";
}


function normalizarProtocolo(valor) {

  return String(valor || "")
    .replace(/\D/g, "");
}


// ============================================================
// DETECTAR ORIGEM
// ============================================================

function detectarOrigem(numero) {

  const semefRegex =
    /^\d{4}\.\d{5}\.\d{5}\.\d\.\d{6}$/;

  return semefRegex.test(numero)
    ? "semef"
    : "sefaz";
}


// ============================================================
// VALIDAR
// ============================================================

function validarNumero(
  numero,
  origem
) {

  if (origem === "semef") {

    return (
      /^\d{4}\.\d{5}\.\d{5}\.\d\.\d{6}$/
        .test(numero)
    );
  }

  return (
    /^\d{2}\.\d{2}\.\d{6}\.\d{6}\/\d{4}-\d{2}$/
      .test(numero)
  );
}


// ============================================================
// PROTOCOLO SEMEF
// ============================================================

function protocoloSemefConhecido(
  numero
) {

  return (
    SEMEF_PROTOCOLS[numero]
    ||
    ""
  );
}


// ============================================================
// ERRO
// ============================================================

function formatarErro(erro) {

  if (!erro) {
    return "Erro desconhecido";
  }

  return {
    nome:
      String(
        erro.name || ""
      ),

    mensagem:
      String(
        erro.message ||
        erro
      ),

    causa:
      erro.cause
        ? String(
            erro.cause.message ||
            erro.cause
          )
        : "",
  };
}


// ============================================================
// DIAGNÓSTICO HTTP
// ============================================================

function diagnosticoResposta(
  etapa,
  resposta,
  duracaoMs
) {

  return {
    etapa,

    sucesso_http:
      resposta.ok,

    status:
      resposta.status,

    status_text:
      resposta.statusText || "",

    url_final:
      resposta.url || "",

    redirected:
      resposta.redirected,

    tipo:
      resposta.type || "",

    content_type:
      resposta.headers.get(
        "content-type"
      ) || "",

    server:
      resposta.headers.get(
        "server"
      ) || "",

    cf_ray:
      resposta.headers.get(
        "cf-ray"
      ) || "",

    duracao_ms:
      duracaoMs,
  };
}


// ============================================================
// PRÉVIA SEGURA DO HTML
// ============================================================

function resumirHTML(html) {

  if (!html) {
    return "";
  }

  const texto =
    String(html)
      .replace(
        /<script[\s\S]*?<\/script>/gi,
        " "
      )
      .replace(
        /<style[\s\S]*?<\/style>/gi,
        " "
      )
      .replace(
        /<[^>]+>/g,
        " "
      )
      .replace(
        /&nbsp;/gi,
        " "
      )
      .replace(
        /\s+/g,
        " "
      )
      .trim();

  return texto.slice(
    0,
    500
  );
}


// ============================================================
// CONSULTA SEMEF
// ============================================================

async function consultarSemefPorWorker(
  codProtocolo
) {

  const inicioTotal =
    Date.now();

  const diagnostico = [];

  const url =
    SEMEF_DETALHE_URL
    +
    "?origem=1&cod_protocolo="
    +
    encodeURIComponent(
      codProtocolo
    );


  const headersBase = {

    "User-Agent":
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",

    "Accept":
      "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",

    "Accept-Language":
      "pt-BR,pt;q=0.9,en;q=0.8",

    "Cache-Control":
      "no-cache",

    "Pragma":
      "no-cache",

    "Referer":
      SEMEF_HOME_URL,
  };


  // =========================================================
  // TESTE 1
  // Página de detalhe diretamente
  // =========================================================

  try {

    const inicio =
      Date.now();

    const resposta =
      await fetchComTimeout(
        url,
        {
          method: "GET",
          headers: headersBase,
          redirect: "follow",
        },
        SEMEF_TIMEOUT_MS
      );

    const duracao =
      Date.now() - inicio;

    const diag =
      diagnosticoResposta(
        "detalhe_direto",
        resposta,
        duracao
      );

    const html =
      await resposta.text();

    diag.tamanho_resposta =
      html.length;

    diag.preview =
      resumirHTML(html);

    diag.pagina_semef_valida =
      paginaSemefValida(html);

    diagnostico.push(diag);

    if (
      resposta.ok &&
      paginaSemefValida(html)
    ) {

      return {
        ok: true,

        via:
          "cloudflare-direto",

        status:
          resposta.status,

        duracao_total_ms:
          Date.now() -
          inicioTotal,

        diagnostico,

        html,
      };
    }

  } catch (erro) {

    diagnostico.push({
      etapa:
        "detalhe_direto",

      sucesso:
        false,

      tipo_erro:
        erro?.name || "",

      mensagem:
        String(
          erro?.message ||
          erro
        ),

      causa:
        erro?.cause
          ? String(
              erro.cause.message ||
              erro.cause
            )
          : "",

      duracao_ms:
        Date.now() -
        inicioTotal,
    });
  }


  // =========================================================
  // TESTE 2
  // Página inicial
  // =========================================================

  let cookie = "";

  try {

    const inicio =
      Date.now();

    const respostaHome =
      await fetchComTimeout(
        SEMEF_HOME_URL,
        {
          method: "GET",

          headers: {
            "User-Agent":
              headersBase[
                "User-Agent"
              ],

            "Accept":
              headersBase[
                "Accept"
              ],

            "Accept-Language":
              headersBase[
                "Accept-Language"
              ],

            "Cache-Control":
              "no-cache",

            "Pragma":
              "no-cache",
          },

          redirect:
            "follow",
        },
        SEMEF_TIMEOUT_MS
      );

    const duracao =
      Date.now() - inicio;

    const htmlHome =
      await respostaHome.text();

    cookie =
      extrairCookie(
        respostaHome.headers
      );

    const diag =
      diagnosticoResposta(
        "pagina_inicial",
        respostaHome,
        duracao
      );

    diag.tamanho_resposta =
      htmlHome.length;

    diag.preview =
      resumirHTML(
        htmlHome
      );

    diag.cookie_recebido =
      Boolean(cookie);

    diagnostico.push(
      diag
    );

  } catch (erro) {

    diagnostico.push({
      etapa:
        "pagina_inicial",

      sucesso:
        false,

      tipo_erro:
        erro?.name || "",

      mensagem:
        String(
          erro?.message ||
          erro
        ),

      causa:
        erro?.cause
          ? String(
              erro.cause.message ||
              erro.cause
            )
          : "",
    });
  }


  // =========================================================
  // TESTE 3
  // Detalhe após a sessão
  // =========================================================

  try {

    const inicio =
      Date.now();

    const headersSessao = {
      ...headersBase,
    };

    if (cookie) {
      headersSessao.Cookie =
        cookie;
    }

    const resposta =
      await fetchComTimeout(
        url,
        {
          method: "GET",

          headers:
            headersSessao,

          redirect:
            "follow",
        },
        SEMEF_TIMEOUT_MS
      );

    const duracao =
      Date.now() - inicio;

    const html =
      await resposta.text();

    const diag =
      diagnosticoResposta(
        "detalhe_com_sessao",
        resposta,
        duracao
      );

    diag.tamanho_resposta =
      html.length;

    diag.preview =
      resumirHTML(html);

    diag.cookie_enviado =
      Boolean(cookie);

    diag.pagina_semef_valida =
      paginaSemefValida(html);

    diagnostico.push(
      diag
    );

    if (
      resposta.ok &&
      paginaSemefValida(html)
    ) {

      return {
        ok: true,

        via:
          cookie
            ? "cloudflare-sessao"
            : "cloudflare-segunda-tentativa",

        status:
          resposta.status,

        duracao_total_ms:
          Date.now() -
          inicioTotal,

        diagnostico,

        html,
      };
    }

  } catch (erro) {

    diagnostico.push({
      etapa:
        "detalhe_com_sessao",

      sucesso:
        false,

      tipo_erro:
        erro?.name || "",

      mensagem:
        String(
          erro?.message ||
          erro
        ),

      causa:
        erro?.cause
          ? String(
              erro.cause.message ||
              erro.cause
            )
          : "",
    });
  }


  // =========================================================
  // FALHA FINAL
  // =========================================================

  return {
    ok: false,

    erro:
      "Não foi possível consultar a SEMEF pelo Cloudflare Worker.",

    host:
      SEMEF_HOST,

    endpoint:
      SEMEF_DETALHE_URL,

    protocolo:
      codProtocolo,

    timeout_por_tentativa_ms:
      SEMEF_TIMEOUT_MS,

    duracao_total_ms:
      Date.now() -
      inicioTotal,

    diagnostico,
  };
}


// ============================================================
// FETCH COM TIMEOUT
// ============================================================

async function fetchComTimeout(
  url,
  options,
  timeoutMs
) {

  const controller =
    new AbortController();

  const timer =
    setTimeout(
      () =>
        controller.abort(
          "Tempo excedido"
        ),
      timeoutMs
    );

  try {

    return await fetch(
      url,
      {
        ...options,
        signal:
          controller.signal,
      }
    );

  } catch (erro) {

    if (
      controller.signal.aborted
    ) {

      const timeoutError =
        new Error(
          `Timeout após ${timeoutMs} ms ao acessar ${url}`
        );

      timeoutError.name =
        "TimeoutError";

      throw timeoutError;
    }

    throw erro;

  } finally {

    clearTimeout(
      timer
    );
  }
}


// ============================================================
// VALIDAR HTML SEMEF
// ============================================================

function paginaSemefValida(html) {

  const texto =
    String(html || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(
        /[\u0300-\u036f]/g,
        ""
      );

  return (
    texto.includes(
      "consulta de documentos e processos"
    )
    &&
    texto.includes(
      "processo"
    )
    &&
    texto.includes(
      "situacao"
    )
    &&
    (
      texto.includes(
        "historico do processo"
      )
      ||
      texto.includes(
        "despacho movimentacao"
      )
    )
  );
}


// ============================================================
// COOKIE
// ============================================================

function extrairCookie(headers) {

  try {

    if (
      typeof headers.getSetCookie
      === "function"
    ) {

      const cookies =
        headers.getSetCookie();

      if (
        Array.isArray(cookies)
      ) {

        return cookies
          .map(
            item =>
              String(item)
                .split(";")[0]
          )
          .filter(Boolean)
          .join("; ");
      }
    }

  } catch {
    // continua
  }

  const setCookie =
    headers.get(
      "set-cookie"
    );

  if (!setCookie) {
    return "";
  }

  return setCookie
    .split(",")
    .map(
      item =>
        item
          .trim()
          .split(";")[0]
    )
    .filter(Boolean)
    .join("; ");
}


// ============================================================
// GITHUB HEADERS
// ============================================================

function githubHeaders(token) {

  return {
    "Accept":
      "application/vnd.github+json",

    "Authorization":
      `Bearer ${token}`,

    "X-GitHub-Api-Version":
      "2022-11-28",

    "User-Agent":
      "monitor-processos",

    "Content-Type":
      "application/json",
  };
}


// ============================================================
// BASE64 UTF-8
// ============================================================

function base64ParaTexto(base64) {

  const binario =
    atob(
      base64.replace(
        /\n/g,
        ""
      )
    );

  const bytes =
    new Uint8Array(
      binario.length
    );

  for (
    let i = 0;
    i < binario.length;
    i++
  ) {

    bytes[i] =
      binario.charCodeAt(i);
  }

  return new TextDecoder(
    "utf-8"
  ).decode(bytes);
}


function textoParaBase64(texto) {

  const bytes =
    new TextEncoder()
      .encode(texto);

  let binario = "";

  const tamanhoBloco =
    8192;

  for (
    let i = 0;
    i < bytes.length;
    i += tamanhoBloco
  ) {

    const bloco =
      bytes.subarray(
        i,
        i + tamanhoBloco
      );

    binario +=
      String.fromCharCode(
        ...bloco
      );
  }

  return btoa(binario);
}


// ============================================================
// NORMALIZAR PROCESSOS.JSON
// ============================================================

function normalizarItemProcesso(item) {

  if (
    typeof item === "string"
  ) {

    const numero =
      normalizarNumero(item);

    const origem =
      detectarOrigem(numero);

    const resultado = {
      numero,
      origem,
    };

    if (origem === "semef") {

      const protocolo =
        protocoloSemefConhecido(
          numero
        );

      if (protocolo) {

        resultado.cod_protocolo =
          protocolo;
      }
    }

    return resultado;
  }

  if (
    item &&
    typeof item === "object"
  ) {

    const numero =
      normalizarNumero(
        item.numero ||
        item.processo ||
        ""
      );

    const origem =
      normalizarOrigem(
        item.origem ||
        detectarOrigem(numero)
      );

    const resultado = {
      numero,
      origem,
    };

    if (
      origem === "semef"
    ) {

      const protocolo =
        normalizarProtocolo(
          item.cod_protocolo ||
          item.codProtocolo ||
          protocoloSemefConhecido(
            numero
          )
        );

      if (protocolo) {

        resultado.cod_protocolo =
          protocolo;
      }
    }

    return resultado;
  }

  return null;
}


// ============================================================
// LER PROCESSOS.JSON
// ============================================================

async function lerProcessos(token) {

  const url =
    `${API_BASE}/contents/${ARQUIVO_PROCESSOS}?ref=${encodeURIComponent(BRANCH)}`;

  const resposta =
    await fetch(
      url,
      {
        method: "GET",
        headers:
          githubHeaders(token),
      }
    );

  if (!resposta.ok) {

    const detalhe =
      await resposta.text();

    throw new Error(
      `GitHub retornou HTTP ${resposta.status} ao ler processos.json: ${detalhe}`
    );
  }

  const arquivo =
    await resposta.json();

  const texto =
    base64ParaTexto(
      String(
        arquivo.content ||
        ""
      )
    );

  const dados =
    JSON.parse(texto);

  if (
    !dados ||
    !Array.isArray(
      dados.processos
    )
  ) {

    throw new Error(
      "processos.json possui formato inválido."
    );
  }

  const processos =
    dados.processos
      .map(
        normalizarItemProcesso
      )
      .filter(
        item =>
          item &&
          item.numero
      );

  return {
    sha:
      arquivo.sha,

    processos,
  };
}


// ============================================================
// GRAVAR PROCESSOS.JSON
// ============================================================

async function gravarProcessos(
  token,
  processos,
  sha,
  mensagem
) {

  const url =
    `${API_BASE}/contents/${ARQUIVO_PROCESSOS}`;

  const conteudo =
    JSON.stringify(
      {
        processos,
      },
      null,
      2
    )
    +
    "\n";

  const resposta =
    await fetch(
      url,
      {
        method: "PUT",

        headers:
          githubHeaders(token),

        body:
          JSON.stringify(
            {
              message:
                mensagem,

              content:
                textoParaBase64(
                  conteudo
                ),

              sha,

              branch:
                BRANCH,
            }
          ),
      }
    );

  if (!resposta.ok) {

    const detalhe =
      await resposta.text();

    throw new Error(
      `GitHub retornou HTTP ${resposta.status}: ${detalhe}`
    );
  }

  return resposta.json();
}


// ============================================================
// DISPARAR WORKFLOW
// ============================================================

async function dispararWorkflow(token) {

  const url =
    `${API_BASE}/actions/workflows/${WORKFLOW}/dispatches`;

  const resposta =
    await fetch(
      url,
      {
        method: "POST",

        headers:
          githubHeaders(token),

        body:
          JSON.stringify(
            {
              ref:
                BRANCH,
            }
          ),
      }
    );

  if (
    resposta.status === 204
  ) {

    return {
      ok: true,
      mensagem:
        "Atualização iniciada.",
    };
  }

  const detalhe =
    await resposta.text();

  return {
    ok: false,

    erro:
      "GitHub recusou o disparo do monitor.",

    statusGitHub:
      resposta.status,

    detalhe,
  };
}


// ============================================================
// ADICIONAR
// ============================================================

async function adicionarProcesso(
  token,
  numero,
  origem,
  codProtocolo
) {

  const atual =
    await lerProcessos(token);

  const processos =
    atual.processos;

  const jaExiste =
    processos.some(
      item =>
        item.numero === numero
    );

  if (jaExiste) {

    return {
      ok: false,
      erro:
        "Este processo já está cadastrado.",
    };
  }

  const novo = {
    numero,
    origem,
  };

  if (
    origem === "semef"
  ) {

    novo.cod_protocolo =
      codProtocolo;
  }

  processos.push(novo);

  await gravarProcessos(
    token,
    processos,
    atual.sha,
    `Adiciona processo ${numero}`
  );

  const workflow =
    await dispararWorkflow(token);

  return {
    ok: true,

    mensagem:
      `Processo ${origem.toUpperCase()} adicionado.`,

    numero,

    origem,

    cod_protocolo:
      origem === "semef"
        ? codProtocolo
        : undefined,

    total:
      processos.length,

    consultaIniciada:
      workflow.ok,
  };
}


// ============================================================
// EXCLUIR
// ============================================================

async function excluirProcesso(
  token,
  numero
) {

  const atual =
    await lerProcessos(token);

  const processos =
    atual.processos;

  const existe =
    processos.some(
      item =>
        item.numero === numero
    );

  if (!existe) {

    return {
      ok: false,
      erro:
        "Processo não encontrado.",
    };
  }

  const novaLista =
    processos.filter(
      item =>
        item.numero !== numero
    );

  await gravarProcessos(
    token,
    novaLista,
    atual.sha,
    `Remove processo ${numero}`
  );

  const workflow =
    await dispararWorkflow(token);

  return {
    ok: true,

    mensagem:
      "Processo removido.",

    numero,

    total:
      novaLista.length,

    consultaIniciada:
      workflow.ok,
  };
}
