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

SEFAZ_BASE_URL = (
    "https://online.sefaz.am.gov.br/processo/"
)

SEMEF_BASE_URL = (
    "https://sigedweb.manaus.am.gov.br/"
    "protonweb/detalhe.aspx"
)

TIMEOUT = 30


HEADERS = {

    "User-Agent": (
        "Mozilla/5.0 "
        "(iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) "
        "Version/18.0 "
        "Mobile/15E148 "
        "Safari/604.1"
    ),

    "Accept": (
        "text/html,"
        "application/xhtml+xml,"
        "application/xml;"
        "q=0.9,*/*;q=0.8"
    ),

    "Accept-Language":
        "pt-BR,pt;q=0.9,en;q=0.8",

}


# ============================================================
# PROTOCOLOS SEMEF JÁ CONHECIDOS
# ============================================================

SEMEF_PROTOCOLS = {

    "2024.18000.19012.0.008302":
        "7954846",

    "2026.18000.19951.0.024703":
        "11442112",

}


# ============================================================
# DATA / HORA
# ============================================================

def agora_manaus():

    return datetime.now(
        ZoneInfo(
            "America/Manaus"
        )
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


def normalizar_origem(valor):

    origem = texto_limpo(
        valor
    ).lower()

    if origem in (
        "semef",
        "siged"
    ):
        return "semef"

    return "sefaz"


def detectar_origem(numero):

    numero = texto_limpo(
        numero
    )

    if re.match(
        r"^\d{4}\."
        r"\d{5}\."
        r"\d{5}\."
        r"\d\."
        r"\d{6}$",
        numero
    ):
        return "semef"

    return "sefaz"


def url_sefaz(numero):

    return (
        SEFAZ_BASE_URL
        +
        quote(
            numero,
            safe="/"
        )
    )


def url_semef(cod_protocolo):

    return (
        SEMEF_BASE_URL
        +
        "?origem=1"
        +
        "&cod_protocolo="
        +
        quote(
            str(cod_protocolo)
        )
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

        dados = json.load(
            arquivo
        )


    if not isinstance(
        dados,
        dict
    ):

        raise ValueError(
            "processos.json possui formato inválido."
        )


    lista = dados.get(
        "processos",
        []
    )


    if not isinstance(
        lista,
        list
    ):

        raise ValueError(
            'O campo "processos" precisa ser uma lista.'
        )


    processos = []

    vistos = set()


    for item in lista:


        # ----------------------------------------------------
        # FORMATO ANTIGO
        # "01.01...."
        # ----------------------------------------------------

        if isinstance(
            item,
            str
        ):

            numero = texto_limpo(
                item
            )

            origem = detectar_origem(
                numero
            )

            cod_protocolo = ""

            if origem == "semef":

                cod_protocolo = (
                    SEMEF_PROTOCOLS.get(
                        numero,
                        ""
                    )
                )


        # ----------------------------------------------------
        # NOVO FORMATO
        # {
        #   "numero": "...",
        #   "origem": "semef",
        #   "cod_protocolo": "..."
        # }
        # ----------------------------------------------------

        elif isinstance(
            item,
            dict
        ):

            numero = texto_limpo(
                item.get(
                    "numero",
                    item.get(
                        "processo",
                        ""
                    )
                )
            )

            origem = normalizar_origem(
                item.get(
                    "origem",
                    detectar_origem(
                        numero
                    )
                )
            )

            cod_protocolo = texto_limpo(

                item.get(
                    "cod_protocolo",
                    item.get(
                        "codProtocolo",
                        ""
                    )
                )

            )

            if (
                origem == "semef"
                and
                not cod_protocolo
            ):

                cod_protocolo = (
                    SEMEF_PROTOCOLS.get(
                        numero,
                        ""
                    )
                )


        else:

            continue


        if not numero:
            continue


        if numero in vistos:

            print(
                "Aviso: processo duplicado ignorado:",
                numero
            )

            continue


        vistos.add(
            numero
        )


        processos.append({

            "numero":
                numero,

            "origem":
                origem,

            "cod_protocolo":
                cod_protocolo,

        })


    if not processos:

        raise ValueError(
            "Nenhum processo cadastrado "
            "em processos.json."
        )


    return processos


# ============================================================
# dados.json
# ============================================================

def estrutura_vazia():

    return {

        "ultima_verificacao":
            None,

        "timezone":
            "America/Manaus",

        "total_processos":
            0,

        "erros":
            0,

        "novos_alertas":
            0,

        "processos":
            [],

        "alertas":
            [],

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

        arquivo.write(
            "\n"
        )


# ============================================================
# DOWNLOAD GENÉRICO
# ============================================================

def baixar_url(
    url,
    descricao
):

    print(
        f"Consultando {descricao}"
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
        "HTTP:",
        resposta.status_code
    )

    print(
        "URL final:",
        resposta.url
    )


    resposta.raise_for_status()


    if resposta.encoding is None:

        resposta.encoding = (
            resposta.apparent_encoding
            or
            "utf-8"
        )


    return (
        resposta.text,
        resposta.url
    )


# ============================================================
# SEFAZ
# ============================================================

def baixar_pagina_sefaz(
    numero
):

    return baixar_url(

        url_sefaz(
            numero
        ),

        f"SEFAZ - {numero}"

    )


def extrair_cabecalho_sefaz(
    soup
):

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

        "situacao":
            situacao,

        "assunto":
            assunto,

        "interessado":
            interessado,

    }


def encontrar_tabela_movimentacoes_sefaz(
    soup
):

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
            and
            "setor" in texto
            and
            "evento" in texto
        ):

            return tabela


    return None


def extrair_movimentacoes_sefaz(
    soup
):

    tabela = (
        encontrar_tabela_movimentacoes_sefaz(
            soup
        )
    )


    movimentacoes = []


    if tabela is None:

        print(
            "Aviso: tabela de movimentações "
            "SEFAZ não encontrada."
        )

        return movimentacoes


    for linha in tabela.find_all(
        "tr"
    ):

        celulas = linha.find_all(
            [
                "td",
                "th"
            ]
        )


        valores = [

            texto_limpo(

                celula.get_text(
                    " ",
                    strip=True
                )

            )

            for celula
            in celulas

        ]


        if len(
            valores
        ) < 3:

            continue


        if (
            valores[0].lower()
            == "data"
            and
            valores[1].lower()
            == "setor"
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

            "data":
                data,

            "setor":
                setor,

            "evento":
                evento,

        })


    return movimentacoes


def consultar_sefaz(
    processo
):

    numero = processo[
        "numero"
    ]


    html, url_final = (
        baixar_pagina_sefaz(
            numero
        )
    )


    soup = BeautifulSoup(
        html,
        "html.parser"
    )


    cabecalho = (
        extrair_cabecalho_sefaz(
            soup
        )
    )


    movimentacoes = (
        extrair_movimentacoes_sefaz(
            soup
        )
    )


    if movimentacoes:

        ultima = (
            movimentacoes[0]
        )

    else:

        ultima = {

            "data":
                "",

            "setor":
                "",

            "evento":
                "",

        }


    return {

        "numero":
            numero,

        "origem":
            "sefaz",

        "cod_protocolo":
            "",

        "situacao":
            (
                cabecalho[
                    "situacao"
                ]
                or
                "Não identificada"
            ),

        "interessado":
            cabecalho[
                "interessado"
            ],

        "assunto":
            cabecalho[
                "assunto"
            ],

        "dataMovimentacao":
            ultima[
                "data"
            ],

        "setor":
            ultima[
                "setor"
            ],

        "evento":
            ultima[
                "evento"
            ],

        "url":
            url_final,

        "consultado_em":
            agora_iso(),

        "erro":
            None,

    }


# ============================================================
# SEMEF
# ============================================================

def localizar_valor_rotulo(
    soup,
    rotulo
):

    rotulo_alvo = (
        texto_limpo(
            rotulo
        )
        .replace(
            ":",
            ""
        )
        .upper()
    )


    # --------------------------------------------------------
    # Procura primeiro em células de tabela
    # --------------------------------------------------------

    for celula in soup.find_all(
        [
            "td",
            "th"
        ]
    ):

        texto = (
            texto_limpo(
                celula.get_text(
                    " ",
                    strip=True
                )
            )
            .replace(
                ":",
                ""
            )
            .upper()
        )


        if texto != rotulo_alvo:
            continue


        proxima = (
            celula.find_next(
                "td"
            )
        )


        if proxima:

            valor = texto_limpo(

                proxima.get_text(
                    " ",
                    strip=True
                )

            )

            if (
                valor
                and
                valor.upper()
                != rotulo_alvo
            ):

                return valor


    return ""


def extrair_cabecalho_semef(
    soup
):

    texto = texto_limpo(

        soup.get_text(
            " ",
            strip=True
        )

    )


    def regex_valor(
        inicio,
        finais
    ):

        padrao_finais = "|".join(

            re.escape(
                item
            )

            for item
            in finais

        )


        match = re.search(

            re.escape(
                inicio
            )
            +
            r"\s*:\s*"
            +
            r"(.*?)"
            +
            r"(?=\s+(?:"
            +
            padrao_finais
            +
            r")\s*:|$)",

            texto,

            flags=re.IGNORECASE

        )


        if match:

            return texto_limpo(
                match.group(1)
            )


        return ""


    processo_numero = regex_valor(

        "PROCESSO",

        [
            "DATA DO PROCESSO",
            "SITUAÇÃO",
            "INTERESSADO"
        ]

    )


    data_processo = regex_valor(

        "DATA DO PROCESSO",

        [
            "SITUAÇÃO",
            "INTERESSADO"
        ]

    )


    situacao = regex_valor(

        "SITUAÇÃO",

        [
            "INTERESSADO",
            "ASSUNTO",
            "LOCALIZAÇÃO ATUAL"
        ]

    )


    interessado = regex_valor(

        "INTERESSADO",

        [
            "ASSUNTO",
            "LOCALIZAÇÃO ATUAL"
        ]

    )


    assunto = regex_valor(

        "ASSUNTO",

        [
            "LOCALIZAÇÃO ATUAL",
            "DATA DO SOBRESTAMENTO",
            "DESPACHO"
        ]

    )


    localizacao = regex_valor(

        "LOCALIZAÇÃO ATUAL",

        [
            "DATA DO SOBRESTAMENTO",
            "DESPACHO",
            "MOTIVO",
            "Histórico do Processo"
        ]

    )


    return {

        "numero":
            processo_numero,

        "data_processo":
            data_processo,

        "situacao":
            situacao,

        "interessado":
            interessado,

        "assunto":
            assunto,

        "localizacao":
            localizacao,

    }


def encontrar_tabela_historico_semef(
    soup
):

    for tabela in soup.find_all(
        "table"
    ):

        texto = texto_limpo(

            tabela.get_text(
                " ",
                strip=True
            )

        ).upper()


        if (
            "SITUAÇÃO" in texto
            and
            "DATA" in texto
            and
            "DEPTO" in texto
            and
            "DESPACHO" in texto
            and
            "MOVIMENTAÇÃO" in texto
        ):

            return tabela


    return None


def extrair_historico_semef(
    soup
):

    tabela = (
        encontrar_tabela_historico_semef(
            soup
        )
    )


    if tabela is None:

        print(
            "Aviso: histórico SEMEF "
            "não encontrado."
        )

        return []


    linhas = []


    for linha in tabela.find_all(
        "tr"
    ):

        celulas = linha.find_all(
            [
                "td",
                "th"
            ]
        )


        valores = [

            texto_limpo(

                celula.get_text(
                    " ",
                    strip=True
                )

            )

            for celula
            in celulas

        ]


        if not valores:
            continue


        texto_linha = (
            " ".join(
                valores
            )
            .upper()
        )


        if (
            "DESPACHO MOVIMENTAÇÃO"
            in texto_linha
            or
            "DEPTO. ORIGEM"
            in texto_linha
        ):

            continue


        # ----------------------------------------------------
        # Estrutura observada no SIGED:
        #
        # 0 Situação
        # 1 Data
        # 2 Depto. Origem
        # 3 Desfeito/Desarquivado em
        # 4 Recebido em
        # 5 Depto. Destino
        # 6 Despacho Movimentação
        # ----------------------------------------------------

        if len(
            valores
        ) < 2:

            continue


        situacao = (
            valores[0]
            if len(valores) > 0
            else ""
        )

        data = (
            valores[1]
            if len(valores) > 1
            else ""
        )

        origem = (
            valores[2]
            if len(valores) > 2
            else ""
        )

        recebido = (
            valores[4]
            if len(valores) > 4
            else ""
        )

        destino = (
            valores[5]
            if len(valores) > 5
            else ""
        )

        despacho = (
            texto_limpo(
                " ".join(
                    valores[6:]
                )
            )
            if len(valores) > 6
            else ""
        )


        if not re.match(
            r"^\d{2}/\d{2}/\d{4}$",
            data
        ):

            continue


        linhas.append({

            "situacao":
                situacao,

            "data":
                data,

            "origem":
                origem,

            "recebido":
                recebido,

            "destino":
                destino,

            "despacho":
                despacho,

        })


    return linhas


def resolver_cod_protocolo(
    processo
):

    numero = processo[
        "numero"
    ]


    cod_protocolo = texto_limpo(

        processo.get(
            "cod_protocolo",
            ""
        )

    )


    if cod_protocolo:

        return cod_protocolo


    cod_protocolo = (
        SEMEF_PROTOCOLS.get(
            numero,
            ""
        )
    )


    if cod_protocolo:

        return cod_protocolo


    raise ValueError(

        "Processo SEMEF sem código "
        "de protocolo conhecido. "
        "A pesquisa inicial do SIGED "
        "exige validação por código de acesso."

    )


def consultar_semef(
    processo
):

    numero = processo[
        "numero"
    ]


    cod_protocolo = (
        resolver_cod_protocolo(
            processo
        )
    )


    url = url_semef(
        cod_protocolo
    )


    html, url_final = baixar_url(

        url,

        f"SEMEF - {numero}"

    )


    soup = BeautifulSoup(
        html,
        "html.parser"
    )


    cabecalho = (
        extrair_cabecalho_semef(
            soup
        )
    )


    historico = (
        extrair_historico_semef(
            soup
        )
    )


    # --------------------------------------------------------
    # REGRA DEFINIDA:
    #
    # Usa EXATAMENTE a primeira linha do histórico.
    #
    # Se "Despacho Movimentação" estiver vazio,
    # evento permanece vazio.
    #
    # NÃO busca o despacho de linha anterior,
    # inclusive em situação SOBRESTADO.
    # --------------------------------------------------------

    if historico:

        ultima = historico[0]

    else:

        ultima = {

            "situacao":
                "",

            "data":
                "",

            "origem":
                "",

            "recebido":
                "",

            "destino":
                "",

            "despacho":
                "",

        }


    numero_pagina = texto_limpo(

        cabecalho.get(
            "numero",
            ""
        )

    )


    if (
        numero_pagina
        and
        numero_pagina != numero
    ):

        raise ValueError(

            "O código de protocolo SEMEF "
            "não corresponde ao número "
            f"{numero}."

        )


    situacao = texto_limpo(

        cabecalho.get(
            "situacao",
            ""
        )

    )


    if not situacao:

        situacao = texto_limpo(

            ultima.get(
                "situacao",
                ""
            )

        )


    return {

        "numero":
            numero,

        "origem":
            "semef",

        "cod_protocolo":
            cod_protocolo,

        "situacao":
            (
                situacao
                or
                "Não identificada"
            ),

        "interessado":
            texto_limpo(
                cabecalho.get(
                    "interessado",
                    ""
                )
            ),

        "assunto":
            texto_limpo(
                cabecalho.get(
                    "assunto",
                    ""
                )
            ),

        "dataMovimentacao":
            texto_limpo(
                ultima.get(
                    "data",
                    ""
                )
            ),

        "setor":
            texto_limpo(
                cabecalho.get(
                    "localizacao",
                    ""
                )
            ),

        # IMPORTANTE:
        # evento = Despacho Movimentação
        # da primeira linha do histórico.

        "evento":
            texto_limpo(
                ultima.get(
                    "despacho",
                    ""
                )
            ),

        "url":
            url_final,

        "consultado_em":
            agora_iso(),

        "erro":
            None,

    }


# ============================================================
# CONSULTA POR ORIGEM
# ============================================================

def consultar_processo(
    processo
):

    origem = processo.get(
        "origem",
        "sefaz"
    )


    if origem == "semef":

        return consultar_semef(
            processo
        )


    return consultar_sefaz(
        processo
    )


# ============================================================
# COMPARAÇÃO
# ============================================================

def assinatura_movimentacao(
    processo
):

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
        or
        setor
        or
        evento
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
            processo.get(
                "numero"
            )
            ==
            numero
        ):

            return processo


    return None


def anterior_e_valido(
    anterior
):

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


    assinatura = (
        assinatura_movimentacao(
            anterior
        )
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

        "origem":
            novo.get(
                "origem",
                "sefaz"
            ),

        "data":
            agora_iso(),

        "mensagem":
            (
                "Nova movimentação: "
                +
                (
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
            alerta.get(
                "numero"
            )
            ==
            numero
            and
            alerta.get(
                "movimentacao_atual"
            )
            ==
            assinatura
        ):

            return True


    return False


# ============================================================
# URL PARA ERRO
# ============================================================

def url_do_processo(
    processo
):

    if (
        processo.get(
            "origem"
        )
        ==
        "semef"
    ):

        try:

            return url_semef(

                resolver_cod_protocolo(
                    processo
                )

            )

        except Exception:

            return (
                "https://sigedweb.manaus.am.gov.br/"
                "protonweb/"
            )


    return url_sefaz(
        processo[
            "numero"
        ]
    )


# ============================================================
# EXECUÇÃO
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "MONITOR SEFAZ + SEMEF"
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


    dados_anteriores = (
        carregar_dados()
    )


    novos_processos = []


    numeros_ativos = {

        item[
            "numero"
        ]

        for item
        in processos_monitorados

    }


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
        in numeros_ativos

    ]


    erros = 0

    novos_alertas_detectados = 0


    # ========================================================
    # CONSULTA
    # ========================================================

    for cadastro in processos_monitorados:

        numero = cadastro[
            "numero"
        ]

        origem = cadastro[
            "origem"
        ]


        print()

        print(
            "-" * 60
        )

        print(
            f"{origem.upper()} - {numero}"
        )

        print(
            "-" * 60
        )


        anterior = localizar_anterior(
            dados_anteriores,
            numero
        )


        try:

            atual = consultar_processo(
                cadastro
            )


            print(
                "Origem:",
                atual[
                    "origem"
                ].upper()
            )

            print(
                "Situação:",
                atual[
                    "situacao"
                ]
            )

            print(
                "Interessado:",
                atual[
                    "interessado"
                ]
            )

            print(
                "Assunto:",
                atual[
                    "assunto"
                ]
            )

            print(
                "Setor:",
                atual[
                    "setor"
                ]
            )

            print(
                "Data:",
                atual[
                    "dataMovimentacao"
                ]
            )

            print(
                "Última movimentação:",
                atual[
                    "evento"
                ]
                or
                "—"
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
                    !=
                    assinatura_anterior
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
                            "NOVA MOVIMENTAÇÃO DETECTADA!"
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
                    "origem"
                ] = origem


                if (
                    origem
                    ==
                    "semef"
                ):

                    copia[
                        "cod_protocolo"
                    ] = cadastro.get(
                        "cod_protocolo",
                        SEMEF_PROTOCOLS.get(
                            numero,
                            ""
                        )
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

                    "origem":
                        origem,

                    "cod_protocolo":
                        cadastro.get(
                            "cod_protocolo",
                            ""
                        ),

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
                        url_do_processo(
                            cadastro
                        ),

                    "consultado_em":
                        agora_iso(),

                    "erro":
                        str(
                            erro
                        ),

                })


    # ========================================================
    # LIMITA HISTÓRICO
    # ========================================================

    novos_alertas = (
        novos_alertas[:100]
    )


    # ========================================================
    # SAÍDA
    # ========================================================

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
