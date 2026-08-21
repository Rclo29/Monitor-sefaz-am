import json
import requests

import monitor

WORKER_URL = "https://monitor-sefaz-am.8dryc8ph6w.workers.dev"
WORKER_TIMEOUT = 18

_obter_html_semef_original = monitor.obter_html_semef


def obter_html_semef_via_worker(cod_protocolo):
    numero = ""

    for processo, codigo in monitor.SEMEF_PROTOCOLS.items():
        if str(codigo) == str(cod_protocolo):
            numero = processo
            break

    if not numero:
        # Mantém compatibilidade com eventual processo SEMEF novo cujo
        # protocolo ainda não esteja no mapa estático.
        return _obter_html_semef_original(cod_protocolo)

    try:
        resposta = requests.post(
            WORKER_URL,
            headers={"Content-Type": "application/json"},
            json={
                "acao": "consultar_semef",
                "numero": numero,
                "cod_protocolo": str(cod_protocolo),
            },
            timeout=WORKER_TIMEOUT,
        )

        resposta.raise_for_status()
        payload = resposta.json()

        if not payload.get("ok"):
            raise RuntimeError(
                payload.get("erro")
                or "O Worker não confirmou a consulta SEMEF."
            )

        html = payload.get("html") or ""
        if not html:
            raise RuntimeError("O Worker retornou a página SEMEF vazia.")

        print(
            "SEMEF via Cloudflare:",
            numero,
            payload.get("via", ""),
            payload.get("version", ""),
        )

        return html.encode("utf-8")

    except Exception as erro:
        print(
            "Falha no proxy SEMEF; tentando consulta direta:",
            numero,
            str(erro),
        )
        return _obter_html_semef_original(cod_protocolo)


monitor.obter_html_semef = obter_html_semef_via_worker


if __name__ == "__main__":
    raise SystemExit(monitor.main())
