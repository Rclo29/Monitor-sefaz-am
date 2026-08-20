export default {

  async fetch(request, env) {

    const allowedOrigins = [
      "https://rclo29.github.io",
      "https://rclo29.github.io/",
    ];

    const origin =
      request.headers.get("Origin")
      || "";

    const allowOrigin =
      allowedOrigins.some(
        item =>
          origin.startsWith(
            item.replace(/\/$/, "")
          )
      )
      ?
      origin
      :
      "*";


    const corsHeaders = {

      "Access-Control-Allow-Origin":
        allowOrigin,

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


    if (
      request.method === "OPTIONS"
    ) {

      return new Response(
        null,
        {
          status: 204,
          headers: corsHeaders,
        }
      );

    }


    if (
      request.method !== "POST"
    ) {

      return respostaJSON(
        {
          ok: false,
          erro:
            "Método não permitido.",
        },
        405,
        jsonHeaders
      );

    }


    if (
      !env.GITHUB_TOKEN
    ) {

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


    let body = {};

    try {

      body =
        await request.json();

    } catch {

      body = {};

    }


    const acao =
      String(
        body.acao
        ||
        ""
      )
        .trim()
        .toLowerCase();


    try {

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
          ?
          200
          :
          500,
          jsonHeaders
        );

      }


      if (
        acao === "adicionar"
      ) {

        const numero =
          normalizarNumero(
            body.numero
          );


        if (
          !numero
        ) {

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
                "Ainda não conhecemos o código interno deste processo SEMEF. Faça uma consulta no SIGED uma primeira vez e informe o link do processo para cadastrarmos o protocolo.",
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
          ?
          200
          :
          400,
          jsonHeaders
        );

      }


      if (
        acao === "excluir"
      ) {

        const numero =
          normalizarNumero(
            body.numero
          );


        if (
          !numero
        ) {

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
          ?
          200
          :
          400,
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
          erro?.message
          ||
          erro
        )
      );


      return respostaJSON(
        {
          ok: false,

          erro:
            "Erro interno do Worker.",

          detalhe:
            String(
              erro?.message
              ||
              erro
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
   PROTOCOLOS SEMEF CONHECIDOS
   =========================================================== */

const SEMEF_PROTOCOLS = {

  "2024.18000.19012.0.008302":
    "7954846",

  "2026.18000.19951.0.024703":
    "11442112",

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
    valor
    ||
    ""
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
      valor
      ||
      ""
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
    valor
    ||
    ""
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
   NORMALIZA ITEM
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


      if (
        protocolo
      ) {

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


      if (
        protocolo
      ) {

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


  if (
    !resposta.ok
  ) {

    const detalhe =
      await resposta.text();


    console.error(
      "ERRO GITHUB AO LER processos.json:",
      "STATUS:",
      resposta.status,
      "DETALHE:",
      detalhe
    );


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


  const conteudoBase64 =
    textoParaBase64(
      conteudo
    );


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
              conteudoBase64,

            sha,

            branch:
              BRANCH,

          }),

      }

    );


  if (
    !resposta.ok
  ) {

    const detalhe =
      await resposta.text();


    console.error(
      "ERRO GITHUB AO GRAVAR processos.json:",
      "STATUS:",
      resposta.status,
      "DETALHE:",
      detalhe
    );


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


  console.error(
    "ERRO AO DISPARAR WORKFLOW:",
    "STATUS:",
    resposta.status,
    "DETALHE:",
    detalhe
  );


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


  if (
    jaExiste
  ) {

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


  if (
    !existe
  ) {

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
