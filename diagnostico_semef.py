import json
import time
from datetime import datetime

import requests

WORKER_URL = "https://monitor-sefaz-am.8dryc8ph6w.workers.dev"
PROCESSOS = [
    ("2024.18000.19012.0.008302", "7954846"),
    ("2026.18000.19951.0.024703", "11442112"),
]


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


resultado = {
    "gerado_em": datetime.now().astimezone().isoformat(),
    "worker": WORKER_URL,
    "testes": [],
}

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
    resultado["testes"].append(item)

with open("semef_diagnostico.json", "w", encoding="utf-8") as f:
    json.dump(resultado, f, ensure_ascii=False, indent=2)
    f.write("\n")

print(json.dumps(resultado, ensure_ascii=False, indent=2))
