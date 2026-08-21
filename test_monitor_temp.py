import json
import subprocess
import sys
import time

import requests
from bs4 import BeautifulSoup

WORKER_URL = "https://monitor-sefaz-am.8dryc8ph6w.workers.dev"
PROCESSOS_SEMEF = [
    ("2024.18000.19012.0.008302", "7954846"),
    ("2026.18000.19951.0.024703", "11442112"),
    ("2026.18000.19951.0.014382", "11037580"),
]

relatorio = {
    "proxy": [],
    "monitor": {},
    "ok": False,
}


def estrutura_html(html):
    soup = BeautifulSoup(html, "html.parser")
    linhas = []
    for tr in soup.find_all("tr")[:18]:
        celulas = [
            " ".join(td.stripped_strings)
            for td in tr.find_all(["td", "th"], recursive=False)
        ]
        if celulas:
            linhas.append(celulas)
    return linhas


def testar_proxy(numero, protocolo):
    ultimo = None
    for tentativa in range(1, 10):
        try:
            resposta = requests.post(
                WORKER_URL,
                json={
                    "acao": "consultar_semef",
                    "numero": numero,
                    "cod_protocolo": protocolo,
                },
                timeout=25,
            )
            ultimo = {
                "status": resposta.status_code,
                "body": resposta.text[:1500],
            }
            if resposta.status_code == 200:
                dados = resposta.json()
                html = dados.get("html", "")
                if dados.get("ok") is True and numero in html:
                    return {
                        "numero": numero,
                        "ok": True,
                        "status": 200,
                        "via": dados.get("via", ""),
                        "version": dados.get("version", ""),
                        "html_size": len(html),
                        "estrutura": estrutura_html(html),
                    }
        except Exception as erro:
            ultimo = {"erro": repr(erro)}
        time.sleep(5)

    return {
        "numero": numero,
        "ok": False,
        "ultimo": ultimo,
    }


try:
    for numero, protocolo in PROCESSOS_SEMEF:
        resultado = testar_proxy(numero, protocolo)
        relatorio["proxy"].append(resultado)

    proxy_ok = all(item.get("ok") for item in relatorio["proxy"])

    execucao = subprocess.run(
        [sys.executable, "monitor_runner.py"],
        text=True,
        capture_output=True,
        timeout=90,
    )

    relatorio["monitor"]["returncode"] = execucao.returncode
    relatorio["monitor"]["stdout"] = execucao.stdout[-8000:]
    relatorio["monitor"]["stderr"] = execucao.stderr[-4000:]

    with open("dados.json", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)

    processos = dados.get("processos", [])
    semef = [p for p in processos if p.get("origem") == "semef"]
    erros_semef = [p for p in semef if p.get("erro")]

    relatorio["monitor"].update({
        "total_processos": dados.get("total_processos"),
        "erros_gerais": dados.get("erros"),
        "tempo_excedido": dados.get("tempo_excedido"),
        "duracao_segundos": dados.get("duracao_segundos"),
        "semef_total": len(semef),
        "semef_erros": erros_semef,
        "semef_processos": [
            {
                "numero": p.get("numero"),
                "situacao": p.get("situacao"),
                "interessado": p.get("interessado"),
                "assunto": p.get("assunto"),
                "setor": p.get("setor"),
                "evento": p.get("evento"),
                "dataMovimentacao": p.get("dataMovimentacao"),
                "erro": p.get("erro"),
            }
            for p in semef
        ],
    })

    monitor_ok = (
        execucao.returncode == 0
        and dados.get("total_processos") == 29
        and len(processos) == 29
        and len(semef) == 3
        and not erros_semef
    )

    relatorio["ok"] = bool(proxy_ok and monitor_ok)

except Exception as erro:
    relatorio["erro_teste"] = repr(erro)

with open("test-results.json", "w", encoding="utf-8") as arquivo:
    json.dump(relatorio, arquivo, ensure_ascii=False, indent=2)
    arquivo.write("\n")

print(json.dumps(relatorio, ensure_ascii=False, indent=2))
