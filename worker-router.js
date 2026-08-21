import workerEntry from "./worker-entry.js";

const ROUTER_VERSION = "router-v4-workflow-diagnostics";
const GITHUB_API = "https://api.github.com/repos/Rclo29/Monitor-sefaz-am";
const WORKFLOW_FILE = "monitor.yml";
const BRANCH = "main";

function json(dados, status = 200) {
  return new Response(JSON.stringify(dados, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}

function githubHeaders(token) {
  return {
    "Accept": "application/vnd.github+json",
    "Authorization": `Bearer ${token}`,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "monitor-processos",
    "Content-Type": "application/json",
  };
}

function resumirDetalhe(texto) {
  const valor = String(texto || "").trim();
  return valor.length > 800 ? `${valor.slice(0, 800)}…` : valor;
}

async function tentarWorkflowDispatch(token) {
  const endpoint = `${GITHUB_API}/actions/workflows/${encodeURIComponent(WORKFLOW_FILE)}/dispatches`;
  const inicio = Date.now();

  console.log("[monitor] workflow_dispatch iniciando", {
    endpoint,
    workflow: WORKFLOW_FILE,
    branch: BRANCH,
    token_configurado: Boolean(token),
  });

  const resposta = await fetch(endpoint, {
    method: "POST",
    headers: githubHeaders(token),
    body: JSON.stringify({ ref: BRANCH }),
  });

  const duracao_ms = Date.now() - inicio;
  const detalhe = resposta.status === 204 ? "" : resumirDetalhe(await resposta.text());

  console.log("[monitor] workflow_dispatch resposta", {
    status: resposta.status,
    ok: resposta.status === 204,
    duracao_ms,
    detalhe,
    github_request_id: resposta.headers.get("x-github-request-id") || "",
  });

  if (resposta.status === 204) {
    return {
      ok: true,
      metodo: "workflow_dispatch",
      statusGitHub: 204,
      duracao_ms,
    };
  }

  return {
    ok: false,
    metodo: "workflow_dispatch",
    statusGitHub: resposta.status,
    duracao_ms,
    detalhe,
  };
}

async function tentarRepositoryDispatch(token) {
  const endpoint = `${GITHUB_API}/dispatches`;
  const inicio = Date.now();

  console.log("[monitor] repository_dispatch iniciando", {
    endpoint,
    event_type: "atualizar-monitor",
    token_configurado: Boolean(token),
  });

  const resposta = await fetch(endpoint, {
    method: "POST",
    headers: githubHeaders(token),
    body: JSON.stringify({
      event_type: "atualizar-monitor",
      client_payload: {
        origem: "botao-monitor",
        solicitado_em: new Date().toISOString(),
      },
    }),
  });

  const duracao_ms = Date.now() - inicio;
  const detalhe = resposta.status === 204 ? "" : resumirDetalhe(await resposta.text());

  console.log("[monitor] repository_dispatch resposta", {
    status: resposta.status,
    ok: resposta.status === 204,
    duracao_ms,
    detalhe,
    github_request_id: resposta.headers.get("x-github-request-id") || "",
  });

  if (resposta.status === 204) {
    return {
      ok: true,
      metodo: "repository_dispatch",
      statusGitHub: 204,
      duracao_ms,
    };
  }

  return {
    ok: false,
    metodo: "repository_dispatch",
    statusGitHub: resposta.status,
    duracao_ms,
    detalhe,
  };
}

async function dispararAtualizacao(token) {
  console.log("[monitor] dispararAtualizacao", {
    router_version: ROUTER_VERSION,
    token_configurado: Boolean(token),
    token_tamanho: token ? String(token).length : 0,
  });

  if (!token) {
    const resultado = {
      ok: false,
      erro: "GITHUB_TOKEN não configurado no Worker.",
      router_version: ROUTER_VERSION,
    };
    console.error("[monitor] atualização recusada", resultado);
    return resultado;
  }

  const tentativas = [];

  try {
    const workflow = await tentarWorkflowDispatch(token);
    tentativas.push(workflow);

    if (workflow.ok) {
      const resultado = {
        ok: true,
        mensagem: "Atualização iniciada.",
        metodo: workflow.metodo,
        router_version: ROUTER_VERSION,
        tentativas,
      };
      console.log("[monitor] atualização aceita pelo GitHub", resultado);
      return resultado;
    }
  } catch (erro) {
    const falha = {
      ok: false,
      metodo: "workflow_dispatch",
      erro: String(erro?.message || erro),
    };
    tentativas.push(falha);
    console.error("[monitor] workflow_dispatch exceção", falha);
  }

  try {
    const repository = await tentarRepositoryDispatch(token);
    tentativas.push(repository);

    if (repository.ok) {
      const resultado = {
        ok: true,
        mensagem: "Atualização iniciada.",
        metodo: repository.metodo,
        router_version: ROUTER_VERSION,
        tentativas,
      };
      console.log("[monitor] atualização aceita pelo GitHub", resultado);
      return resultado;
    }
  } catch (erro) {
    const falha = {
      ok: false,
      metodo: "repository_dispatch",
      erro: String(erro?.message || erro),
    };
    tentativas.push(falha);
    console.error("[monitor] repository_dispatch exceção", falha);
  }

  const resultado = {
    ok: false,
    erro: "GitHub recusou o disparo do monitor.",
    router_version: ROUTER_VERSION,
    tentativas,
  };

  console.error("[monitor] todas as tentativas falharam", resultado);
  return resultado;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
          "Access-Control-Allow-Headers": "Content-Type",
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    if (request.method === "GET" && url.pathname === "/health") {
      return json({
        ok: true,
        service: "monitor-sefaz-am",
        router_version: ROUTER_VERSION,
        github_token_configurado: Boolean(env.GITHUB_TOKEN),
        timestamp: new Date().toISOString(),
      });
    }

    if (request.method === "GET" && url.pathname === "/semef-test") {
      const numero = url.searchParams.get("numero") || "";
      const protocolo = url.searchParams.get("cod_protocolo") || "";

      if (!numero || !protocolo) {
        return json(
          {
            ok: false,
            erro: "Informe numero e cod_protocolo.",
            router_version: ROUTER_VERSION,
          },
          400
        );
      }

      const interno = new Request(request.url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: "https://diagnostico.local",
        },
        body: JSON.stringify({
          acao: "consultar_semef",
          numero,
          cod_protocolo: protocolo,
        }),
      });

      return workerEntry.fetch(interno, env, ctx);
    }

    if (request.method === "POST") {
      try {
        const body = await request.clone().json();
        const acao = String(body?.acao || "").trim().toLowerCase();

        console.log("[monitor] POST recebido", {
          acao,
          pathname: url.pathname,
          router_version: ROUTER_VERSION,
        });

        if (acao === "atualizar") {
          const resultado = await dispararAtualizacao(env.GITHUB_TOKEN);
          return json(resultado, resultado.ok ? 200 : 500);
        }
      } catch (erro) {
        console.error("[monitor] falha ao interpretar POST no router", {
          erro: String(erro?.message || erro),
        });
      }
    }

    return workerEntry.fetch(request, env, ctx);
  },
};
