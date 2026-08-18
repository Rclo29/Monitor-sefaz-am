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
ARQUIVO_PROCESSOS = "processos.json"

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
# DATA / HORA
# ============================================================

def agora_manaus():
    return datetime.now(
        ZoneInfo("America/Manaus")
    )


def agora_iso():
    return agora_manaus().isoformat(
        timespec="seconds"
    )


# ============================================================
# UTILIDADES
# ============================================================

def texto_limpo(valor):
    if valor is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(valor)
    ).strip()


def url_processo(numero):
    return BASE_URL + quote(
        numero,
        safe="/"
    )


# ============================================================
# processos.json
# ============================================================

def carregar_processos():

    if not os.path.exists(
        ARQUIVO_PROCESSOS
    ):
        raise FileNotFoundError(
            "Arquivo processos.json não encontrado."
        )

    with open(
        ARQUIVO_PROCESSOS,
        "r",
        encoding="utf-8"
    ) as arquivo:
        dados = json.load(arquivo)

    if not isinstance(dados, dict):
        raise ValueError(
            "processos.json possui formato inválido."
        )

    lista = dados.get(
        "processos",
        []
    )

    if not isinstance(lista, list):
        raise ValueError(
            'O campo "processos" precisa ser uma lista.'
        )

    processos = []
    vistos = set()

    for numero in lista:

        numero = texto_limpo(numero)

        if not numero:
            continue

        if numero in vistos:
            print(
                "Aviso: processo duplicado ignorado:",
                numero
            )
            continue

        vistos.add(numero)
        processos.append(numero)

    if not processos:
        raise ValueError(
            "Nenhum processo cadastrado em processos.json."
        )

    return processos


# ============================================================
# dados.json
# ============================================================

def estrutura_vazia():
    return {
        "ultima_verificacao": None,
        "timezone": "America/Manaus",
        "total_processos": 0,
        "erros": 0,
        "novos_alertas": 0,
        "processos": [],
        "alertas": [],
    }


def carregar_dados():

    if not os.path.exists(
        ARQUIVO_DADOS
    ):
        return estrutura_vazia()

    try:

        with open(
            ARQUIVO_DADOS,
            "r",
            encoding="utf-8"
        ) as arquivo:

            dados = json.load(
                arquivo
            )

        if not isinstance(
            dados,
            dict
        ):
            return estrutura_vazia()

        dados.setdefault(
            "processos",
            []
        )

        dados.setdefault(
            "alertas",
            []
        )

        return dados

    except Exception as erro:

        print(
            "Aviso ao ler dados.json:",
            erro
        )

        return estrutura_vazia()


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

    url = url_processo(numero)

    print(
        f"Consultando: {numero}"
    )

    print(
        f"URL: {url}"
    )

    resposta = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True
    )

    print(
        f"HTTP: {resposta.status_code}"
    )

    print(
        f"URL final: {resposta.url}"
    )

    resposta.raise_for_status()

    if resposta.encoding is None:
        resposta.encoding = (
            resposta.apparent_encoding
            or "utf-8"
        )

    return (
        resposta.text,
        resposta.url
    )


# ============================================================
# CABEÇALHO
# ============================================================

def extrair_cabecalho(soup):

    texto = texto_limpo(
        soup.get_text(
            " ",
            strip=True
        )
    )

    situacao = ""
    assunto = ""
    interessado = ""

    match = re.search(
        r"Situação\s*:\s*"
        r"(.*?)"
        r"(?=\s+Assunto\s*:|"
        r"\s+Órgão/Entidade\s*:|"
        r"\s+Interessado\s*:|$)",
        texto,
        flags=re.IGNORECASE
    )

    if match:
        situacao = texto_limpo(
            match.group(1)
        )

    match = re.search(
        r"Assunto\s*:\s*"
        r"(.*?)"
        r"(?=\s+Órgão/Entidade\s*:|"
        r"\s+CNPJ\s*:|"
        r"\s+Interessado\s*:|$)",
        texto,
        flags=re.IGNORECASE
    )

    if match:
        assunto = texto_limpo(
            match.group(1)
        )

    match = re.search(
        r"Interessado\s*:\s*"
        r"(.*?)"
        r"(?=\s+Processo disponível|"
        r"\s+Nova Pesquisa|"
        r"\s+Data\s+Setor\s+Evento|$)",
        texto,
        flags=re.IGNORECASE
    )

    if match:
        interessado = texto_limpo(
            match.group(1)
        )

    return {
        "situacao": situacao,
        "assunto": assunto,
        "interessado": interessado,
    }


# ============================================================
# MOVIMENTAÇÕES
# ============================================================

def encontrar_tabela_movimentacoes(soup):

    for tabela in soup.find_all(
        "table"
    ):

        texto = texto_limpo(
            tabela.get_text(
                " ",
                strip=True
            )
        ).lower()

        if (
            "data" in texto
            and "setor" in texto
            and "evento" in texto
        ):
            return tabela

    return None


def extrair_movimentacoes(soup):

    tabela = encontrar_tabela_movimentacoes(
        soup
    )

    movimentacoes = []

    if tabela is None:

        print(
            "Aviso: tabela de movimentações "
            "não encontrada."
        )

        return movimentacoes

    for linha in tabela.find_all(
        "tr"
    ):

        celulas = linha.find_all(
            ["td", "th"]
        )

        valores = [
            texto_limpo(
                celula.get_text(
                    " ",
                    strip=True
                )
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

        evento = texto_limpo(
            " ".join(
                valores[2:]
            )
        )

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
# CONSULTAR PROCESSO
# ============================================================

def consultar_processo(numero):

    html, url_final = baixar_pagina(
        numero
    )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    cabecalho = extrair_cabecalho(
        soup
    )

    movimentacoes = extrair_movimentacoes(
        soup
    )

    if movimentacoes:
        ultima = movimentacoes[0]
    else:
        ultima = {
            "data": "",
            "setor": "",
            "evento": "",
        }

    return {
        "numero": numero,
        "situacao": (
            cabecalho["situacao"]
            or "Não identificada"
        ),
        "interessado":
            cabecalho["interessado"],
        "assunto":
            cabecalho["assunto"],
        "dataMovimentacao":
            ultima["data"],
        "setor":
            ultima["setor"],
        "evento":
            ultima["evento"],
        "url":
            url_final,
        "consultado_em":
            agora_iso(),
        "erro":
            None,
    }


# ============================================================
# COMPARAÇÃO
# ============================================================

def assinatura_movimentacao(processo):

    if not processo:
        return ""

    data = texto_limpo(
        processo.get(
            "dataMovimentacao",
            ""
        )
    )

    setor = texto_limpo(
        processo.get(
            "setor",
            ""
        )
    )

    evento = texto_limpo(
        processo.get(
            "evento",
            ""
        )
    )

    if not (
        data
        or setor
        or evento
    ):
        return ""

    return "|".join([
        data,
        setor,
        evento,
    ])


def localizar_anterior(
    dados,
    numero
):

    for processo in dados.get(
        "processos",
        []
    ):

        if (
            processo.get("numero")
            == numero
        ):
            return processo

    return None


def anterior_e_valido(anterior):

    if not anterior:
        return False

    if anterior.get(
        "erro"
    ):
        return False

    situacao = texto_limpo(
        anterior.get(
            "situacao",
            ""
        )
    ).lower()

    if "erro" in situacao:
        return False

    assinatura = assinatura_movimentacao(
        anterior
    )

    if not assinatura:
        return False

    return True


# ============================================================
# ALERTAS
# ============================================================

def criar_alerta(
    numero,
    novo,
    anterior
):

    return {
        "numero":
            numero,

        "data":
            agora_iso(),

        "mensagem":
            (
                "Nova movimentação: "
                + (
                    novo.get(
                        "evento"
                    )
                    or
                    "movimentação atualizada"
                )
            ),

        "movimentacao_anterior":
            assinatura_movimentacao(
                anterior
            ),

        "movimentacao_atual":
            assinatura_movimentacao(
                novo
            ),

        "data_movimentacao":
            novo.get(
                "dataMovimentacao",
                ""
            ),

        "setor":
            novo.get(
                "setor",
                ""
            ),

        "evento":
            novo.get(
                "evento",
                ""
            ),
    }


def alerta_ja_existe(
    alertas,
    numero,
    assinatura
):

    for alerta in alertas:

        if (
            alerta.get("numero")
            == numero
            and
            alerta.get(
                "movimentacao_atual"
            )
            == assinatura
        ):
            return True

    return False


# ============================================================
# EXECUÇÃO
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "MONITOR SEFAZ-AM"
    )

    print(
        "Início:",
        agora_manaus().strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    )

    print(
        "=" * 60
    )


    # --------------------------------------------------------
    # CARREGA A LISTA DINÂMICA
    # --------------------------------------------------------

    try:

        processos_monitorados = (
            carregar_processos()
        )

    except Exception as erro:

        print(
            "ERRO ao carregar processos.json:",
            erro
        )

        return 1


    print(
        "Processos cadastrados:",
        len(
            processos_monitorados
        )
    )


    dados_anteriores = carregar_dados()

    novos_processos = []


    # Mantém alertas somente dos processos
    # que continuam cadastrados.

    processos_ativos = set(
        processos_monitorados
    )

    novos_alertas = [

        alerta

        for alerta
        in dados_anteriores.get(
            "alertas",
            []
        )

        if alerta.get(
            "numero"
        )
        in processos_ativos

    ]


    erros = 0

    novos_alertas_detectados = 0


    # --------------------------------------------------------
    # CONSULTA TODOS OS PROCESSOS DO processos.json
    # --------------------------------------------------------

    for numero in processos_monitorados:

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
                "Interessado:",
                atual["interessado"]
            )

            print(
                "Assunto:",
                atual["assunto"]
            )

            print(
                "Última movimentação:",
                atual["dataMovimentacao"],
                atual["setor"],
                atual["evento"]
            )


            if anterior_e_valido(
                anterior
            ):

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
                    and
                    assinatura_atual
                    != assinatura_anterior
                ):

                    if not alerta_ja_existe(
                        novos_alertas,
                        numero,
                        assinatura_atual
                    ):

                        alerta = criar_alerta(
                            numero,
                            atual,
                            anterior
                        )

                        novos_alertas.insert(
                            0,
                            alerta
                        )

                        novos_alertas_detectados += 1

                        print(
                            "NOVA MOVIMENTAÇÃO "
                            "DETECTADA!"
                        )

                    else:

                        print(
                            "Movimentação já possui "
                            "alerta registrado."
                        )

                else:

                    print(
                        "Nenhuma nova movimentação."
                    )

            else:

                print(
                    "Sem consulta anterior válida "
                    "para comparação."
                )

                print(
                    "Estado atual salvo como "
                    "referência inicial."
                )


            novos_processos.append(
                atual
            )


        except Exception as erro:

            erros += 1

            print(
                "ERRO ao consultar "
                f"{numero}: {erro}"
            )

            if anterior:

                copia = dict(
                    anterior
                )

                copia[
                    "erro"
                ] = str(
                    erro
                )

                copia[
                    "consultado_em"
                ] = agora_iso()

                novos_processos.append(
                    copia
                )

            else:

                novos_processos.append({
                    "numero":
                        numero,

                    "situacao":
                        "Erro na consulta",

                    "interessado":
                        "",

                    "assunto":
                        "",

                    "dataMovimentacao":
                        "",

                    "setor":
                        "",

                    "evento":
                        "",

                    "url":
                        url_processo(
                            numero
                        ),

                    "consultado_em":
                        agora_iso(),

                    "erro":
                        str(
                            erro
                        ),
                })


    # Limita histórico de alertas.

    novos_alertas = (
        novos_alertas[:100]
    )


    saida = {

        "ultima_verificacao":
            agora_iso(),

        "timezone":
            "America/Manaus",

        "total_processos":
            len(
                novos_processos
            ),

        "erros":
            erros,

        "novos_alertas":
            novos_alertas_detectados,

        "processos":
            novos_processos,

        "alertas":
            novos_alertas,
    }


    salvar_dados(
        saida
    )


    print(
        "=" * 60
    )

    print(
        "dados.json atualizado."
    )

    print(
        "Processos:",
        len(
            novos_processos
        )
    )

    print(
        "Erros:",
        erros
    )

    print(
        "Novos alertas:",
        novos_alertas_detectados
    )

    print(
        "=" * 60
    )

    return 0


if __name__ == "__main__":

    sys.exit(
        main()
    )
