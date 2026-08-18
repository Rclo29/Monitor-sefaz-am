import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURAÇÃO
# ============================================================

ARQUIVO_DADOS = "dados.json"

PROCESSOS = [
    "01.01.028101.030037/2026-43",
    "01.01.013102.003068/2026-44",
]

BASE_URL = "https://online.sefaz.am.gov.br/processo/"

TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


# ============================================================
# UTILIDADES
# ============================================================

def agora_manaus():
    return datetime.now(ZoneInfo("America/Manaus"))


def agora_iso():
    return agora_manaus().isoformat(timespec="seconds")


def texto_limpo(valor):
    if valor is None:
        return ""

    return re.sub(r"\s+", " ", str(valor)).strip()


def carregar_dados():
    if not os.path.exists(ARQUIVO_DADOS):
        return {
            "ultima_verificacao": None,
            "processos": [],
            "alertas": [],
        }

    try:
        with open(
            ARQUIVO_DADOS,
            "r",
            encoding="utf-8"
        ) as arquivo:
            dados = json.load(arquivo)

        if not isinstance(dados, dict):
            raise ValueError("Formato inválido")

        dados.setdefault("ultima_verificacao", None)
        dados.setdefault("processos", [])
        dados.setdefault("alertas", [])

        return dados

    except Exception as erro:
        print(
            f"Aviso: não foi possível ler "
            f"{ARQUIVO_DADOS}: {erro}"
        )

        return {
            "ultima_verificacao": None,
            "processos": [],
            "alertas": [],
        }


def salvar_dados(dados):
    with open(
        ARQUIVO_DADOS,
        "w",
        encoding="utf-8"
    ) as arquivo:
        json.dump(
            dados,
            arquivo,
            ensure_ascii=False,
            indent=2
        )

        arquivo.write("\n")


# ============================================================
# CONSULTA À SEFAZ
# ============================================================

def baixar_pagina(numero):
    url = BASE_URL + quote(numero, safe="")

    print(f"Consultando: {numero}")
    print(f"URL: {url}")

    resposta = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True
    )

    print(f"HTTP: {resposta.status_code}")

    resposta.raise_for_status()

    if not resposta.encoding:
        resposta.encoding = "utf-8"

    return resposta.text, resposta.url


# ============================================================
# LEITURA DOS CAMPOS
# ============================================================

def extrair_por_rotulo(texto_pagina, rotulo):
    padrao = (
        re.escape(rotulo)
        + r"\s*:\s*(.+?)(?="
        + r"\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-zÁÉÍÓÚ"
        + r"áéíóúÂÊÔâêôÃÕãõÇç/() -]{1,40}\s*:|$)"
    )

    resultado = re.search(
        padrao,
        texto_pagina,
        flags=re.IGNORECASE
    )

    if resultado:
        return texto_limpo(resultado.group(1))

    return ""


def extrair_cabecalho(soup):
    texto = texto_limpo(
        soup.get_text(" ", strip=True)
    )

    situacao = ""
    assunto = ""
    interessado = ""

    # --------------------------------------------------------
    # Tenta encontrar os campos diretamente pelas células
    # --------------------------------------------------------

    elementos = soup.find_all(
        ["td", "th", "div", "span"]
    )

    for elemento in elementos:
        conteudo = texto_limpo(
            elemento.get_text(" ", strip=True)
        )

        conteudo_lower = conteudo.lower()

        if (
            not situacao
            and conteudo_lower.startswith("situação")
        ):
            situacao = texto_limpo(
                re.sub(
                    r"^situação\s*:\s*",
                    "",
                    conteudo,
                    flags=re.IGNORECASE
                )
            )

        if (
            not assunto
            and conteudo_lower.startswith("assunto")
        ):
            assunto = texto_limpo(
                re.sub(
                    r"^assunto\s*:\s*",
                    "",
                    conteudo,
                    flags=re.IGNORECASE
                )
            )

        if (
            not interessado
            and conteudo_lower.startswith("interessado")
        ):
            interessado = texto_limpo(
                re.sub(
                    r"^interessado\s*:\s*",
                    "",
                    conteudo,
                    flags=re.IGNORECASE
                )
            )

    # --------------------------------------------------------
    # Fallback pelo texto completo
    # --------------------------------------------------------

    if not situacao:
        match = re.search(
            r"Situação\s*:\s*(.*?)(?=\s+Assunto\s*:|\s+Órgão/Entidade\s*:|$)",
            texto,
            flags=re.IGNORECASE
        )

        if match:
            situacao = texto_limpo(match.group(1))

    if not assunto:
        match = re.search(
            r"Assunto\s*:\s*(.*?)(?=\s+Órgão/Entidade\s*:|\s+CNPJ\s*:|$)",
            texto,
            flags=re.IGNORECASE
        )

        if match:
            assunto = texto_limpo(match.group(1))

    if not interessado:
        match = re.search(
            r"Interessado\s*:\s*(.*?)(?=\s+Processo disponível|\s+Nova Pesquisa|$)",
            texto,
            flags=re.IGNORECASE
        )

        if match:
            interessado = texto_limpo(match.group(1))

    return {
        "situacao": situacao,
        "assunto": assunto,
        "interessado": interessado,
    }


# ============================================================
# MOVIMENTAÇÕES
# ============================================================

def encontrar_tabela_movimentacoes(soup):
    tabelas = soup.find_all("table")

    for tabela in tabelas:
        texto = texto_limpo(
            tabela.get_text(" ", strip=True)
        ).lower()

        if (
            "data" in texto
            and "setor" in texto
            and "evento" in texto
        ):
            return tabela

    return None


def extrair_movimentacoes(soup):
    tabela = encontrar_tabela_movimentacoes(soup)

    movimentacoes = []

    if tabela is None:
        return movimentacoes

    linhas = tabela.find_all("tr")

    for linha in linhas:
        celulas = linha.find_all(["td", "th"])

        valores = [
            texto_limpo(
                celula.get_text(" ", strip=True)
            )
            for celula in celulas
        ]

        if len(valores) < 3:
            continue

        if (
            valores[0].lower() == "data"
            and valores[1].lower() == "setor"
        ):
            continue

        data = valores[0]
        setor = valores[1]
        evento = " ".join(valores[2:])

        if not re.match(
            r"^\d{2}/\d{2}/\d{4}$",
            data
        ):
            continue

        movimentacoes.append({
            "data": data,
            "setor": setor,
            "evento": evento,
        })

    return movimentacoes


# ============================================================
# PROCESSAR PROCESSO
# ============================================================

def consultar_processo(numero):
    html, url_final = baixar_pagina(numero)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    cabecalho = extrair_cabecalho(soup)

    movimentacoes = extrair_movimentacoes(soup)

    if movimentacoes:
        ultima = movimentacoes[0]
    else:
        ultima = {
            "data": "",
            "setor": "",
            "evento": "",
        }

    resultado = {
        "numero": numero,
        "situacao": (
            cabecalho["situacao"]
            or "Não identificada"
        ),
        "interessado": cabecalho["interessado"],
        "assunto": cabecalho["assunto"],
        "dataMovimentacao": ultima["data"],
        "setor": ultima["setor"],
        "evento": ultima["evento"],
        "url": url_final,
        "consultado_em": agora_iso(),
        "erro": None,
    }

    return resultado


# ============================================================
# COMPARAÇÃO
# ============================================================

def assinatura_movimentacao(processo):
    return "|".join([
        texto_limpo(
            processo.get("dataMovimentacao", "")
        ),
        texto_limpo(
            processo.get("setor", "")
        ),
        texto_limpo(
            processo.get("evento", "")
        ),
    ])


def localizar_anterior(dados, numero):
    for processo in dados.get(
        "processos",
        []
    ):
        if processo.get("numero") == numero:
            return processo

    return None


def criar_alerta(
    numero,
    processo_novo,
    processo_anterior
):
    return {
        "numero": numero,
        "data": agora_iso(),
        "mensagem": (
            "Nova movimentação: "
            + (
                processo_novo.get("evento")
                or "movimentação atualizada"
            )
        ),
        "movimentacao_anterior": (
            assinatura_movimentacao(
                processo_anterior
            )
            if processo_anterior
            else None
        ),
        "movimentacao_atual": (
            assinatura_movimentacao(
                processo_novo
            )
        ),
    }


# ============================================================
# EXECUÇÃO
# ============================================================

def main():
    print("=" * 60)
    print("MONITOR SEFAZ-AM")
    print(
        "Início:",
        agora_manaus().strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    )
    print("=" * 60)

    dados_anteriores = carregar_dados()

    novos_processos = []
    novos_alertas = list(
        dados_anteriores.get(
            "alertas",
            []
        )
    )

    erros = 0

    for numero in PROCESSOS:
        anterior = localizar_anterior(
            dados_anteriores,
            numero
        )

        try:
            atual = consultar_processo(
                numero
            )

            print(
                "Situação:",
                atual["situacao"]
            )

            print(
                "Última movimentação:",
                atual["dataMovimentacao"],
                atual["setor"],
                atual["evento"]
            )

            # Só gera alerta se já existia uma
            # consulta anterior.
            if anterior:
                assinatura_anterior = (
                    assinatura_movimentacao(
                        anterior
                    )
                )

                assinatura_atual = (
                    assinatura_movimentacao(
                        atual
                    )
                )

                if (
                    assinatura_atual
                    and assinatura_atual
                    != assinatura_anterior
                ):
                    novos_alertas.insert(
                        0,
                        criar_alerta(
                            numero,
                            atual,
                            anterior
                        )
                    )

                    print(
                        "NOVA MOVIMENTAÇÃO DETECTADA!"
                    )

            novos_processos.append(
                atual
            )

        except Exception as erro:
            erros += 1

            print(
                f"ERRO ao consultar {numero}: "
                f"{erro}"
            )

            # Mantém os dados anteriores caso
            # uma consulta falhe temporariamente.
            if anterior:
                copia = dict(anterior)
                copia["erro"] = str(erro)
                copia["consultado_em"] = agora_iso()

                novos_processos.append(
                    copia
                )

            else:
                novos_processos.append({
                    "numero": numero,
                    "situacao": "Erro na consulta",
                    "interessado": "",
                    "assunto": "",
                    "dataMovimentacao": "",
                    "setor": "",
                    "evento": "",
                    "url": (
                        BASE_URL
                        + quote(
                            numero,
                            safe=""
                        )
                    ),
                    "consultado_em": agora_iso(),
                    "erro": str(erro),
                })

    # Mantém no máximo os 100 alertas
    novos_alertas = novos_alertas[:100]

    saida = {
        "ultima_verificacao": agora_iso(),
        "timezone": "America/Manaus",
        "total_processos": len(
            novos_processos
        ),
        "erros": erros,
        "processos": novos_processos,
        "alertas": novos_alertas,
    }

    salvar_dados(saida)

    print("=" * 60)
    print(
        f"{ARQUIVO_DADOS} atualizado."
    )
    print(
        f"Processos: {len(novos_processos)}"
    )
    print(
        f"Erros: {erros}"
    )
    print("=" * 60)

    # Não encerra o workflow por erro de apenas
    # um processo. Assim os demais continuam
    # sendo monitorados.
    return 0


if __name__ == "__main__":
    sys.exit(main())
