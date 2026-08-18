// Monitor SEFAZ-AM - Cloudflare Worker

export default {
  async fetch(request, env) {
    const allowedOrigin = "https://rclo29.github.io";

    const corsHeaders = {
      "Access-Control-Allow-Origin": allowedOrigin,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
    };

    const jsonHeaders = {
      ...corsHeaders,
      "Content-Type": "application/json; charset=UTF-8",
      "Cache-Control": "no-store",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders,
      });
    }

    if (request.method !== "POST") {
      return respostaJSON(
        {
          ok: false,
          erro: "Método não permitido",
        },
        405,
        jsonHeaders
      );
    }

    if (!env.GITHUB_TOKEN) {
      return respostaJSON(
        {
          ok: false,
          erro: "GITHUB_TOKEN não configurado no Worker",
        },
        500,
        jsonHeaders
      );
    }

    let body = {};

    try {
      body = await request.json();
    } catch {
      body = {};
    }

    const acao = body.acao || "atualizar";

    try {
      if (acao === "atualizar") {
        const resultado = await dispararWorkflow(env.GITHUB_TOKEN);

        return respostaJSON(
          resultado,
          resultado.ok ? 200 : 502,
          jsonHeaders
        );
      }

      if (acao === "adicionar") {
        const numero = normalizarNumero(body.numero);

        if (!numero) {
          return respostaJSON(
            {
              ok: false,
              erro: "Número do processo não informado",
            },
            400,
            jsonHeaders
          );
        }

        if (!validarNumero(numero)) {
          return respostaJSON(
            {
              ok: false,
              erro:
                "Formato inválido. Exemplo: 01.01.028101.030037/2026-43",
            },
            400,
            jsonHeaders
          );
        }

        const resultado = await adicionarProcesso(
          env.GITHUB_TOKEN,
          numero
        );

        return respostaJSON(
          resultado,
          resultado.ok ? 200 : 400,
          jsonHeaders
        );
      }

      if (acao === "excluir") {
        const numero = normalizarNumero(body.numero);

        if (!numero) {
          return respostaJSON(
            {
              ok: false,
              erro: "Número do processo não informado",
            },
            400,
            jsonHeaders
          );
        }

        const resultado = await excluirProcesso(
          env.GITHUB_TOKEN,
          numero
        );

        return respostaJSON(
          resultado,
          resultado.ok ? 200 : 400,
          jsonHeaders
        );
      }

      return respostaJSON(
        {
          ok: false,
          erro: "Ação desconhecida",
        },
        400,
        jsonHeaders
      );
    } catch (erro) {
      return respostaJSON(
        {
          ok: false,
          erro: "Erro interno do Worker",
          detalhe: String(erro),
        },
        500,
        jsonHeaders
      );
    }
  },
};


/* ============================================================
   CONFIGURAÇÃO GITHUB
============================================================ */

const OWNER = "Rclo29";
const REPO = "Monitor-sefaz-am";
const BRANCH = "main";
const WORKFLOW = "monitor.yml";
const ARQUIVO_PROCESSOS = "processos.json";

const API_BASE =
  `https://api.github.com/repos/${OWNER}/${REPO}`;


/* ============================================================
   HEADERS GITHUB
============================================================ */

function githubHeaders(token) {
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "monitor-sefaz-am-worker",
    "Content-Type": "application/json",
  };
}


/* ============================================================
   RESPOSTA JSON
============================================================ */

function respostaJSON(dados, status, headers) {
  return new Response(
    JSON.stringify(dados),
    {
      status,
      headers,
    }
  );
}


/* ============================================================
   NORMALIZAÇÃO / VALIDAÇÃO
============================================================ */

function normalizarNumero(valor) {
  return String(valor || "")
    .trim()
    .replace(/\s+/g, "");
}


function validarNumero(numero) {
  return /^\d{2}\.\d{2}\.\d{6}\.\d{6}\/\d{4}-\d{2}$/.test(
    numero
  );
}


/* ============================================================
   LER processos.json
============================================================ */

async function lerProcessos(token) {
  const url =
    `${API_BASE}/contents/${ARQUIVO_PROCESSOS}?ref=${BRANCH}`;

  const resposta = await fetch(
    url,
    {
      method: "GET",
      headers: githubHeaders(token),
    }
  );

  if (!resposta.ok) {
    const detalhe = await resposta.text();

    throw new Error(
      `Falha ao ler processos.json. HTTP ${resposta.status}. ${detalhe}`
    );
  }

  const arquivo = await resposta.json();

  const conteudoBase64 =
    String(arquivo.content || "")
      .replace(/\n/g, "");

  const texto =
    decodeURIComponent(
      escape(
        atob(conteudoBase64)
      )
    );

  const dados = JSON.parse(texto);

  if (
    !dados ||
    !Array.isArray(dados.processos)
  ) {
    throw new Error(
      "processos.json possui formato inválido."
    );
  }

  return {
    sha: arquivo.sha,
    dados,
  };
}


/* ============================================================
   GRAVAR processos.json
============================================================ */

async function gravarProcessos(
  token,
  processos,
  sha,
  mensagem
) {
  const url =
    `${API_BASE}/contents/${ARQUIVO_PROCESSOS}`;

  const conteudo = JSON.stringify(
    {
      processos,
    },
    null,
    2
  ) + "\n";

  const conteudoBase64 =
    btoa(
      unescape(
        encodeURIComponent(conteudo)
      )
    );

  const resposta = await fetch(
    url,
    {
      method: "PUT",

      headers:
        githubHeaders(token),

      body: JSON.stringify({
        message: mensagem,
        content: conteudoBase64,
        sha,
        branch: BRANCH,
      }),
    }
  );

  if (!resposta.ok) {
    const detalhe = await resposta.text();

    throw new Error(
      `Falha ao atualizar processos.json. HTTP ${resposta.status}. ${detalhe}`
    );
  }

  return resposta.json();
}


/* ============================================================
   DISPARAR WORKFLOW
============================================================ */

async function dispararWorkflow(token) {
  const url =
    `${API_BASE}/actions/workflows/${WORKFLOW}/dispatches`;

  const resposta = await fetch(
    url,
    {
      method: "POST",

      headers:
        githubHeaders(token),

      body: JSON.stringify({
        ref: BRANCH,
      }),
    }
  );

  if (resposta.status === 204) {
    return {
      ok: true,
      mensagem:
        "Atualização dos processos iniciada.",
    };
  }

  const detalhe = await resposta.text();

  return {
    ok: false,
    erro:
      "GitHub recusou o disparo do workflow.",
    statusGitHub:
      resposta.status,
    detalhe,
  };
}


/* ============================================================
   ADICIONAR PROCESSO
============================================================ */

async function adicionarProcesso(
  token,
  numero
) {
  const atual =
    await lerProcessos(token);

  const processos =
    atual.dados.processos
      .map(normalizarNumero)
      .filter(Boolean);

  if (processos.includes(numero)) {
    return {
      ok: false,
      erro:
        "Este processo já está cadastrado.",
    };
  }

  processos.push(numero);

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
      "Processo adicionado com sucesso.",
    numero,
    total:
      processos.length,
    consultaIniciada:
      workflow.ok,
  };
}


/* ============================================================
   EXCLUIR PROCESSO
============================================================ */

async function excluirProcesso(
  token,
  numero
) {
  const atual =
    await lerProcessos(token);

  const processos =
    atual.dados.processos
      .map(normalizarNumero)
      .filter(Boolean);

  if (!processos.includes(numero)) {
    return {
      ok: false,
      erro:
        "Processo não encontrado.",
    };
  }

  const novaLista =
    processos.filter(
      item =>
        item !== numero
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
      "Processo removido com sucesso.",
    numero,
    total:
      novaLista.length,
    consultaIniciada:
      workflow.ok,
  };
}
