import workerEntry from "./worker-entry.js";

const ROUTER_VERSION = "router-v5-github-actions-status";
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
  return valor.length > 1200 ? `${valor.slice(0, 1200)}…` : valor;
}

async function githubJSON(url, token) {
  const resposta = await fetch(url, {
    method: "GET",
    headers: githubHeaders(token),
  });

  const texto = await resposta.text();
  let dados = null;

  try {
    dados = texto ? JSON.parse(texto) : null;
  } catch {
    dados = texto;
  }

  return {
    ok: resposta.ok,
    status: resposta.status,
    dados,
    github_request_id: resposta.headers.get("x-github-request-id") || "",
  };
}

async function consultarEstadoGitHubActions(token) {
  if (!token) {
    return {
      ok: false,
      erro: "GITHUB_TOKEN não configurado no Worker.",
      router_version: ROUTER_VERSION,
    };
  }

  const workflow = await githubJSON(
    `${GITHUB_API}/actions/workflows/${encodeURIComponent(WORKFLOW_FILE)}`,
    token
  );

  const runs = await githubJSON(
    `${GITHUB_API}/actions/workflows/${encodeURIComponent(WORKFLOW_FILE)}/runs?per_page=5`,
    token
  );

  return {
    ok: workflow.ok,
    router_version: ROUTER_VERSION,
    workflow_http_status: workflow.status,
    workflow: workflow.ok
      ? {
          id: workflow.dados?.id,
          name: workflow.dados?.name,
          path: workflow.dados?.path,
          state: workflow.dados?.state,
          created_at: workflow.dados?.created_at,
          updated_at: workflow.dados?.updated_at,
          html_url: workflow.dados?.html_url,
        }
      : workflow.dados,
    runs_http_status: runs.status,
    total_count: runs.dados?.total_count ?? null,
    runs: Array.isArray(runs.dados?.workflow_runs)
      ? runs.dados.workflow_runs.map((run) => ({
          id: run.id,
          event: run.event,
          status: run.status,
          conclusion: run.conclusion,
          created_at: run.created_at,
          updated_at: run.updated_at,
          run_started_at: run.run_started_at,
          head_sha: run.head_sha,
          html_url: run.html_url,
        }))
      : [],
  };
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

  return resposta.status === 204
    ? { ok: true, metodo: "workflow_dispatch", statusGitHub: 204, duracao_ms }
    : {
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

  return resposta.status === 204
    ? { ok: true, metodo: "repository_dispatch", statusGitHub: 204, duracao_ms }
    : {
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

    if (request.method === "GET" && url.pathname === "/github-actions-status") {
      try {
        const resultado = await consultarEstadoGitHubActions(env.GITHUB_TOKEN);
        return json(resultado, resultado.ok ? 200 : 500);
      } catch (erro) {
        return json(
          {
            ok: false,
            erro: String(erro?.message || erro),
            router_version: ROUTER_VERSION,
          },
          500
        );
      }
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
