import json
import os
import queue
import re
import sys
import threading
import time
import unicodedata

from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURAÇÃO
# ============================================================

ARQUIVO_DADOS = "dados.json"
ARQUIVO_PROCESSOS = "processos.json"

SEFAZ_BASE_URL = "https://online.sefaz.am.gov.br/processo/"

SEMEF_HOME_URL = (
    "https://sigedweb.manaus.am.gov.br/protonweb/"
)

SEMEF_DETALHE_URL = (
    "https://sigedweb.manaus.am.gov.br/"
    "protonweb/detalhe.aspx"
)

TIMEZONE = "America/Manaus"

# Limite máximo da execução completa
TEMPO_MAXIMO_EXECUCAO = 50

# Consultas simultâneas
MAX_WORKERS = 10

# SEFAZ
SEFAZ_CONNECT_TIMEOUT = 4
SEFAZ_READ_TIMEOUT = 8

# SEMEF
SEMEF_CONNECT_TIMEOUT = 5
SEMEF_READ_TIMEOUT = 10

# Uma tentativa por atualização
SEMEF_MAX_TENTATIVAS = 1


# ============================================================
# HEADERS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": (
        "text/html,"
        "application/xhtml+xml,"
        "application/xml;q=0.9,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


# ============================================================
# PROTOCOLOS SEMEF CONHECIDOS
# ============================================================

SEMEF_PROTOCOLS = {
    "2024.18000.19012.0.008302": "7954846",
    "2026.18000.19951.0.024703": "11442112",
    "2026.18000.19951.0.014382": "11037580",
}


# ============================================================
# DATA / HORA
# ============================================================

def agora_manaus():
    return datetime.now(
        ZoneInfo(TIMEZONE)
    )


def agora_iso():
    return agora_manaus().isoformat(
        timespec="seconds"
    )


# ============================================================
# TEXTO
# ============================================================

def reparar_mojibake(valor):
    if valor is None:
        return ""

    texto = str(valor)

    for _ in range(2):
        if not any(
            marcador in texto
            for marcador in (
                "Ã",
                "Â",
                "â€",
                "ðŸ",
            )
        ):
            break

        try:
            corrigido = (
                texto
                .encode("latin1")
                .decode("utf-8")
            )

            if corrigido == texto:
                break

            texto = corrigido

        except Exception:
            break

    return texto


def texto_limpo(valor):
    texto = reparar_mojibake(valor)

    return re.sub(
        r"\s+",
        " ",
        texto
    ).strip()


def chave_texto(valor):
    texto = texto_limpo(valor)

    texto = unicodedata.normalize(
        "NFD",
        texto
    )

    texto = "".join(
        caractere
        for caractere in texto
        if unicodedata.category(
            caractere
        ) != "Mn"
    )

    texto = texto.lower()

    texto = re.sub(
        r"[^a-z0-9]+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# ORIGEM
# ============================================================

def detectar_origem(numero):
    numero = texto_limpo(numero)

    if re.fullmatch(
        r"\d{4}\."
        r"\d{5}\."
        r"\d{5}\."
        r"\d\."
        r"\d{6}",
        numero
    ):
        return "semef"

    return "sefaz"


def normalizar_origem(
    valor,
    numero=""
):
    origem = chave_texto(valor)

    if origem in (
        "semef",
        "siged",
    ):
        return "semef"

    if origem == "sefaz":
        return "sefaz"

    return detectar_origem(numero)


# ============================================================
# URLS
# ============================================================

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
        SEMEF_DETALHE_URL
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
# PROCESSOS.JSON
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

        if isinstance(
            item,
            str
        ):
            numero = texto_limpo(item)
            origem = detectar_origem(numero)

            cod_protocolo = (
                SEMEF_PROTOCOLS.get(
                    numero,
                    ""
                )
                if origem == "semef"
                else ""
            )

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
                    ""
                ),
                numero
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
            continue

        vistos.add(numero)

        processos.append({
            "numero": numero,
            "origem": origem,
            "cod_protocolo": cod_protocolo,
        })

    if not processos:
        raise ValueError(
            "Nenhum processo cadastrado."
        )

    return processos


# ============================================================
# DADOS ANTERIORES
# ============================================================

def carregar_dados_anteriores():
    if not os.path.exists(
        ARQUIVO_DADOS
    ):
        return {
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

        if not isinstance(
            dados,
            dict
        ):
            return {
                "processos": [],
                "alertas": [],
            }

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
            "Aviso ao carregar dados.json:",
            erro
        )

        return {
            "processos": [],
            "alertas": [],
        }


def criar_mapa_anterior(dados):
    mapa = {}

    for processo in dados.get(
        "processos",
        []
    ):
        if not isinstance(
            processo,
            dict
        ):
            continue

        numero = texto_limpo(
            processo.get(
                "numero",
                processo.get(
                    "processo",
                    ""
                )
            )
        )

        if numero:
            mapa[numero] = processo

    return mapa


# ============================================================
# ESTRUTURA PADRÃO
# ============================================================

def estrutura_vazia(cadastro):
    return {
        "numero":
            cadastro["numero"],

        "origem":
            cadastro["origem"],

        "cod_protocolo":
            cadastro.get(
                "cod_protocolo",
                ""
            ),

        "situacao": "",
        "interessado": "",
        "assunto": "",
        "setor": "",
        "evento": "",
        "dataMovimentacao": "",
        "erro": "",
        "consultado_em": "",
    }


# ============================================================
# NÃO ATUALIZADO
# ============================================================

def marcar_nao_atualizado(
    cadastro,
    anterior,
    motivo
):
    resultado = estrutura_vazia(
        cadastro
    )

    if isinstance(
        anterior,
        dict
    ):
        for campo in (
            "situacao",
            "interessado",
            "assunto",
            "setor",
            "evento",
            "dataMovimentacao",
        ):
            valor = anterior.get(campo)

            if valor not in (
                None,
                ""
            ):
                resultado[campo] = valor

    if not resultado[
        "situacao"
    ]:
        resultado[
            "situacao"
        ] = "Não atualizado"

    resultado[
        "consultado_em"
    ] = agora_iso()

    resultado[
        "erro"
    ] = (
        texto_limpo(motivo)
        or
        "Não atualizado"
    )

    return resultado


# ============================================================
# HTTP
# ============================================================

def criar_sessao():
    sessao = requests.Session()
    sessao.headers.update(HEADERS)

    return sessao


def obter_html(
    url,
    connect_timeout,
    read_timeout
):
    sessao = criar_sessao()

    try:
        resposta = sessao.get(
            url,
            timeout=(
                connect_timeout,
                read_timeout
            ),
            allow_redirects=True
        )

        resposta.raise_for_status()

        if not resposta.content:
            raise RuntimeError(
                "A página retornada está vazia."
            )

        return resposta.content

    finally:
        sessao.close()


# ============================================================
# RÓTULOS
# ============================================================

ROTULOS_CONHECIDOS = {
    "situacao",
    "assunto",
    "interessado",
    "orgao entidade",
    "cnpj",
    "processo",
    "setor",
    "evento",
    "data",
    "localizacao atual",
    "localizacao",
}


def token_invalido_como_valor(valor):
    texto = texto_limpo(valor)

    if not texto:
        return True

    if texto in (
        ":",
        "-",
        "–",
        "—",
    ):
        return True

    if chave_texto(
        texto
    ) in ROTULOS_CONHECIDOS:
        return True

    return False


# ============================================================
# VALOR POR RÓTULO
# ============================================================

def valor_por_rotulo(
    soup,
    rotulos
):
    alvos = {
        chave_texto(rotulo)
        for rotulo in rotulos
    }

    tokens = [
        texto_limpo(texto)
        for texto
        in soup.stripped_strings
    ]

    for indice, token in enumerate(
        tokens
    ):
        if chave_texto(
            token
        ) not in alvos:
            continue

        limite = min(
            len(tokens),
            indice + 8
        )

        for proximo_indice in range(
            indice + 1,
            limite
        ):
            candidato = tokens[
                proximo_indice
            ]

            if token_invalido_como_valor(
                candidato
            ):
                continue

            return texto_limpo(
                candidato
            )

    for linha in soup.find_all(
        "tr"
    ):
        celulas = linha.find_all(
            [
                "td",
                "th",
            ]
        )

        if not celulas:
            continue

        textos = [
            texto_limpo(
                celula.get_text(
                    " ",
                    strip=True
                )
            )
            for celula in celulas
        ]

        for indice, texto in enumerate(
            textos
        ):
            if chave_texto(
                texto
            ) not in alvos:
                continue

            for candidato in textos[
                indice + 1:
            ]:
                if token_invalido_como_valor(
                    candidato
                ):
                    continue

                return candidato

    return ""


# ============================================================
# EXTRAÇÃO SEQUENCIAL SEFAZ
# ============================================================

def extrair_campo_sefaz_por_tokens(
    soup,
    rotulo,
    proximos_rotulos
):
    tokens = [
        texto_limpo(item)
        for item
        in soup.stripped_strings
    ]

    alvo = chave_texto(rotulo)

    limites = {
        chave_texto(item)
        for item
        in proximos_rotulos
    }

    inicio = None

    for indice, token in enumerate(
        tokens
    ):
        if chave_texto(
            token
        ) == alvo:
            inicio = indice + 1
            break

    if inicio is None:
        return ""

    partes = []

    for token in tokens[
        inicio:
    ]:
        chave = chave_texto(token)

        if chave in limites:
            break

        if token in (
            ":",
            "",
        ):
            continue

        if (
            not partes
            and
            chave in ROTULOS_CONHECIDOS
        ):
            continue

        partes.append(token)

    return texto_limpo(
        " ".join(partes)
    )


# ============================================================
# LIMPEZA SEFAZ
# ============================================================

def cortar_no_primeiro_marcador(
    texto,
    marcadores
):
    texto = texto_limpo(texto)

    posicoes = []

    for marcador in marcadores:
        correspondencia = re.search(
            marcador,
            texto,
            flags=re.IGNORECASE
        )

        if correspondencia:
            posicoes.append(
                correspondencia.start()
            )

    if posicoes:
        texto = texto[
            :min(posicoes)
        ]

    return texto_limpo(texto)


def limpar_situacao_sefaz(valor):
    valor = cortar_no_primeiro_marcador(
        valor,
        [
            r"\bAssunto\b",
            r"\bÓrgão\s*/\s*Entidade\b",
            r"\bOrgao\s*/\s*Entidade\b",
            r"\bInteressado\b",
            r"\bCNPJ\b",
        ]
    )

    if token_invalido_como_valor(
        valor
    ):
        return ""

    return valor


def limpar_assunto_sefaz(valor):
    valor = cortar_no_primeiro_marcador(
        valor,
        [
            r"\bÓrgão\s*/\s*Entidade\b",
            r"\bOrgao\s*/\s*Entidade\b",
            r"\bInteressado\b",
            r"\bCNPJ\b",
            r"\bProcesso\s+dispon[ií]vel\b",
        ]
    )

    if token_invalido_como_valor(
        valor
    ):
        return ""

    return valor


def limpar_interessado_sefaz(valor):
    """
    Deixa somente o nome do interessado.

    Exemplo:
    34.018.488/0001-04 Interessado PLATINA SERVICOS...
    ->
    PLATINA SERVICOS...
    """

    valor = texto_limpo(valor)

    # Remove textos que aparecem depois do nome.
    valor = cortar_no_primeiro_marcador(
        valor,
        [
            r"\bProcesso\s+dispon[ií]vel\b",
            r"\bNova\s+Pesquisa\b",
            r"\bData\s+Setor\s+Evento\b",
        ]
    )

    # Remove a palavra "Interessado"
    # no começo ou no meio do texto.
    valor = re.sub(
        r"\bInteressado\s*:?\s*",
        " ",
        valor,
        flags=re.IGNORECASE
    )

    # Remove CNPJ com ou sem pontuação.
    valor = re.sub(
        r"\b"
        r"\d{2}\.?\d{3}\.?\d{3}"
        r"/?"
        r"\d{4}"
        r"-?"
        r"\d{2}"
        r"\b",
        " ",
        valor
    )

    # Caso o site retorne "CNPJ:"
    valor = re.sub(
        r"\bCNPJ\s*:?\s*",
        " ",
        valor,
        flags=re.IGNORECASE
    )

    valor = texto_limpo(valor)

    # Remove separadores restantes no início.
    valor = re.sub(
        r"^[\s:;\-|–—]+",
        "",
        valor
    ).strip()

    if token_invalido_como_valor(
        valor
    ):
        return ""

    return valor


# ============================================================
# CABEÇALHO SEFAZ
# ============================================================

def extrair_cabecalho_sefaz(soup):
    situacao = extrair_campo_sefaz_por_tokens(
        soup,
        "Situação",
        [
            "Assunto",
            "Órgão/Entidade",
            "Interessado",
        ]
    )

    if not situacao:
        situacao = valor_por_rotulo(
            soup,
            [
                "Situação",
                "Situacao",
            ]
        )

    assunto = extrair_campo_sefaz_por_tokens(
        soup,
        "Assunto",
        [
            "Órgão/Entidade",
            "CNPJ",
            "Interessado",
        ]
    )

    if not assunto:
        assunto = valor_por_rotulo(
            soup,
            [
                "Assunto",
            ]
        )

    interessado = (
        extrair_campo_sefaz_por_tokens(
            soup,
            "Interessado",
            [
                "Processo disponível",
                "Nova Pesquisa",
                "Data",
                "Setor",
                "Evento",
            ]
        )
    )

    if not interessado:
        interessado = valor_por_rotulo(
            soup,
            [
                "Interessado",
            ]
        )

    return {
        "situacao":
            limpar_situacao_sefaz(
                situacao
            ),

        "assunto":
            limpar_assunto_sefaz(
                assunto
            ),

        "interessado":
            limpar_interessado_sefaz(
                interessado
            ),
    }


# ============================================================
# DATA
# ============================================================

def converter_data(valor):
    valor = texto_limpo(valor)

    for formato in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(
                valor,
                formato
            )

        except ValueError:
            pass

    return None


# ============================================================
# MOVIMENTAÇÕES SEFAZ
# ============================================================

def extrair_movimentacoes_sefaz(soup):
    tabela_alvo = None

    for tabela in soup.find_all(
        "table"
    ):
        texto = chave_texto(
            tabela.get_text(
                " ",
                strip=True
            )
        )

        if (
            "data" in texto
            and
            "setor" in texto
            and
            "evento" in texto
        ):
            tabela_alvo = tabela
            break

    if tabela_alvo is None:
        return []

    movimentacoes = []

    for linha in tabela_alvo.find_all(
        "tr"
    ):
        valores = [
            texto_limpo(
                celula.get_text(
                    " ",
                    strip=True
                )
            )
            for celula
            in linha.find_all(
                [
                    "td",
                    "th",
                ]
            )
        ]

        if len(
            valores
        ) < 3:
            continue

        data = valores[0]

        if not re.fullmatch(
            (
                r"\d{2}/\d{2}/\d{4}"
                r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"
            ),
            data
        ):
            continue

        movimentacoes.append({
            "data":
                data,

            "setor":
                texto_limpo(
                    valores[1]
                ),

            "evento":
                texto_limpo(
                    " ".join(
                        valores[2:]
                    )
                ),

            "data_obj":
                converter_data(
                    data
                ),
        })

    return movimentacoes


def ultima_movimentacao_sefaz(
    movimentacoes
):
    if not movimentacoes:
        return {
            "data": "",
            "setor": "",
            "evento": "",
        }

    validas = [
        item
        for item
        in movimentacoes
        if item.get(
            "data_obj"
        ) is not None
    ]

    if validas:
        ultima = max(
            validas,
            key=lambda item:
                item["data_obj"]
        )

    else:
        ultima = movimentacoes[0]

    return {
        "data":
            texto_limpo(
                ultima.get(
                    "data",
                    ""
                )
            ),

        "setor":
            texto_limpo(
                ultima.get(
                    "setor",
                    ""
                )
            ),

        "evento":
            texto_limpo(
                ultima.get(
                    "evento",
                    ""
                )
            ),
    }


# ============================================================
# CONSULTA SEFAZ
# ============================================================

def consultar_sefaz(cadastro):
    numero = cadastro[
        "numero"
    ]

    conteudo = obter_html(
        url_sefaz(numero),
        SEFAZ_CONNECT_TIMEOUT,
        SEFAZ_READ_TIMEOUT
    )

    soup = BeautifulSoup(
        conteudo,
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

    ultima = (
        ultima_movimentacao_sefaz(
            movimentacoes
        )
    )

    situacao = texto_limpo(
        cabecalho.get(
            "situacao",
            ""
        )
    )

    assunto = texto_limpo(
        cabecalho.get(
            "assunto",
            ""
        )
    )

    interessado = (
        limpar_interessado_sefaz(
            cabecalho.get(
                "interessado",
                ""
            )
        )
    )

    if token_invalido_como_valor(
        situacao
    ):
        situacao = ""

    if token_invalido_como_valor(
        assunto
    ):
        assunto = ""

    if token_invalido_como_valor(
        interessado
    ):
        interessado = ""

    if not situacao:
        situacao = "Não identificada"

    return {
        "numero":
            numero,

        "origem":
            "sefaz",

        "cod_protocolo":
            "",

        "situacao":
            situacao,

        "interessado":
            interessado,

        "assunto":
            assunto,

        "setor":
            ultima.get(
                "setor",
                ""
            ),

        "evento":
            ultima.get(
                "evento",
                ""
            ),

        "dataMovimentacao":
            ultima.get(
                "data",
                ""
            ),

        "erro":
            "",

        "consultado_em":
            agora_iso(),
    }


# ============================================================
# SEMEF / SIGED
# ============================================================

def resolver_cod_protocolo(cadastro):
    codigo = texto_limpo(
        cadastro.get(
            "cod_protocolo",
            ""
        )
    )

    if codigo:
        return codigo

    numero = cadastro[
        "numero"
    ]

    codigo = texto_limpo(
        SEMEF_PROTOCOLS.get(
            numero,
            ""
        )
    )

    if codigo:
        return codigo

    raise ValueError(
        "Processo SEMEF sem código de protocolo."
    )


def criar_sessao_semef():
    """
    Cria uma sessão específica do SIGED.

    Primeiro acessamos a página inicial para que
    o servidor possa fornecer cookies de sessão.
    """

    sessao = requests.Session()

    sessao.headers.update(
        HEADERS
    )

    sessao.headers.update({
        "Referer":
            SEMEF_HOME_URL,

        "Origin":
            "https://sigedweb.manaus.am.gov.br",
    })

    return sessao


def obter_html_semef(
    cod_protocolo
):
    sessao = criar_sessao_semef()

    try:
        # ----------------------------------------------------
        # 1. ABRIR PÁGINA INICIAL
        # ----------------------------------------------------

        resposta_home = sessao.get(
            SEMEF_HOME_URL,
            timeout=(
                SEMEF_CONNECT_TIMEOUT,
                SEMEF_READ_TIMEOUT
            ),
            allow_redirects=True
        )

        resposta_home.raise_for_status()

        # ----------------------------------------------------
        # 2. CONSULTAR DETALHE COM A MESMA SESSÃO
        # ----------------------------------------------------

        resposta = sessao.get(
            SEMEF_DETALHE_URL,
            params={
                "origem": "1",
                "cod_protocolo":
                    str(
                        cod_protocolo
                    ),
            },
            headers={
                "Referer":
                    resposta_home.url,
            },
            timeout=(
                SEMEF_CONNECT_TIMEOUT,
                SEMEF_READ_TIMEOUT
            ),
            allow_redirects=True
        )

        resposta.raise_for_status()

        if not resposta.content:
            raise RuntimeError(
                "A SEMEF retornou uma página vazia."
            )

        return resposta.content

    finally:
        sessao.close()


# ============================================================
# CABEÇALHO SEMEF
# ============================================================

def extrair_cabecalho_semef(soup):
    return {
        "numero":
            valor_por_rotulo(
                soup,
                [
                    "Processo",
                ]
            ),

        "situacao":
            valor_por_rotulo(
                soup,
                [
                    "Situação",
                    "Situacao",
                ]
            ),

        "interessado":
            valor_por_rotulo(
                soup,
                [
                    "Interessado",
                ]
            ),

        "assunto":
            valor_por_rotulo(
                soup,
                [
                    "Assunto",
                ]
            ),

        "localizacao":
            valor_por_rotulo(
                soup,
                [
                    "Localização Atual",
                    "Localizacao Atual",
                    "Localização",
                    "Localizacao",
                ]
            ),
    }


# ============================================================
# HISTÓRICO SEMEF
# ============================================================

def extrair_historico_semef(soup):
    tabela_alvo = None

    for tabela in soup.find_all(
        "table"
    ):
        texto = chave_texto(
            tabela.get_text(
                " ",
                strip=True
            )
        )

        if (
            "data" in texto
            and
            (
                "despacho" in texto
                or
                "movimentacao" in texto
            )
        ):
            tabela_alvo = tabela
            break

    if tabela_alvo is None:
        return []

    historico = []

    for linha in tabela_alvo.find_all(
        "tr"
    ):
        valores = [
            texto_limpo(
                celula.get_text(
                    " ",
                    strip=True
                )
            )
            for celula
            in linha.find_all(
                [
                    "td",
                    "th",
                ]
            )
        ]

        if not valores:
            continue

        indice_data = None

        for indice, valor in enumerate(
            valores
        ):
            if re.fullmatch(
                (
                    r"\d{2}/\d{2}/\d{4}"
                    r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"
                ),
                valor
            ):
                indice_data = indice
                break

        if indice_data is None:
            continue

        data = valores[
            indice_data
        ]

        situacao = (
            valores[0]
            if indice_data > 0
            else ""
        )

        origem = (
            valores[
                indice_data + 1
            ]
            if (
                len(valores)
                >
                indice_data + 1
            )
            else ""
        )

        destino = ""

        if (
            len(valores)
            >
            indice_data + 4
        ):
            destino = valores[
                indice_data + 4
            ]

        despacho = ""

        if (
            len(valores)
            >
            indice_data + 5
        ):
            despacho = texto_limpo(
                " ".join(
                    valores[
                        indice_data + 5:
                    ]
                )
            )

        elif (
            len(valores)
            >
            indice_data + 2
        ):
            despacho = texto_limpo(
                " ".join(
                    valores[
                        indice_data + 2:
                    ]
                )
            )

        historico.append({
            "situacao":
                situacao,

            "data":
                data,

            "origem":
                origem,

            "destino":
                destino,

            "despacho":
                despacho,

            "data_obj":
                converter_data(
                    data
                ),
        })

    return historico


def ultima_movimentacao_semef(
    historico
):
    if not historico:
        return {
            "situacao": "",
            "data": "",
            "origem": "",
            "destino": "",
            "despacho": "",
        }

    validos = [
        item
        for item
        in historico
        if item.get(
            "data_obj"
        ) is not None
    ]

    if validos:
        return max(
            validos,
            key=lambda item:
                item["data_obj"]
        )

    return historico[0]


# ============================================================
# CONSULTA SEMEF
# ============================================================

def consultar_semef(cadastro):
    numero = cadastro[
        "numero"
    ]

    codigo = resolver_cod_protocolo(
        cadastro
    )

    ultimo_erro = None

    for _ in range(
        SEMEF_MAX_TENTATIVAS
    ):
        try:
            conteudo = obter_html_semef(
                codigo
            )

            soup = BeautifulSoup(
                conteudo,
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

            ultima = (
                ultima_movimentacao_semef(
                    historico
                )
            )

            situacao = (
                texto_limpo(
                    cabecalho.get(
                        "situacao",
                        ""
                    )
                )
                or
                texto_limpo(
                    ultima.get(
                        "situacao",
                        ""
                    )
                )
                or
                "Não identificada"
            )

            setor = (
                texto_limpo(
                    cabecalho.get(
                        "localizacao",
                        ""
                    )
                )
                or
                texto_limpo(
                    ultima.get(
                        "destino",
                        ""
                    )
                )
                or
                texto_limpo(
                    ultima.get(
                        "origem",
                        ""
                    )
                )
            )

            interessado = texto_limpo(
                cabecalho.get(
                    "interessado",
                    ""
                )
            )

            assunto = texto_limpo(
                cabecalho.get(
                    "assunto",
                    ""
                )
            )

            possui_dados = any([
                interessado,
                assunto,
                setor,
                texto_limpo(
                    ultima.get(
                        "data",
                        ""
                    )
                ),
                texto_limpo(
                    ultima.get(
                        "despacho",
                        ""
                    )
                ),
            ])

            if not possui_dados:
                raise RuntimeError(
                    "A SEMEF respondeu, mas não retornou "
                    "dados do processo."
                )

            return {
                "numero":
                    numero,

                "origem":
                    "semef",

                "cod_protocolo":
                    codigo,

                "situacao":
                    situacao,

                "interessado":
                    interessado,

                "assunto":
                    assunto,

                "setor":
                    setor,

                "evento":
                    texto_limpo(
                        ultima.get(
                            "despacho",
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

                "erro":
                    "",

                "consultado_em":
                    agora_iso(),
            }

        except Exception as erro:
            ultimo_erro = erro

    raise RuntimeError(
        "Não foi possível atualizar o processo SEMEF: "
        +
        texto_limpo(
            ultimo_erro
        )
    )


# ============================================================
# CONSULTA POR ORIGEM
# ============================================================

def consultar_processo(cadastro):
    if cadastro.get(
        "origem"
    ) == "semef":
        return consultar_semef(
            cadastro
        )

    return consultar_sefaz(
        cadastro
    )


# ============================================================
# ALERTAS
# ============================================================

def assinatura_movimentacao(processo):
    if not isinstance(
        processo,
        dict
    ):
        return ""

    return "|".join([
        texto_limpo(
            processo.get(
                "dataMovimentacao",
                ""
            )
        ),
        texto_limpo(
            processo.get(
                "setor",
                ""
            )
        ),
        texto_limpo(
            processo.get(
                "evento",
                ""
            )
        ),
    ])


def dado_anterior_valido(processo):
    if not isinstance(
        processo,
        dict
    ):
        return False

    if texto_limpo(
        processo.get(
            "erro",
            ""
        )
    ):
        return False

    return bool(
        assinatura_movimentacao(
            processo
        ).replace(
            "|",
            ""
        )
    )


def alerta_ja_existe(
    alertas,
    numero,
    assinatura
):
    return any(
        alerta.get(
            "numero"
        ) == numero
        and
        alerta.get(
            "movimentacao_atual"
        ) == assinatura
        for alerta in alertas
    )


def criar_alerta(
    atual,
    anterior
):
    return {
        "numero":
            atual.get(
                "numero",
                ""
            ),

        "origem":
            atual.get(
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
                    atual.get(
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
                atual
            ),

        "data_movimentacao":
            atual.get(
                "dataMovimentacao",
                ""
            ),

        "setor":
            atual.get(
                "setor",
                ""
            ),

        "evento":
            atual.get(
                "evento",
                ""
            ),
    }


# ============================================================
# WORKER
# ============================================================

def worker_consulta(
    fila_entrada,
    fila_saida,
    deadline
):
    while (
        time.monotonic()
        <
        deadline
    ):
        try:
            cadastro = (
                fila_entrada.get_nowait()
            )

        except queue.Empty:
            return

        numero = cadastro[
            "numero"
        ]

        try:
            resultado = consultar_processo(
                cadastro
            )

            fila_saida.put({
                "numero": numero,
                "ok": True,
                "resultado": resultado,
            })

        except Exception as erro:
            fila_saida.put({
                "numero": numero,
                "ok": False,
                "erro": (
                    texto_limpo(erro)
                    or
                    "Erro na consulta."
                ),
            })

        finally:
            fila_entrada.task_done()


# ============================================================
# SALVAR DADOS.JSON
# ============================================================

def salvar_payload(payload):
    temporario = (
        ARQUIVO_DADOS
        +
        ".tmp"
    )

    with open(
        temporario,
        "w",
        encoding="utf-8"
    ) as arquivo:
        json.dump(
            payload,
            arquivo,
            ensure_ascii=False,
            indent=2
        )

        arquivo.write("\n")

    os.replace(
        temporario,
        ARQUIVO_DADOS
    )


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main():
    inicio = time.monotonic()

    deadline = (
        inicio
        +
        TEMPO_MAXIMO_EXECUCAO
    )

    print("=" * 60)
    print("MONITOR SEFAZ-AM + SEMEF")

    print(
        "Início:",
        agora_manaus().strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    )

    print(
        "Limite global:",
        TEMPO_MAXIMO_EXECUCAO,
        "segundos"
    )

    print("=" * 60)

    try:
        cadastros = carregar_processos()

    except Exception as erro:
        print(
            "Erro ao carregar processos.json:",
            erro
        )

        return 1

    print(
        "Processos cadastrados:",
        len(cadastros)
    )

    dados_anteriores = (
        carregar_dados_anteriores()
    )

    mapa_anterior = (
        criar_mapa_anterior(
            dados_anteriores
        )
    )

    numeros_ativos = {
        cadastro["numero"]
        for cadastro in cadastros
    }

    alertas = [
        alerta
        for alerta
        in dados_anteriores.get(
            "alertas",
            []
        )
        if alerta.get(
            "numero"
        ) in numeros_ativos
    ]

    fila_entrada = queue.Queue()
    fila_saida = queue.Queue()

    for cadastro in cadastros:
        fila_entrada.put(
            cadastro
        )

    quantidade_workers = min(
        MAX_WORKERS,
        len(cadastros)
    )

    for _ in range(
        quantidade_workers
    ):
        thread = threading.Thread(
            target=worker_consulta,
            args=(
                fila_entrada,
                fila_saida,
                deadline
            ),
            daemon=True
        )

        thread.start()

    recebidos = {}

    while (
        time.monotonic()
        <
        deadline
        and
        len(recebidos)
        <
        len(cadastros)
    ):
        restante = (
            deadline
            -
            time.monotonic()
        )

        try:
            item = fila_saida.get(
                timeout=min(
                    0.5,
                    restante
                )
            )

            recebidos[
                item["numero"]
            ] = item

        except queue.Empty:
            continue

    # Drenagem final da fila
    while True:
        try:
            item = (
                fila_saida.get_nowait()
            )

            recebidos[
                item["numero"]
            ] = item

        except queue.Empty:
            break

    processos_finais = []

    quantidade_erros = 0
    quantidade_tempo_excedido = 0
    novos_alertas = 0

    for cadastro in cadastros:
        numero = cadastro[
            "numero"
        ]

        anterior = mapa_anterior.get(
            numero
        )

        resposta = recebidos.get(
            numero
        )

        # ====================================================
        # TEMPO EXCEDIDO
        # ====================================================

        if resposta is None:
            quantidade_erros += 1
            quantidade_tempo_excedido += 1

            atual = marcar_nao_atualizado(
                cadastro,
                anterior,
                (
                    "Tempo excedido. "
                    "O processo não foi atualizado "
                    "nesta consulta."
                )
            )

            processos_finais.append(
                atual
            )

            print(
                "TEMPO EXCEDIDO:",
                numero
            )

            continue

        # ====================================================
        # ERRO
        # ====================================================

        if not resposta.get(
            "ok",
            False
        ):
            quantidade_erros += 1

            atual = marcar_nao_atualizado(
                cadastro,
                anterior,
                resposta.get(
                    "erro",
                    "Erro na consulta."
                )
            )

            processos_finais.append(
                atual
            )

            print(
                "NÃO ATUALIZADO:",
                numero,
                "-",
                atual["erro"]
            )

            continue

        # ====================================================
        # SUCESSO
        # ====================================================

        atual = resposta[
            "resultado"
        ]

        atual["erro"] = ""

        processos_finais.append(
            atual
        )

        print(
            "OK:",
            numero,
            "|",
            atual.get(
                "situacao",
                ""
            ),
            "|",
            atual.get(
                "setor",
                ""
            ),
            "|",
            atual.get(
                "dataMovimentacao",
                ""
            )
        )

        # ====================================================
        # NOVA MOVIMENTAÇÃO
        # ====================================================

        if dado_anterior_valido(
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
                and
                not alerta_ja_existe(
                    alertas,
                    numero,
                    assinatura_atual
                )
            ):
                alertas.insert(
                    0,
                    criar_alerta(
                        atual,
                        anterior
                    )
                )

                novos_alertas += 1

    agora = agora_iso()

    duracao = round(
        time.monotonic()
        -
        inicio,
        1
    )

    payload = {
        "ultima_verificacao":
            agora,

        "ultima_atualizacao":
            agora,

        "timezone":
            TIMEZONE,

        "duracao_segundos":
            duracao,

        "tempo_excedido":
            (
                quantidade_tempo_excedido
                >
                0
            ),

        "limite_execucao_segundos":
            TEMPO_MAXIMO_EXECUCAO,

        "total_processos":
            len(processos_finais),

        "erros":
            quantidade_erros,

        "processos_nao_atualizados":
            quantidade_erros,

        "processos_tempo_excedido":
            quantidade_tempo_excedido,

        "novos_alertas":
            novos_alertas,

        "processos":
            processos_finais,

        "alertas":
            alertas[:100],
    }

    salvar_payload(
        payload
    )

    print("=" * 60)

    print(
        "dados.json atualizado."
    )

    print(
        "Duração:",
        duracao,
        "segundos"
    )

    print(
        "Total:",
        len(processos_finais)
    )

    print(
        "Não atualizados:",
        quantidade_erros
    )

    print(
        "Tempo excedido:",
        quantidade_tempo_excedido
    )

    print(
        "Novos alertas:",
        novos_alertas
    )

    print("=" * 60)

    return 0


# ============================================================
# INICIAR
# ============================================================

if __name__ == "__main__":
    sys.exit(
        main()
    )
