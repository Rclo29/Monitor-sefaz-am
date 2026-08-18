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

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders,
      });
    }

    if (request.method !== "POST") {
      return new Response(
        JSON.stringify({
          ok: false,
          erro: "Método não permitido",
        }),
        {
          status: 405,
          headers: {
            ...corsHeaders,
            "Content-Type": "application/json; charset=UTF-8",
          },
        }
      );
    }

    if (!env.GITHUB_TOKEN) {
      return new Response(
        JSON.stringify({
          ok: false,
          erro: "GITHUB_TOKEN não configurado",
        }),
        {
          status: 500,
          headers: {
            ...corsHeaders,
            "Content-Type": "application/json; charset=UTF-8",
          },
        }
      );
    }

    const owner = "Rclo29";
    const repo = "Monitor-sefaz-am";
    const workflow = "monitor.yml";

    const githubUrl =
      `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;

    try {
      const resposta = await fetch(githubUrl, {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "monitor-sefaz-am-worker",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ref: "main",
        }),
      });

      if (resposta.status === 204) {
        return new Response(
          JSON.stringify({
            ok: true,
            mensagem: "Atualização dos processos iniciada.",
          }),
          {
            status: 200,
            headers: {
              ...corsHeaders,
              "Content-Type": "application/json; charset=UTF-8",
              "Cache-Control": "no-store",
            },
          }
        );
      }

      const detalhe = await resposta.text();

      return new Response(
        JSON.stringify({
          ok: false,
          erro: "GitHub recusou o disparo do workflow.",
          statusGitHub: resposta.status,
          detalhe: detalhe,
        }),
        {
          status: 502,
          headers: {
            ...corsHeaders,
            "Content-Type": "application/json; charset=UTF-8",
            "Cache-Control": "no-store",
          },
        }
      );
    } catch (erro) {
      return new Response(
        JSON.stringify({
          ok: false,
          erro: "Falha ao comunicar com o GitHub.",
          detalhe: String(erro),
        }),
        {
          status: 500,
          headers: {
            ...corsHeaders,
            "Content-Type": "application/json; charset=UTF-8",
            "Cache-Control": "no-store",
          },
        }
      );
    }
  },
};
