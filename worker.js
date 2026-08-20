// deploy cloudflare 20-08

export default {

  async fetch(request, env) {

    /* =====================================================
       CORS
       ===================================================== */

    const origin =
      request.headers.get("Origin") || "";

    const corsHeaders = {

      "Access-Control-Allow-Origin":
        origin || "*",

      "Access-Control-Allow-Methods":
        "POST, OPTIONS",

      "Access-Control-Allow-Headers":
        "Content-Type",

      "Access-Control-Max-Age":
        "86400",

    };


    const jsonHeaders = {

      ...corsHeaders,

      "Content-Type":
        "application/json; charset=utf-8",

      "Cache-Control":
        "no-store",

    };


    if (request.method === "OPTIONS") {

      return new Response(
        null,
        {
          status: 204,
          headers: corsHeaders,
        }
      );

    }


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


    let body = {};

    try {

      body =
        await request.json();

    } catch {

      body = {};

    }


    const acao =
      String(
        body.acao || ""
      )
        .trim()
        .toLowerCase();


    try {

      /* ===================================================
         CONSULTAR SEMEF
         Não depende do GitHub Token.
         =================================================== */

      if (
        acao === "consultar_semef"
      ) {

        const numero =
          normalizarNumero(
            body.numero || ""
          );

        let codProtocolo =
          normalizarProtocolo(
            body.cod_protocolo
            ||
            body.codProtocolo
            ||
            ""
          );


        if (
          !codProtocolo
          &&
          numero
        ) {

          codProtocolo =
            protocoloSemefConhecido(
              numero
            );

        }


        if (
          numero
          &&
          !validarNumero(
            numero,
            "semef"
          )
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

            cod_protocolo:
              codProtocolo,

          },
          resultado.ok
            ? 200
            : 502,
          jsonHeaders
        );

      }


      /* ===================================================
         A PARTIR DAQUI PRECISAMOS DO TOKEN GITHUB
         =================================================== */

      if (!env.GITHUB_TOKEN) {

        return respostaJSON(
          {
            ok: false,
            erro:
              "GITHUB_TOKEN não configurado.",
          },
          500,
          jsonHeaders
        );

      }


      /* ===================================================
         ATUALIZAR
         =================================================== */

      if (
        acao === "atualizar"
      ) {

        const resultado =
          await dispararWorkflow(
            env.GITHUB_TOKEN
          );


        return respostaJSON(
          resultado,
          resultado.ok
            ? 200
            : 500,
          jsonHeaders
        );

      }


      /* ===================================================
         ADICIONAR
         =================================================== */

      if (
        acao === "adicionar"
      ) {

        const numero =
          normalizarNumero(
            body.numero
          );


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
            body.origem
            ||
            detectarOrigem(
              numero
            )
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
                  ?
                  "Formato SEMEF inválido. Exemplo: 2026.18000.19951.0.024703"
                  :
                  "Formato SEFAZ inválido. Exemplo: 01.01.028101.030037/2026-43",

            },
            400,
            jsonHeaders
          );

        }


        let codProtocolo =
          normalizarProtocolo(
            body.cod_protocolo
            ||
            body.codProtocolo
            ||
            ""
          );


        if (
          origem === "semef"
          &&
          !codProtocolo
        ) {

          codProtocolo =
            protocoloSemefConhecido(
              numero
            );

        }


        if (
          origem === "semef"
          &&
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
          resultado.ok
            ? 200
            : 400,
          jsonHeaders
        );

      }


      /* ===================================================
         EXCLUIR
         =================================================== */

      if (
        acao === "excluir"
      ) {

        const numero =
          normalizarNumero(
            body.numero
          );


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
          resultado.ok
            ? 200
            : 400,
          jsonHeaders
        );

      }


      return respostaJSON(
        {
          ok: false,
          erro:
            "Ação desconhecida.",
        },
        400,
        jsonHeaders
      );


    } catch (erro) {

      console.error(
        "Erro no Worker:",
        String(
          erro?.message || erro
        )
      );


      return respostaJSON(
        {

          ok: false,

          erro:
            "Erro interno do Worker.",

          detalhe:
            String(
              erro?.message || erro
            ),

        },
        500,
        jsonHeaders
      );

    }

  },

};


/* ===========================================================
   CONFIGURAÇÃO GITHUB
   =========================================================== */

const OWNER =
  "Rclo29";

const REPO =
  "Monitor-sefaz-am";

const BRANCH =
  "main";

const WORKFLOW =
  "monitor.yml";

const ARQUIVO_PROCESSOS =
  "processos.json";

const API_BASE =
  `https://api.github.com/repos/${OWNER}/${REPO}`;


/* ===========================================================
   CONFIGURAÇÃO SEMEF
   =========================================================== */

const SEMEF_HOME_URL =
  "https://sigedweb.manaus.am.gov.br/protonweb/";

const SEMEF_DETALHE_URL =
  "https://sigedweb.manaus.am.gov.br/protonweb/detalhe.aspx";

const SEMEF_TIMEOUT_MS =
  8000;


/* ===========================================================
   PROTOCOLOS SEMEF
   =========================================================== */

const SEMEF_PROTOCOLS = {

  "2024.18000.19012.0.008302":
    "7954846",

  "2026.18000.19951.0.024703":
    "11442112",

  "2026.18000.19951.0.014382":
    "11037580",

};


/* ===========================================================
   RESPOSTA JSON
   =========================================================== */

function respostaJSON(
  dados,
  status,
  headers
) {

  return new Response(

    JSON.stringify(
      dados
    ),

    {
      status,
      headers,
    }

  );

}


/* ===========================================================
   NORMALIZAÇÃO
   =========================================================== */

function normalizarNumero(
  valor
) {

  return String(
    valor || ""
  )
    .trim()
    .replace(
      /\s+/g,
      ""
    );

}


function normalizarOrigem(
  valor
) {

  const origem =
    String(
      valor || ""
    )
      .trim()
      .toLowerCase();


  if (
    origem === "semef"
    ||
    origem === "siged"
  ) {

    return "semef";

  }


  return "sefaz";

}


function normalizarProtocolo(
  valor
) {

  return String(
    valor || ""
  )
    .replace(
      /\D/g,
      ""
    );

}


/* ===========================================================
   DETECTAR ORIGEM
   =========================================================== */

function detectarOrigem(
  numero
) {

  const semefRegex =
    /^\d{4}\.\d{5}\.\d{5}\.\d\.\d{6}$/;


  if (
    semefRegex.test(
      numero
    )
  ) {

    return "semef";

  }


  return "sefaz";

}


/* ===========================================================
   VALIDAR NÚMERO
   =========================================================== */

function validarNumero(
  numero,
  origem
) {

  if (
    origem === "semef"
  ) {

    return (
      /^\d{4}\.\d{5}\.\d{5}\.\d\.\d{6}$/
        .test(
          numero
        )
    );

  }


  return (
    /^\d{2}\.\d{2}\.\d{6}\.\d{6}\/\d{4}-\d{2}$/
      .test(
        numero
      )
  );

}


/* ===========================================================
   PROTOCOLO SEMEF
   =========================================================== */

function protocoloSemefConhecido(
  numero
) {

  return (
    SEMEF_PROTOCOLS[
      numero
    ]
    ||
    ""
  );

}


/* ===========================================================
   CONSULTA SEMEF PELO CLOUDFLARE
   =========================================================== */

async function consultarSemefPorWorker(
  codProtocolo
) {

  const url =
    SEMEF_DETALHE_URL
    +
    "?origem=1&cod_protocolo="
    +
    encodeURIComponent(
      codProtocolo
    );


  const headers = {

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


  const erros = [];


  /* =======================================================
     TENTATIVA 1 — DETALHE DIRETO
     ======================================================= */

  try {

    const resposta =
      await fetchComTimeout(
        url,
        {
          method: "GET",
          headers,
          redirect: "follow",
        },
        SEMEF_TIMEOUT_MS
      );


    if (
      resposta.ok
    ) {

      const html =
        await resposta.text();


      if (
        paginaSemefValida(
          html
        )
      ) {

        return {

          ok: true,

          via:
            "cloudflare-direto",

          status:
            resposta.status,

          html,

        };

      }


      erros.push(
        "A SEMEF respondeu, mas a página direta não contém os dados esperados."
      );

    } else {

      erros.push(
        `Acesso direto retornou HTTP ${resposta.status}.`
      );

    }

  } catch (erro) {

    erros.push(
      "Falha no acesso direto: "
      +
      String(
        erro?.message || erro
      )
    );

  }


  /* =======================================================
     TENTATIVA 2 — ABRIR HOME
     ======================================================= */

  let cookie = "";


  try {

    const respostaHome =
      await fetchComTimeout(
        SEMEF_HOME_URL,
        {

          method:
            "GET",

          headers: {

            "User-Agent":
              headers["User-Agent"],

            "Accept":
              headers["Accept"],

            "Accept-Language":
              headers["Accept-Language"],

            "Cache-Control":
              "no-cache",

          },

          redirect:
            "follow",

        },
        SEMEF_TIMEOUT_MS
      );


    if (
      respostaHome.ok
    ) {

      cookie =
        extrairCookie(
          respostaHome.headers
        );

    } else {

      erros.push(
        `Página inicial retornou HTTP ${respostaHome.status}.`
      );

    }

  } catch (erro) {

    erros.push(
      "Falha ao abrir a página inicial: "
      +
      String(
        erro?.message || erro
      )
    );

  }


  /* =======================================================
     TENTATIVA 3 — DETALHE COM COOKIE
     ======================================================= */

  try {

    const headersSessao = {
      ...headers,
    };


    if (cookie) {

      headersSessao.Cookie =
        cookie;

    }


    const resposta =
      await fetchComTimeout(
        url,
        {

          method:
            "GET",

          headers:
            headersSessao,

          redirect:
            "follow",

        },
        SEMEF_TIMEOUT_MS
      );


    if (
      resposta.ok
    ) {

      const html =
        await resposta.text();


      if (
        paginaSemefValida(
          html
        )
      ) {

        return {

          ok: true,

          via:
            cookie
              ?
              "cloudflare-sessao"
              :
              "cloudflare-segunda-tentativa",

          status:
            resposta.status,

          html,

        };

      }


      erros.push(
        "A segunda resposta da SEMEF não contém os dados esperados."
      );

    } else {

      erros.push(
        `Segunda tentativa retornou HTTP ${resposta.status}.`
      );

    }

  } catch (erro) {

    erros.push(
      "Falha na segunda tentativa: "
      +
      String(
        erro?.message || erro
      )
    );

  }


  return {

    ok:
      false,

    erro:
      "Não foi possível consultar a SEMEF pelo Cloudflare Worker.",

    detalhe:
      erros.join(
        " | "
      ),

  };

}


/* ===========================================================
   FETCH COM TIMEOUT
   =========================================================== */

async function fetchComTimeout(
  url,
  options,
  timeoutMs
) {

  const controller =
    new AbortController();


  const timer =
    setTimeout(
      () => {

        controller.abort();

      },
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

  } finally {

    clearTimeout(
      timer
    );

  }

}


/* ===========================================================
   VALIDAR HTML SEMEF
   =========================================================== */

function paginaSemefValida(
  html
) {

  const texto =
    String(
      html || ""
    )
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


/* ===========================================================
   EXTRAIR COOKIE DA SEMEF
   =========================================================== */

function extrairCookie(
  headers
) {

  try {

    if (
      typeof headers.getSetCookie
      ===
      "function"
    ) {

      const cookies =
        headers.getSetCookie();


      if (
        Array.isArray(
          cookies
        )
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

    /* continua */

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


/* ===========================================================
   HEADERS GITHUB
   =========================================================== */

function githubHeaders(
  token
) {

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


/* ===========================================================
   BASE64 UTF-8
   =========================================================== */

function base64ParaTexto(
  base64
) {

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
      binario.charCodeAt(
        i
      );

  }


  return new TextDecoder(
    "utf-8"
  ).decode(
    bytes
  );

}


function textoParaBase64(
  texto
) {

  const bytes =
    new TextEncoder()
      .encode(
        texto
      );


  let binario =
    "";


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


  return btoa(
    binario
  );

}


/* ===========================================================
   NORMALIZAR ITEM DO processos.json
   =========================================================== */

function normalizarItemProcesso(
  item
) {

  if (
    typeof item === "string"
  ) {

    const numero =
      normalizarNumero(
        item
      );


    const origem =
      detectarOrigem(
        numero
      );


    const resultado = {

      numero,

      origem,

    };


    if (
      origem === "semef"
    ) {

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
    item
    &&
    typeof item === "object"
  ) {

    const numero =
      normalizarNumero(
        item.numero
        ||
        item.processo
        ||
        ""
      );


    const origem =
      normalizarOrigem(
        item.origem
        ||
        detectarOrigem(
          numero
        )
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

          item.cod_protocolo

          ||

          item.codProtocolo

          ||

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


/* ===========================================================
   LER processos.json
   =========================================================== */

async function lerProcessos(
  token
) {

  const url =
    `${API_BASE}/contents/${ARQUIVO_PROCESSOS}?ref=${encodeURIComponent(BRANCH)}`;


  const resposta =
    await fetch(
      url,
      {

        method:
          "GET",

        headers:
          githubHeaders(
            token
          ),

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
        arquivo.content
        ||
        ""
      )
    );


  const dados =
    JSON.parse(
      texto
    );


  if (
    !dados
    ||
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
          item
          &&
          item.numero
      );


  return {

    sha:
      arquivo.sha,

    processos,

  };

}


/* ===========================================================
   GRAVAR processos.json
   =========================================================== */

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

        method:
          "PUT",

        headers:
          githubHeaders(
            token
          ),

        body:
          JSON.stringify({

            message:
              mensagem,

            content:
              textoParaBase64(
                conteudo
              ),

            sha,

            branch:
              BRANCH,

          }),

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


/* ===========================================================
   DISPARAR WORKFLOW
   =========================================================== */

async function dispararWorkflow(
  token
) {

  const url =
    `${API_BASE}/actions/workflows/${WORKFLOW}/dispatches`;


  const resposta =
    await fetch(
      url,
      {

        method:
          "POST",

        headers:
          githubHeaders(
            token
          ),

        body:
          JSON.stringify({

            ref:
              BRANCH,

          }),

      }
    );


  if (
    resposta.status === 204
  ) {

    return {

      ok:
        true,

      mensagem:
        "Atualização iniciada.",

    };

  }


  const detalhe =
    await resposta.text();


  return {

    ok:
      false,

    erro:
      "GitHub recusou o disparo do monitor.",

    statusGitHub:
      resposta.status,

    detalhe,

  };

}


/* ===========================================================
   ADICIONAR PROCESSO
   =========================================================== */

async function adicionarProcesso(
  token,
  numero,
  origem,
  codProtocolo
) {

  const atual =
    await lerProcessos(
      token
    );


  const processos =
    atual.processos;


  const jaExiste =
    processos.some(
      item =>
        item.numero
        ===
        numero
    );


  if (jaExiste) {

    return {

      ok:
        false,

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


  processos.push(
    novo
  );


  await gravarProcessos(

    token,

    processos,

    atual.sha,

    `Adiciona processo ${numero}`

  );


  const workflow =
    await dispararWorkflow(
      token
    );


  return {

    ok:
      true,

    mensagem:
      `Processo ${origem.toUpperCase()} adicionado.`,

    numero,

    origem,

    cod_protocolo:
      origem === "semef"
        ?
        codProtocolo
        :
        undefined,

    total:
      processos.length,

    consultaIniciada:
      workflow.ok,

  };

}


/* ===========================================================
   EXCLUIR PROCESSO
   =========================================================== */

async function excluirProcesso(
  token,
  numero
) {

  const atual =
    await lerProcessos(
      token
    );


  const processos =
    atual.processos;


  const existe =
    processos.some(
      item =>
        item.numero
        ===
        numero
    );


  if (!existe) {

    return {

      ok:
        false,

      erro:
        "Processo não encontrado.",

    };

  }


  const novaLista =
    processos.filter(
      item =>
        item.numero
        !==
        numero
    );


  await gravarProcessos(

    token,

    novaLista,

    atual.sha,

    `Remove processo ${numero}`

  );


  const workflow =
    await dispararWorkflow(
      token
    );


  return {

    ok:
      true,

    mensagem:
      "Processo removido.",

    numero,

    total:
      novaLista.length,

    consultaIniciada:
      workflow.ok,

  };

}
