import workerEntry from "./worker-entry.js";

const ROUTER_VERSION = "router-v3-workflow-dispatch-fallback";
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

async function tentarWorkflowDispatch(token) {
  const resposta = await fetch(
    `${GITHUB_API}/actions/workflows/${encodeURIComponent(WORKFLOW_FILE)}/dispatches`,
    {
      method: "POST",
      headers: githubHeaders(token),
      body: JSON.stringify({ ref: BRANCH }),
    }
  );

  if (resposta.status === 204) {
    return {
      ok: true,
      metodo: "workflow_dispatch",
      statusGitHub: 204,
    };
  }

  return {
    ok: false,
    metodo: "workflow_dispatch",
    statusGitHub: resposta.status,
    detalhe: await resposta.text(),
  };
}

async function tentarRepositoryDispatch(token) {
  const resposta = await fetch(`${GITHUB_API}/dispatches`, {
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

  if (resposta.status === 204) {
    return {
      ok: true,
      metodo: "repository_dispatch",
      statusGitHub: 204,
    };
  }

  return {
    ok: false,
    metodo: "repository_dispatch",
    statusGitHub: resposta.status,
    detalhe: await resposta.text(),
  };
}

async function dispararAtualizacao(token) {
  if (!token) {
    return {
      ok: false,
      erro: "GITHUB_TOKEN não configurado no Worker.",
      router_version: ROUTER_VERSION,
    };
  }

  const tentativas = [];

  try {
    const workflow = await tentarWorkflowDispatch(token);
    tentativas.push(workflow);

    if (workflow.ok) {
      return {
        ok: true,
        mensagem: "Atualização iniciada.",
        metodo: workflow.metodo,
        router_version: ROUTER_VERSION,
        tentativas,
      };
    }
  } catch (erro) {
    tentativas.push({
      ok: false,
      metodo: "workflow_dispatch",
      erro: String(erro?.message || erro),
    });
  }

  try {
    const repository = await tentarRepositoryDispatch(token);
    tentativas.push(repository);

    if (repository.ok) {
      return {
        ok: true,
        mensagem: "Atualização iniciada.",
        metodo: repository.metodo,
        router_version: ROUTER_VERSION,
        tentativas,
      };
    }
  } catch (erro) {
    tentativas.push({
      ok: false,
      metodo: "repository_dispatch",
      erro: String(erro?.message || erro),
    });
  }

  return {
    ok: false,
    erro: "GitHub recusou o disparo do monitor.",
    router_version: ROUTER_VERSION,
    tentativas,
  };
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

        if (acao === "atualizar") {
          const resultado = await dispararAtualizacao(env.GITHUB_TOKEN);
          return json(resultado, resultado.ok ? 200 : 500);
        }
      } catch {
        // Qualquer outra ação continua no Worker principal.
      }
    }

    return workerEntry.fetch(request, env, ctx);
  },
};
