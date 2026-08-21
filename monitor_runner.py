import re
import threading
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import monitor

WORKER_URL = "https://monitor-sefaz-am.8dryc8ph6w.workers.dev"
WORKER_TIMEOUT = 15
WORKER_TENTATIVAS = 2
SEMEF_LOCK = threading.Lock()


def texto(valor):
    return monitor.texto_limpo(valor)


def chave(valor):
    return monitor.chave_texto(valor)


def valor_valido(valor):
    valor = texto(valor)
    return valor not in ("", "-", "–", "—")


def obter_html_worker(numero, cod_protocolo):
    ultimo_erro = None

    # O SIGED mostrou instabilidade quando recebeu três consultas simultâneas.
    # Somente as consultas SEMEF passam por este lock; a SEFAZ continua paralela.
    with SEMEF_LOCK:
        for tentativa in range(1, WORKER_TENTATIVAS + 1):
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
                if len(html) < 1000:
                    raise RuntimeError("O Worker retornou uma página SEMEF incompleta.")

                if numero not in html:
                    raise RuntimeError("O número do processo não foi encontrado na página SEMEF.")

                print(
                    "SEMEF via Cloudflare:",
                    numero,
                    payload.get("via", ""),
                    payload.get("version", ""),
                    len(html),
                )

                return html

            except Exception as erro:
                ultimo_erro = erro
                print(
                    f"Tentativa SEMEF {tentativa}/{WORKER_TENTATIVAS} falhou:",
                    numero,
                    str(erro),
                )
                if tentativa < WORKER_TENTATIVAS:
                    time.sleep(0.7)

    raise RuntimeError(
        "Falha ao consultar a SEMEF via Cloudflare: "
        + str(ultimo_erro or "erro desconhecido")
    )


def linhas_tabela(soup):
    linhas = []
    for tr in soup.find_all("tr"):
        celulas = [
            texto(td.get_text(" ", strip=True))
            for td in tr.find_all(["td", "th"], recursive=False)
        ]
        if celulas:
            linhas.append(celulas)
    return linhas


def extrair_cabecalho(linhas):
    resultado = {
        "numero": "",
        "data_processo": "",
        "situacao": "",
        "interessado": "",
        "assunto": "",
        "localizacao": "",
        "motivo": "",
    }

    mapas = {
        "processo": "numero",
        "data do processo": "data_processo",
        "situacao": "situacao",
        "interessado": "interessado",
        "assunto": "assunto",
        "localizacao atual": "localizacao",
        "localizacao": "localizacao",
        "motivo": "motivo",
    }

    for indice, linha in enumerate(linhas):
        chaves = [chave(c) for c in linha]

        # Padrão real do SIGED:
        # linha de rótulos: PROCESSO | DATA DO PROCESSO | SITUAÇÃO
        # linha seguinte:   número   | data             | situação
        if indice + 1 < len(linhas):
            seguinte = linhas[indice + 1]
            if len(seguinte) >= len(linha):
                for posicao, rotulo in enumerate(chaves):
                    campo = mapas.get(rotulo)
                    if campo and posicao < len(seguinte) and valor_valido(seguinte[posicao]):
                        if not resultado[campo]:
                            resultado[campo] = texto(seguinte[posicao])

        # Rótulos de uma coluna também têm o valor na linha seguinte.
        if len(linha) == 1 and indice + 1 < len(linhas):
            campo = mapas.get(chaves[0])
            seguinte = linhas[indice + 1]
            if campo and seguinte and valor_valido(seguinte[0]):
                if not resultado[campo]:
                    resultado[campo] = texto(seguinte[0])

    return resultado


def data_obj(valor):
    valor = texto(valor)
    if not valor_valido(valor):
        return None
    for formato in ("%d/%m/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(valor, formato)
        except ValueError:
            pass
    return None


def extrair_historico(linhas):
    inicio = None

    for indice, linha in enumerate(linhas):
        cab = [chave(c) for c in linha]
        if (
            "situacao" in cab
            and "data" in cab
            and "depto origem" in cab
            and "depto destino" in cab
            and "despacho movimentacao" in cab
        ):
            inicio = indice + 1
            break

    if inicio is None:
        return []

    historico = []
    for linha in linhas[inicio:]:
        if len(linha) < 7:
            continue

        situacao, data, origem, desfeito, recebido, destino = linha[:6]
        despacho = texto(" ".join(linha[6:]))

        datas = [
            (data_obj(data), texto(data)),
            (data_obj(desfeito), texto(desfeito)),
            (data_obj(recebido), texto(recebido)),
        ]
        datas_validas = [item for item in datas if item[0] is not None]
        if not datas_validas:
            continue

        melhor_data_obj, melhor_data = max(datas_validas, key=lambda item: item[0])

        setor = ""
        if valor_valido(destino):
            setor = texto(destino)
        elif valor_valido(origem):
            setor = texto(origem)

        historico.append(
            {
                "situacao": texto(situacao),
                "data": melhor_data,
                "data_obj": melhor_data_obj,
                "origem": texto(origem),
                "destino": texto(destino),
                "setor": setor,
                "despacho": despacho if valor_valido(despacho) else "",
            }
        )

    return historico


def consultar_semef_corrigido(cadastro):
    numero = cadastro["numero"]
    codigo = monitor.resolver_cod_protocolo(cadastro)
    html = obter_html_worker(numero, codigo)

    soup = BeautifulSoup(html, "html.parser")
    linhas = linhas_tabela(soup)
    cabecalho = extrair_cabecalho(linhas)

    numero_encontrado = texto(cabecalho.get("numero"))
    if numero_encontrado and numero not in numero_encontrado.replace(" ", ""):
        raise RuntimeError(
            "A SEMEF retornou um processo diferente: " + numero_encontrado
        )

    historico = extrair_historico(linhas)
    ultima = max(historico, key=lambda item: item["data_obj"]) if historico else {}

    situacao = texto(cabecalho.get("situacao")) or texto(ultima.get("situacao")) or "Não identificada"
    interessado = texto(cabecalho.get("interessado"))
    assunto = texto(cabecalho.get("assunto"))
    setor = texto(cabecalho.get("localizacao")) or texto(ultima.get("setor"))
    data_movimentacao = texto(ultima.get("data"))
    evento = texto(ultima.get("despacho"))

    if not evento:
        evento = texto(cabecalho.get("motivo"))
    if not evento and situacao:
        evento = situacao

    if not any([interessado, assunto, setor, data_movimentacao, evento]):
        raise RuntimeError("A SEMEF respondeu, mas nenhum dado do processo foi extraído.")

    return {
        "numero": numero,
        "origem": "semef",
        "cod_protocolo": codigo,
        "situacao": situacao,
        "interessado": interessado,
        "assunto": assunto,
        "setor": setor,
        "evento": evento,
        "dataMovimentacao": data_movimentacao,
        "erro": "",
        "consultado_em": monitor.agora_iso(),
    }


# Mantém todo o restante do monitor original intacto e troca somente
# a consulta SEMEF pela implementação validada acima.
monitor.consultar_semef = consultar_semef_corrigido


if __name__ == "__main__":
    raise SystemExit(monitor.main())
