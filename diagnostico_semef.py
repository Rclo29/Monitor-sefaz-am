import json
import time
from datetime import datetime

import requests

WORKER_URL = "https://monitor-sefaz-am.8dryc8ph6w.workers.dev"
SEMEF_HOME = "https://sigedweb.manaus.am.gov.br/protonweb/"
SEMEF_DETALHE = "https://sigedweb.manaus.am.gov.br/protonweb/detalhe.aspx"
PROCESSOS = [
    ("2024.18000.19012.0.008302", "7954846"),
    ("2026.18000.19951.0.024703", "11442112"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def limpar_payload(payload):
    if not isinstance(payload, dict):
        return payload
    copia = dict(payload)
    html = copia.pop("html", None)
    if html is not None:
        copia["html_tamanho"] = len(str(html))
    diagnostico = copia.get("diagnostico")
    if isinstance(diagnostico, list):
        novo = []
        for item in diagnostico:
            if isinstance(item, dict):
                x = dict(item)
                if "preview" in x:
                    x["preview"] = str(x["preview"])[:500]
                novo.append(x)
            else:
                novo.append(item)
        copia["diagnostico"] = novo
    return copia


def resumo_html(texto):
    texto = str(texto or "")
    return {
        "tamanho": len(texto),
        "tem_numero": None,
        "preview": " ".join(texto.replace("\r", " ").replace("\n", " ").split())[:500],
    }


resultado = {
    "gerado_em": datetime.now().astimezone().isoformat(),
    "worker": WORKER_URL,
    "testes_worker": [],
    "testes_diretos": [],
}

# 1) Testa o caminho atual via Cloudflare Worker.
for numero, protocolo in PROCESSOS:
    inicio = time.time()
    item = {"numero": numero, "cod_protocolo": protocolo}
    try:
        r = requests.post(
            WORKER_URL,
            headers={"Content-Type": "application/json"},
            json={
                "acao": "consultar_semef",
                "numero": numero,
                "cod_protocolo": protocolo,
            },
            timeout=45,
        )
        item["http_status"] = r.status_code
        item["duracao_segundos"] = round(time.time() - inicio, 2)
        try:
            item["resposta"] = limpar_payload(r.json())
        except Exception:
            item["resposta_texto"] = r.text[:1500]
    except Exception as e:
        item["duracao_segundos"] = round(time.time() - inicio, 2)
        item["erro_cliente"] = f"{type(e).__name__}: {e}"
    resultado["testes_worker"].append(item)

# 2) Testa acesso direto do runner do GitHub à SEMEF.
for numero, protocolo in PROCESSOS:
    inicio = time.time()
    item = {"numero": numero, "cod_protocolo": protocolo}
    url = f"{SEMEF_DETALHE}?origem=1&cod_protocolo={protocolo}"
    sessao = requests.Session()
    try:
        r = sessao.get(
            url,
            headers={**HEADERS, "Referer": SEMEF_HOME},
            timeout=(10, 35),
            allow_redirects=True,
        )
        item["http_status"] = r.status_code
        item["url_final"] = r.url
        item["duracao_segundos"] = round(time.time() - inicio, 2)
        item["tamanho"] = len(r.text)
        item["numero_encontrado"] = numero in r.text
        item["tem_semef"] = "semef" in r.text.lower()
        item["tem_situacao"] = "situa" in r.text.lower()
        item["preview"] = " ".join(r.text.replace("\r", " ").replace("\n", " ").split())[:700]
    except Exception as e:
        item["duracao_segundos"] = round(time.time() - inicio, 2)
        item["erro_cliente"] = f"{type(e).__name__}: {e}"
    finally:
        sessao.close()
    resultado["testes_diretos"].append(item)

with open("semef_diagnostico.json", "w", encoding="utf-8") as f:
    json.dump(resultado, f, ensure_ascii=False, indent=2)
    f.write("\n")

print(json.dumps(resultado, ensure_ascii=False, indent=2))
