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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ARQUIVO_DADOS = "dados.json"
ARQUIVO_PROCESSOS = "processos.json"

SEFAZ_BASE_URL = "https://online.sefaz.am.gov.br/processo/"
SEMEF_HOME_URL = "https://sigedweb.manaus.am.gov.br/protonweb/"
SEMEF_DETALHE_URL = "https://sigedweb.manaus.am.gov.br/protonweb/detalhe.aspx"

TIMEZONE = "America/Manaus"
TEMPO_MAXIMO_EXECUCAO = 50
MAX_WORKERS = 10

SEFAZ_CONNECT_TIMEOUT = 4
SEFAZ_READ_TIMEOUT = 8

SEMEF_CONNECT_TIMEOUT = 8
SEMEF_READ_TIMEOUT = 12
SEMEF_MAX_TENTATIVAS = 2
SEMEF_BACKOFF = 0.6

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

SEMEF_PROTOCOLS = {
    "2024.18000.19012.0.008302": "7954846",
    "2026.18000.19951.0.024703": "11442112",
    "2026.18000.19951.0.014382": "11037580",
}


def agora_manaus():
    return datetime.now(ZoneInfo(TIMEZONE))


def agora_iso():
    return agora_manaus().isoformat(timespec="seconds")


def reparar_mojibake(valor):
    if valor is None:
        return ""

    texto = str(valor)

    for _ in range(2):
        if not any(
            item in texto
            for item in ("Ã", "Â", "â€", "ðŸ")
        ):
            break

        try:
            novo = texto.encode("latin1").decode("utf-8")

            if novo == texto:
                break

            texto = novo

        except Exception:
            break

    return texto


def texto_limpo(valor):
    return re.sub(
        r"\s+",
        " ",
        reparar_mojibake(valor),
    ).strip()


def chave_texto(valor):
    texto = unicodedata.normalize(
        "NFD",
        texto_limpo(valor),
    )

    texto = "".join(
        caractere
        for caractere in texto
        if unicodedata.category(caractere) != "Mn"
    )

    return re.sub(
        r"[^a-z0-9]+",
        " ",
        texto.lower(),
    ).strip()


def detectar_origem(numero):
    numero = texto_limpo(numero)

    if re.fullmatch(
        r"\d{4}\.\d{5}\.\d{5}\.\d\.\d{6}",
        numero,
    ):
        return "semef"

    return "sefaz"


def normalizar_origem(valor, numero=""):
    origem = chave_texto(valor)

    if origem in ("semef", "siged"):
        return "semef"

    if origem == "sefaz":
        return "sefaz"

    return detectar_origem(numero)


def url_sefaz(numero):
    return (
        SEFAZ_BASE_URL
        +
        quote(
            numero,
            safe="/",
        )
    )


def url_semef(cod_protocolo):
    return (
        SEMEF_DETALHE_URL
        +
        "?origem=1&cod_protocolo="
        +
        quote(
            str(cod_protocolo)
        )
    )


def carregar_processos():
    if not os.path.exists(ARQUIVO_PROCESSOS):
        raise FileNotFoundError(
            "Arquivo processos.json não encontrado."
        )

    with open(
        ARQUIVO_PROCESSOS,
        "r",
        encoding="utf-8",
    ) as arquivo:
        dados = json.load(arquivo)

    lista = dados.get(
        "processos",
        [],
    )

    if not isinstance(
        lista,
        list,
    ):
        raise ValueError(
            'O campo "processos" precisa ser uma lista.'
        )

    resultado = []
    vistos = set()

    for item in lista:

        if isinstance(item, str):

            numero = texto_limpo(item)

            origem = detectar_origem(numero)

            codigo = (
                SEMEF_PROTOCOLS.get(
                    numero,
                    "",
                )
                if origem == "semef"
                else ""
            )

        elif isinstance(item, dict):

            numero = texto_limpo(
                item.get(
                    "numero",
                    item.get(
                        "processo",
                        "",
                    ),
                )
            )

            origem = normalizar_origem(
                item.get(
                    "origem",
                    "",
                ),
                numero,
            )

            codigo = texto_limpo(
                item.get(
                    "cod_protocolo",
                    item.get(
                        "codProtocolo",
                        "",
                    ),
                )
            )

            if origem == "semef" and not codigo:

                codigo = SEMEF_PROTOCOLS.get(
                    numero,
                    "",
                )

        else:
            continue

        if not numero:
            continue

        if numero in vistos:
            continue

        vistos.add(numero)

        resultado.append(
            {
                "numero": numero,
                "origem": origem,
                "cod_protocolo": codigo,
            }
        )

    if not resultado:
        raise ValueError(
            "Nenhum processo cadastrado."
        )

    return resultado


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
            encoding="utf-8",
        ) as arquivo:

            dados = json.load(
                arquivo
            )

        if not isinstance(
            dados,
            dict,
        ):
            raise ValueError()

        dados.setdefault(
            "processos",
            [],
        )

        dados.setdefault(
            "alertas",
            [],
        )

        return dados

    except Exception:

        return {
            "processos": [],
            "alertas": [],
        }


def criar_mapa_anterior(dados):
    mapa = {}

    for processo in dados.get(
        "processos",
        [],
    ):

        if not isinstance(
            processo,
            dict,
        ):
            continue

        numero = texto_limpo(
            processo.get(
                "numero",
                processo.get(
                    "processo",
                    "",
                ),
            )
        )

        if numero:
            mapa[numero] = processo

    return mapa


def estrutura_vazia(cadastro):
    return {
        "numero":
            cadastro["numero"],

        "origem":
            cadastro["origem"],

        "cod_protocolo":
            cadastro.get(
                "cod_protocolo",
                "",
            ),

        "situacao":
            "",

        "interessado":
            "",

        "assunto":
            "",

        "setor":
            "",

        "evento":
            "",

        "dataMovimentacao":
            "",

        "erro":
            "",

        "consultado_em":
            "",
    }


def marcar_nao_atualizado(
    cadastro,
    anterior,
    motivo,
):
    resultado = estrutura_vazia(
        cadastro
    )

    if isinstance(
        anterior,
        dict,
    ):

        for campo in (
            "situacao",
            "interessado",
            "assunto",
            "setor",
            "evento",
            "dataMovimentacao",
        ):

            valor = anterior.get(
                campo
            )

            if valor not in (
                None,
                "",
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
        texto_limpo(
            motivo
        )
        or
        "Não atualizado"
    )

    return resultado


def criar_sessao():
    sessao = requests.Session()

    sessao.headers.update(
        HEADERS
    )

    return sessao


def criar_sessao_semef():
    sessao = criar_sessao()

    tentativas_extras = max(
        0,
        SEMEF_MAX_TENTATIVAS - 1,
    )

    retry = Retry(
        total=
            tentativas_extras,

        connect=
            tentativas_extras,

        read=
            tentativas_extras,

        status=
            tentativas_extras,

        backoff_factor=
            SEMEF_BACKOFF,

        status_forcelist=(
            429,
            500,
            502,
            503,
            504,
        ),

        allowed_methods=
            frozenset(
                [
                    "GET",
                ]
            ),

        raise_on_status=
            False,
    )

    adapter = HTTPAdapter(
        max_retries=
            retry,

        pool_connections=
            4,

        pool_maxsize=
            4,
    )

    sessao.mount(
        "https://",
        adapter,
    )

    sessao.mount(
        "http://",
        adapter,
    )

    return sessao


def obter_html(
    url,
    connect_timeout,
    read_timeout,
):
    sessao = criar_sessao()

    try:

        resposta = sessao.get(
            url,

            timeout=(
                connect_timeout,
                read_timeout,
            ),

            allow_redirects=
                True,
        )

        resposta.raise_for_status()

        if not resposta.content:

            raise RuntimeError(
                "A página retornada está vazia."
            )

        return resposta.content

    finally:

        sessao.close()


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


def token_invalido_como_valor(
    valor
):
    texto = texto_limpo(
        valor
    )

    return (
        not texto
        or
        texto in (
            ":",
            "-",
            "–",
            "—",
        )
        or
        chave_texto(
            texto
        )
        in
        ROTULOS_CONHECIDOS
    )


def valor_por_rotulo(
    soup,
    rotulos,
):
    alvos = {
        chave_texto(
            rotulo
        )
        for rotulo
        in rotulos
    }

    for linha in soup.find_all(
        "tr"
    ):

        textos = [
            texto_limpo(
                celula.get_text(
                    " ",
                    strip=True,
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

        for indice, texto in enumerate(
            textos
        ):

            if chave_texto(
                texto
            ) in alvos:

                for candidato in textos[
                    indice + 1:
                ]:

                    if not token_invalido_como_valor(
                        candidato
                    ):

                        return candidato

    tokens = [
        texto_limpo(
            item
        )
        for item
        in soup.stripped_strings
    ]

    for indice, token in enumerate(
        tokens
    ):

        if chave_texto(
            token
        ) not in alvos:
            continue

        for candidato in tokens[
            indice + 1:
            indice + 8
        ]:

            if not token_invalido_como_valor(
                candidato
            ):

                return candidato

    return ""


def extrair_campo_sefaz_por_tokens(
    soup,
    rotulo,
    proximos_rotulos,
):
    tokens = [
        texto_limpo(
            item
        )
        for item
        in soup.stripped_strings
    ]

    alvo = chave_texto(
        rotulo
    )

    limites = {
        chave_texto(
            item
        )
        for item
        in proximos_rotulos
    }

    inicio = next(
        (
            indice + 1
            for indice, token
            in enumerate(
                tokens
            )
            if chave_texto(
                token
            )
            ==
            alvo
        ),
        None,
    )

    if inicio is None:
        return ""

    partes = []

    for token in tokens[
        inicio:
    ]:

        chave = chave_texto(
            token
        )

        if chave in limites:
            break

        if token in (
            "",
            ":",
        ):
            continue

        if (
            not partes
            and
            chave in ROTULOS_CONHECIDOS
        ):
            continue

        partes.append(
            token
        )

    return texto_limpo(
        " ".join(
            partes
        )
    )


def cortar_no_primeiro_marcador(
    texto,
    marcadores,
):
    texto = texto_limpo(
        texto
    )

    posicoes = []

    for marcador in marcadores:

        correspondencia = re.search(
            marcador,
            texto,
            flags=re.IGNORECASE,
        )

        if correspondencia:

            posicoes.append(
                correspondencia.start()
            )

    if posicoes:

        texto = texto[
            :min(
                posicoes
            )
        ]

    return texto_limpo(
        texto
    )


def limpar_situacao_sefaz(
    valor
):
    valor = cortar_no_primeiro_marcador(
        valor,
        [
            r"\bAssunto\b",
            r"\bÓrgão\s*/\s*Entidade\b",
            r"\bOrgao\s*/\s*Entidade\b",
            r"\bInteressado\b",
            r"\bCNPJ\b",
        ],
    )

    if token_invalido_como_valor(
        valor
    ):
        return ""

    return valor


def limpar_assunto_sefaz(
    valor
):
    valor = cortar_no_primeiro_marcador(
        valor,
        [
            r"\bÓrgão\s*/\s*Entidade\b",
            r"\bOrgao\s*/\s*Entidade\b",
            r"\bInteressado\b",
            r"\bCNPJ\b",
            r"\bProcesso\s+dispon[ií]vel\b",
        ],
    )

    if token_invalido_como_valor(
        valor
    ):
        return ""

    return valor


def limpar_interessado_sefaz(
    valor
):
    valor = texto_limpo(
        valor
    )

    valor = cortar_no_primeiro_marcador(
        valor,
        [
            r"\bProcesso\s+dispon[ií]vel\b",
            r"\bNova\s+Pesquisa\b",
            r"\bData\s+Setor\s+Evento\b",
        ],
    )

    valor = re.sub(
        r"\bDocumento\s*(?:n[ºo°.]?\s*)?\d+\s*",
        " ",
        valor,
        flags=re.IGNORECASE,
    )

    valor = re.sub(
        r"\bCNPJ\s*:?\s*",
        " ",
        valor,
        flags=re.IGNORECASE,
    )

    valor = re.sub(
        (
            r"\b"
            r"\d{2}\.?"
            r"\d{3}\.?"
            r"\d{3}"
            r"/?"
            r"\d{4}"
            r"-?"
            r"\d{2}"
            r"\b"
        ),
        " ",
        valor,
    )

    valor = re.sub(
        r"\bInteressado\s*:?\s*",
        " ",
        valor,
        flags=re.IGNORECASE,
    )

    valor = texto_limpo(
        valor
    )

    valor = re.sub(
        r"^[\s:;|,\-–—]+",
        "",
        valor,
    ).strip()

    if token_invalido_como_valor(
        valor
    ):
        return ""

    return valor


def extrair_cabecalho_sefaz(
    soup
):
    situacao = (
        extrair_campo_sefaz_por_tokens(
            soup,
            "Situação",
            [
                "Assunto",
                "Órgão/Entidade",
                "Interessado",
            ],
        )
        or
        valor_por_rotulo(
            soup,
            [
                "Situação",
                "Situacao",
            ],
        )
    )

    assunto = (
        extrair_campo_sefaz_por_tokens(
            soup,
            "Assunto",
            [
                "Órgão/Entidade",
                "CNPJ",
                "Interessado",
            ],
        )
        or
        valor_por_rotulo(
            soup,
            [
                "Assunto",
            ],
        )
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
            ],
        )
        or
        valor_por_rotulo(
            soup,
            [
                "Interessado",
            ],
        )
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


def converter_data(
    valor
):
    valor = texto_limpo(
        valor
    )

    for formato in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ):

        try:

            return datetime.strptime(
                valor,
                formato,
            )

        except ValueError:
            pass

    return None


def extrair_movimentacoes_sefaz(
    soup
):
    tabela = None

    for item in soup.find_all(
        "table"
    ):

        texto = chave_texto(
            item.get_text(
                " ",
                strip=True,
            )
        )

        if (
            "data" in texto
            and
            "setor" in texto
            and
            "evento" in texto
        ):

            tabela = item
            break

    if tabela is None:
        return []

    movimentacoes = []

    for linha in tabela.find_all(
        "tr"
    ):

        valores = [
            texto_limpo(
                celula.get_text(
                    " ",
                    strip=True,
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

        data = valores[
            0
        ]

        if not re.fullmatch(
            (
                r"\d{2}/\d{2}/\d{4}"
                r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"
            ),
            data,
        ):

            continue

        movimentacoes.append(
            {
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
            }
        )

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
        )
    ]

    if validas:

        ultima = max(
            validas,
            key=lambda item:
                item[
                    "data_obj"
                ],
        )

    else:

        ultima = movimentacoes[
            0
        ]

    return {
        "data":
            texto_limpo(
                ultima.get(
                    "data",
                    "",
                )
            ),

        "setor":
            texto_limpo(
                ultima.get(
                    "setor",
                    "",
                )
            ),

        "evento":
            texto_limpo(
                ultima.get(
                    "evento",
                    "",
                )
            ),
    }


def consultar_sefaz(
    cadastro
):
    numero = cadastro[
        "numero"
    ]

    conteudo = obter_html(
        url_sefaz(
            numero
        ),
        SEFAZ_CONNECT_TIMEOUT,
        SEFAZ_READ_TIMEOUT,
    )

    soup = BeautifulSoup(
        conteudo,
        "html.parser",
    )

    cabecalho = extrair_cabecalho_sefaz(
        soup
    )

    ultima = ultima_movimentacao_sefaz(
        extrair_movimentacoes_sefaz(
            soup
        )
    )

    situacao = texto_limpo(
        cabecalho.get(
            "situacao",
            "",
        )
    )

    assunto = texto_limpo(
        cabecalho.get(
            "assunto",
            "",
        )
    )

    interessado = limpar_interessado_sefaz(
        cabecalho.get(
            "interessado",
            "",
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

    return {
        "numero":
            numero,

        "origem":
            "sefaz",

        "cod_protocolo":
            "",

        "situacao":
            situacao
            or
            "Não identificada",

        "interessado":
            interessado,

        "assunto":
            assunto,

        "setor":
            ultima.get(
                "setor",
                "",
            ),

        "evento":
            ultima.get(
                "evento",
                "",
            ),

        "dataMovimentacao":
            ultima.get(
                "data",
                "",
            ),

        "erro":
            "",

        "consultado_em":
            agora_iso(),
    }


def resolver_cod_protocolo(
    cadastro
):
    codigo = texto_limpo(
        cadastro.get(
            "cod_protocolo",
            "",
        )
    )

    if codigo:
        return codigo

    codigo = texto_limpo(
        SEMEF_PROTOCOLS.get(
            cadastro[
                "numero"
            ],
            "",
        )
    )

    if codigo:
        return codigo

    raise ValueError(
        "Processo SEMEF sem código de protocolo."
    )


def resposta_semef_parece_valida(
    conteudo
):
    soup = BeautifulSoup(
        conteudo,
        "html.parser",
    )

    texto = chave_texto(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    return (
        "consulta de documentos e processos"
        in texto
        and
        "processo"
        in texto
        and
        "situacao"
        in texto
        and
        (
            "historico do processo"
            in texto
            or
            "despacho movimentacao"
            in texto
        )
    )


def resumo_resposta_semef(
    conteudo
):
    if not conteudo:
        return "Resposta sem conteúdo."

    texto = texto_limpo(
        BeautifulSoup(
            conteudo,
            "html.parser",
        ).get_text(
            " ",
            strip=True,
        )
    )

    if len(
        texto
    ) > 220:

        return (
            texto[
                :220
            ]
            +
            "..."
        )

    return (
        texto
        or
        "Resposta sem texto."
    )


def obter_html_semef(
    cod_protocolo
):
    detalhe_url = url_semef(
        cod_protocolo
    )

    erros = []

    sessao = criar_sessao_semef()

    try:

        # ====================================================
        # 1 - ACESSO DIRETO
        # ====================================================

        try:

            resposta = sessao.get(
                detalhe_url,

                headers={
                    **HEADERS,

                    "Referer":
                        SEMEF_HOME_URL,
                },

                timeout=(
                    SEMEF_CONNECT_TIMEOUT,
                    SEMEF_READ_TIMEOUT,
                ),

                allow_redirects=
                    True,
            )

            resposta.raise_for_status()

            if (
                resposta.content
                and
                resposta_semef_parece_valida(
                    resposta.content
                )
            ):

                return resposta.content

            erros.append(
                (
                    "Acesso direto inválido: "
                    +
                    resumo_resposta_semef(
                        resposta.content
                    )
                )
            )

        except Exception as erro:

            erros.append(
                (
                    "Falha no acesso direto: "
                    +
                    texto_limpo(
                        erro
                    )
                )
            )

        # ====================================================
        # 2 - ABRIR HOME / COOKIES
        # ====================================================

        referer = SEMEF_HOME_URL

        try:

            home = sessao.get(
                SEMEF_HOME_URL,

                headers=
                    HEADERS,

                timeout=(
                    SEMEF_CONNECT_TIMEOUT,
                    SEMEF_READ_TIMEOUT,
                ),

                allow_redirects=
                    True,
            )

            home.raise_for_status()

            referer = (
                home.url
                or
                SEMEF_HOME_URL
            )

        except Exception as erro:

            erros.append(
                (
                    "Falha ao abrir a página inicial: "
                    +
                    texto_limpo(
                        erro
                    )
                )
            )

        # ====================================================
        # 3 - NOVA TENTATIVA COM SESSÃO
        # ====================================================

        try:

            resposta = sessao.get(
                detalhe_url,

                headers={
                    **HEADERS,

                    "Referer":
                        referer,
                },

                timeout=(
                    SEMEF_CONNECT_TIMEOUT,
                    SEMEF_READ_TIMEOUT,
                ),

                allow_redirects=
                    True,
            )

            resposta.raise_for_status()

            if (
                resposta.content
                and
                resposta_semef_parece_valida(
                    resposta.content
                )
            ):

                return resposta.content

            erros.append(
                (
                    "Tentativa com sessão inválida: "
                    +
                    resumo_resposta_semef(
                        resposta.content
                    )
                )
            )

        except Exception as erro:

            erros.append(
                (
                    "Falha na tentativa com sessão: "
                    +
                    texto_limpo(
                        erro
                    )
                )
            )

        detalhe = " | ".join(
            erros
        )

        if len(
            detalhe
        ) > 700:

            detalhe = (
                detalhe[
                    :700
                ]
                +
                "..."
            )

        raise RuntimeError(
            (
                "Não foi possível consultar a SEMEF "
                "após as tentativas disponíveis. "
            )
            +
            (
                detalhe
                or
                "O servidor não respondeu."
            )
        )

    finally:

        sessao.close()


def localizar_valor_semef(
    soup,
    rotulos,
):
    alvos = {
        chave_texto(
            rotulo
        )
        for rotulo
        in rotulos
    }

    for linha in soup.find_all(
        "tr"
    ):

        celulas = [
            texto_limpo(
                celula.get_text(
                    " ",
                    strip=True,
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

        for indice, celula in enumerate(
            celulas
        ):

            if chave_texto(
                celula
            ) in alvos:

                for candidato in celulas[
                    indice + 1:
                ]:

                    if (
                        candidato
                        and
                        not token_invalido_como_valor(
                            candidato
                        )
                    ):

                        return candidato

    return valor_por_rotulo(
        soup,
        rotulos,
    )


def extrair_cabecalho_semef(
    soup
):
    return {
        "numero":
            localizar_valor_semef(
                soup,
                [
                    "Processo",
                ],
            ),

        "data_processo":
            localizar_valor_semef(
                soup,
                [
                    "Data do Processo",
                    "Data Processo",
                ],
            ),

        "situacao":
            localizar_valor_semef(
                soup,
                [
                    "Situação",
                    "Situacao",
                ],
            ),

        "interessado":
            localizar_valor_semef(
                soup,
                [
                    "Interessado",
                ],
            ),

        "assunto":
            localizar_valor_semef(
                soup,
                [
                    "Assunto",
                ],
            ),

        "localizacao":
            localizar_valor_semef(
                soup,
                [
                    "Localização Atual",
                    "Localizacao Atual",
                    "Localização",
                    "Localizacao",
                ],
            ),
    }


def extrair_historico_semef(
    soup
):
    tabela = None

    for item in soup.find_all(
        "table"
    ):

        texto = chave_texto(
            item.get_text(
                " ",
                strip=True,
            )
        )

        if (
            "situacao"
            in texto
            and
            "depto origem"
            in texto
            and
            "depto destino"
            in texto
            and
            "despacho movimentacao"
            in texto
        ):

            tabela = item
            break

    if tabela is None:
        return []

    historico = []

    for linha in tabela.find_all(
        "tr"
    ):

        valores = [
            texto_limpo(
                celula.get_text(
                    " ",
                    strip=True,
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
        ) < 6:

            continue

        if chave_texto(
            valores[0]
        ) == "situacao":

            continue

        situacao = valores[0]

        data = (
            valores[1]
            if len(
                valores
            ) > 1
            else ""
        )

        origem = (
            valores[2]
            if len(
                valores
            ) > 2
            else ""
        )

        desfeito_em = (
            valores[3]
            if len(
                valores
            ) > 3
            else ""
        )

        recebido_em = (
            valores[4]
            if len(
                valores
            ) > 4
            else ""
        )

        destino = (
            valores[5]
            if len(
                valores
            ) > 5
            else ""
        )

        despacho = (
            texto_limpo(
                " ".join(
                    valores[6:]
                )
            )
            if len(
                valores
            ) > 6
            else ""
        )

        data_movimentacao = (
            recebido_em
            or
            data
        )

        data_obj = converter_data(
            data_movimentacao
        )

        if data_obj is None:

            data_movimentacao = data

            data_obj = converter_data(
                data_movimentacao
            )

        if data_obj is None:
            continue

        historico.append(
            {
                "situacao":
                    situacao,

                "data":
                    data,

                "desfeito_em":
                    desfeito_em,

                "recebido_em":
                    recebido_em,

                "dataMovimentacao":
                    data_movimentacao,

                "origem":
                    origem,

                "destino":
                    destino,

                "despacho":
                    despacho,

                "data_obj":
                    data_obj,
            }
        )

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
        )
    ]

    if validos:

        ultima = max(
            validos,
            key=lambda item:
                item[
                    "data_obj"
                ],
        )

    else:

        ultima = historico[
            0
        ]

    return {
        "situacao":
            texto_limpo(
                ultima.get(
                    "situacao",
                    "",
                )
            ),

        "data":
            texto_limpo(
                ultima.get(
                    "dataMovimentacao",
                    "",
                )
            ),

        "origem":
            texto_limpo(
                ultima.get(
                    "origem",
                    "",
                )
            ),

        "destino":
            texto_limpo(
                ultima.get(
                    "destino",
                    "",
                )
            ),

        "despacho":
            texto_limpo(
                ultima.get(
                    "despacho",
                    "",
                )
            ),
    }


def consultar_semef(
    cadastro
):
    numero = cadastro[
        "numero"
    ]

    codigo = resolver_cod_protocolo(
        cadastro
    )

    conteudo = obter_html_semef(
        codigo
    )

    soup = BeautifulSoup(
        conteudo,
        "html.parser",
    )

    cabecalho = extrair_cabecalho_semef(
        soup
    )

    ultima = ultima_movimentacao_semef(
        extrair_historico_semef(
            soup
        )
    )

    numero_encontrado = texto_limpo(
        cabecalho.get(
            "numero",
            "",
        )
    )

    if numero_encontrado:

        numero_esperado = re.sub(
            r"\s+",
            "",
            numero,
        )

        numero_encontrado_normalizado = re.sub(
            r"\s+",
            "",
            numero_encontrado,
        )

        if (
            numero_esperado
            not in
            numero_encontrado_normalizado
        ):

            raise RuntimeError(
                (
                    "A SEMEF retornou um processo diferente: "
                    +
                    numero_encontrado
                )
            )

    situacao = (
        texto_limpo(
            cabecalho.get(
                "situacao",
                "",
            )
        )
        or
        texto_limpo(
            ultima.get(
                "situacao",
                "",
            )
        )
        or
        "Não identificada"
    )

    interessado = texto_limpo(
        cabecalho.get(
            "interessado",
            "",
        )
    )

    assunto = texto_limpo(
        cabecalho.get(
            "assunto",
            "",
        )
    )

    setor = (
        texto_limpo(
            cabecalho.get(
                "localizacao",
                "",
            )
        )
        or
        texto_limpo(
            ultima.get(
                "destino",
                "",
            )
        )
        or
        texto_limpo(
            ultima.get(
                "origem",
                "",
            )
        )
    )

    data_movimentacao = texto_limpo(
        ultima.get(
            "data",
            "",
        )
    )

    evento = texto_limpo(
        ultima.get(
            "despacho",
            "",
        )
    )

    if not any(
        [
            interessado,
            assunto,
            setor,
            data_movimentacao,
            evento,
        ]
    ):

        raise RuntimeError(
            (
                "A SEMEF respondeu, mas não foram "
                "encontrados dados do processo."
            )
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
            evento,

        "dataMovimentacao":
            data_movimentacao,

        "erro":
            "",

        "consultado_em":
            agora_iso(),
    }


def consultar_processo(
    cadastro
):
    if cadastro.get(
        "origem"
    ) == "semef":

        return consultar_semef(
            cadastro
        )

    return consultar_sefaz(
        cadastro
    )


def assinatura_movimentacao(
    processo
):
    if not isinstance(
        processo,
        dict,
    ):
        return ""

    return "|".join(
        [
            texto_limpo(
                processo.get(
                    "dataMovimentacao",
                    "",
                )
            ),

            texto_limpo(
                processo.get(
                    "setor",
                    "",
                )
            ),

            texto_limpo(
                processo.get(
                    "evento",
                    "",
                )
            ),
        ]
    )


def dado_anterior_valido(
    processo
):
    return (
        isinstance(
            processo,
            dict,
        )
        and
        not texto_limpo(
            processo.get(
                "erro",
                "",
            )
        )
        and
        bool(
            assinatura_movimentacao(
                processo
            ).replace(
                "|",
                "",
            )
        )
    )


def alerta_ja_existe(
    alertas,
    numero,
    assinatura,
):
    return any(
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
        for alerta
        in alertas
    )


def criar_alerta(
    atual,
    anterior,
):
    return {
        "numero":
            atual.get(
                "numero",
                "",
            ),

        "origem":
            atual.get(
                "origem",
                "sefaz",
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
                "",
            ),

        "setor":
            atual.get(
                "setor",
                "",
            ),

        "evento":
            atual.get(
                "evento",
                "",
            ),
    }


def worker_consulta(
    fila_entrada,
    fila_saida,
    deadline,
):
    while (
        time.monotonic()
        <
        deadline
    ):

        try:

            cadastro = fila_entrada.get_nowait()

        except queue.Empty:

            return

        numero = cadastro[
            "numero"
        ]

        try:

            fila_saida.put(
                {
                    "numero":
                        numero,

                    "ok":
                        True,

                    "resultado":
                        consultar_processo(
                            cadastro
                        ),
                }
            )

        except Exception as erro:

            fila_saida.put(
                {
                    "numero":
                        numero,

                    "ok":
                        False,

                    "erro":
                        (
                            texto_limpo(
                                erro
                            )
                            or
                            "Erro na consulta."
                        ),
                }
            )

        finally:

            fila_entrada.task_done()


def salvar_payload(
    payload
):
    temporario = (
        ARQUIVO_DADOS
        +
        ".tmp"
    )

    with open(
        temporario,
        "w",
        encoding="utf-8",
    ) as arquivo:

        json.dump(
            payload,
            arquivo,
            ensure_ascii=False,
            indent=2,
        )

        arquivo.write(
            "\n"
        )

    os.replace(
        temporario,
        ARQUIVO_DADOS,
    )


def main():
    inicio = time.monotonic()

    deadline = (
        inicio
        +
        TEMPO_MAXIMO_EXECUCAO
    )

    print(
        "=" * 60
    )

    print(
        "MONITOR SEFAZ-AM + SEMEF"
    )

    print(
        "Início:",
        agora_manaus().strftime(
            "%d/%m/%Y %H:%M:%S"
        ),
    )

    print(
        "Limite global:",
        TEMPO_MAXIMO_EXECUCAO,
        "segundos",
    )

    print(
        "=" * 60
    )

    try:

        cadastros = carregar_processos()

    except Exception as erro:

        print(
            "Erro ao carregar processos.json:",
            erro,
        )

        return 1

    dados_anteriores = carregar_dados_anteriores()

    mapa_anterior = criar_mapa_anterior(
        dados_anteriores
    )

    numeros_ativos = {
        cadastro[
            "numero"
        ]
        for cadastro
        in cadastros
    }

    alertas = [
        alerta
        for alerta
        in dados_anteriores.get(
            "alertas",
            [],
        )
        if alerta.get(
            "numero"
        )
        in numeros_ativos
    ]

    fila_entrada = queue.Queue()
    fila_saida = queue.Queue()

    for cadastro in cadastros:

        fila_entrada.put(
            cadastro
        )

    quantidade_workers = min(
        MAX_WORKERS,
        len(
            cadastros
        ),
    )

    for _ in range(
        quantidade_workers
    ):

        thread = threading.Thread(
            target=
                worker_consulta,

            args=(
                fila_entrada,
                fila_saida,
                deadline,
            ),

            daemon=
                True,
        )

        thread.start()

    recebidos = {}

    while (
        time.monotonic()
        <
        deadline
        and
        len(
            recebidos
        )
        <
        len(
            cadastros
        )
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
                    restante,
                )
            )

            recebidos[
                item[
                    "numero"
                ]
            ] = item

        except queue.Empty:

            continue

    while True:

        try:

            item = fila_saida.get_nowait()

            recebidos[
                item[
                    "numero"
                ]
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
                ),
            )

            processos_finais.append(
                atual
            )

            continue

        if not resposta.get(
            "ok",
            False,
        ):

            quantidade_erros += 1

            atual = marcar_nao_atualizado(
                cadastro,
                anterior,
                resposta.get(
                    "erro",
                    "Erro na consulta.",
                ),
            )

            processos_finais.append(
                atual
            )

            continue

        atual = resposta[
            "resultado"
        ]

        atual[
            "erro"
        ] = ""

        processos_finais.append(
            atual
        )

        if dado_anterior_valido(
            anterior
        ):

            assinatura_anterior = assinatura_movimentacao(
                anterior
            )

            assinatura_atual = assinatura_movimentacao(
                atual
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
                    assinatura_atual,
                )
            ):

                alertas.insert(
                    0,
                    criar_alerta(
                        atual,
                        anterior,
                    ),
                )

                novos_alertas += 1

    agora = agora_iso()

    duracao = round(
        time.monotonic()
        -
        inicio,
        1,
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
            len(
                processos_finais
            ),

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
            alertas[
                :100
            ],
    }

    salvar_payload(
        payload
    )

    print(
        "=" * 60
    )

    print(
        "dados.json atualizado."
    )

    print(
        "Duração:",
        duracao,
        "segundos",
    )

    print(
        "Total:",
        len(
            processos_finais
        ),
    )

    print(
        "Não atualizados:",
        quantidade_erros,
    )

    print(
        "Tempo excedido:",
        quantidade_tempo_excedido,
    )

    print(
        "Novos alertas:",
        novos_alertas,
    )

    print(
        "=" * 60
    )

    return 0


if __name__ == "__main__":

    sys.exit(
        main()
    )
