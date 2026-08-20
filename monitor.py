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

SEFAZ_BASE_URL = (
    "https://online.sefaz.am.gov.br/processo/"
)

SEMEF_BASE_URL = (
    "https://sigedweb.manaus.am.gov.br/"
    "protonweb/detalhe.aspx"
)

TIMEZONE = "America/Manaus"


# ============================================================
# LIMITE GLOBAL DA EXECUÇÃO
# ============================================================

# A execução completa do monitor terá no máximo 50 segundos.
# Processos que não terminarem dentro desse prazo serão
# marcados como "Não atualizado".

TEMPO_MAXIMO_EXECUCAO = 50


# ============================================================
# CONSULTAS SIMULTÂNEAS
# ============================================================

# Número máximo de processos consultados ao mesmo tempo.

MAX_WORKERS = 10


# ============================================================
# TIMEOUTS INDIVIDUAIS
# ============================================================

# SEFAZ-AM
SEFAZ_CONNECT_TIMEOUT = 4
SEFAZ_READ_TIMEOUT = 8

# SEMEF / SIGED
SEMEF_CONNECT_TIMEOUT = 5
SEMEF_READ_TIMEOUT = 8

# A SEMEF terá somente uma tentativa por atualização.
# Isso evita que um processo indisponível segure o monitor.

SEMEF_MAX_TENTATIVAS = 1


# ============================================================
# HEADERS HTTP
# ============================================================

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
        "application/xml;q=0.9,"
        "*/*;q=0.8"
    ),

    "Accept-Language":
        "pt-BR,pt;q=0.9,en;q=0.8",

    "Cache-Control":
        "no-cache",

    "Pragma":
        "no-cache",
}


# ============================================================
# CÓDIGOS DE PROTOCOLO SEMEF CONHECIDOS
# ============================================================

SEMEF_PROTOCOLS = {
    "2024.18000.19012.0.008302":
        "7954846",

    "2026.18000.19951.0.024703":
        "11442112",

    "2026.18000.19951.0.014382":
        "11037580",
}


# ============================================================
# DATA / HORA
# ============================================================

def agora_manaus():
    return datetime.now(
        ZoneInfo(
            TIMEZONE
        )
    )


def agora_iso():
    return agora_manaus().isoformat(
        timespec="seconds"
    )


# ============================================================
# TEXTO
# ============================================================

def reparar_mojibake(valor):
    """
    Corrige problemas de codificação como:

    NÃ£o -> Não
    SituaÃ§Ã£o -> Situação
    AnÃ¡lise -> Análise
    ÓrgÃ£o -> Órgão
    """

    if valor is None:
        return ""

    texto = str(
        valor
    )

    indicadores = (
        "Ã",
        "Â",
        "â€",
        "ðŸ"
    )

    if not any(
        indicador in texto
        for indicador in indicadores
    ):
        return texto

    # Algumas páginas podem chegar
    # com dupla codificação incorreta.

    for _ in range(
        2
    ):

        try:

            corrigido = (
                texto
                .encode(
                    "latin1"
                )
                .decode(
                    "utf-8"
                )
            )

            if corrigido == texto:
                break

            texto = corrigido

        except Exception:
            break

    return texto


def texto_limpo(
    valor
):
    """
    Remove espaços duplicados,
    quebras de linha e também
    corrige problemas de acentuação.
    """

    texto = reparar_mojibake(
        valor
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


def chave_texto(
    valor
):
    """
    Normaliza texto para comparação.

    Exemplo:

    'Órgão/Entidade:' -> 'orgao entidade'
    'SITUAÇÃO'        -> 'situacao'
    """

    texto = texto_limpo(
        valor
    )

    texto = unicodedata.normalize(
        "NFD",
        texto
    )

    texto = "".join(
        caractere
        for caractere
        in texto
        if unicodedata.category(
            caractere
        )
        !=
        "Mn"
    )

    texto = texto.lower()

    texto = re.sub(
        r"[^a-z0-9]+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# IDENTIFICAR ORIGEM
# ============================================================

def detectar_origem(
    numero
):
    """
    Identifica automaticamente se o processo
    pertence à SEMEF ou à SEFAZ.
    """

    numero = texto_limpo(
        numero
    )

    # Exemplo SEMEF:
    # 2026.18000.19951.0.014382

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


def normalizar_origem(
    valor,
    numero=""
):
    origem = chave_texto(
        valor
    )

    if origem in (
        "semef",
        "siged"
    ):
        return "semef"

    if origem == "sefaz":
        return "sefaz"

    return detectar_origem(
        numero
    )


# ============================================================
# URLS
# ============================================================

def url_sefaz(
    numero
):
    return (
        SEFAZ_BASE_URL
        +
        quote(
            numero,
            safe="/"
        )
    )


def url_semef(
    cod_protocolo
):
    return (
        SEMEF_BASE_URL
        +
        "?origem=1"
        +
        "&cod_protocolo="
        +
        quote(
            str(
                cod_protocolo
            )
        )
    )


# ============================================================
# CARREGAR PROCESSOS.JSON
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
        # PROCESSO NO FORMATO SIMPLES
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

            cod_protocolo = (
                SEMEF_PROTOCOLS.get(
                    numero,
                    ""
                )
                if origem == "semef"
                else ""
            )

        # ----------------------------------------------------
        # PROCESSO NO FORMATO COMPLETO
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
            "Nenhum processo cadastrado em processos.json."
        )

    return processos
    # ============================================================
# ESTRUTURA PADRÃO DE UM PROCESSO
# ============================================================

def estrutura_vazia(
    numero,
    origem="sefaz",
    cod_protocolo=""
):
    return {
        "numero":
            texto_limpo(
                numero
            ),

        "origem":
            normalizar_origem(
                origem,
                numero
            ),

        "cod_protocolo":
            texto_limpo(
                cod_protocolo
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


# ============================================================
# CARREGAR DADOS ANTERIORES
# ============================================================

def carregar_dados_anteriores():

    if not os.path.exists(
        ARQUIVO_DADOS
    ):
        return {
            "ultima_verificacao":
                "",

            "processos":
                []
        }

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
            return {
                "ultima_verificacao":
                    "",

                "processos":
                    []
            }

        if not isinstance(
            dados.get(
                "processos",
                []
            ),
            list
        ):
            dados[
                "processos"
            ] = []

        return dados

    except Exception as erro:

        print(
            "Aviso: não foi possível carregar dados.json:",
            erro
        )

        return {
            "ultima_verificacao":
                "",

            "processos":
                []
        }


# ============================================================
# MAPA DOS DADOS ANTERIORES
# ============================================================

def criar_mapa_anterior(
    dados
):

    mapa = {}

    for item in dados.get(
        "processos",
        []
    ):

        if not isinstance(
            item,
            dict
        ):
            continue

        numero = texto_limpo(
            item.get(
                "numero",
                item.get(
                    "processo",
                    ""
                )
            )
        )

        if not numero:
            continue

        mapa[
            numero
        ] = item

    return mapa


# ============================================================
# PRESERVAR DADOS ANTERIORES
# ============================================================

def copiar_dados_anteriores(
    anterior,
    cadastro
):
    """
    Cria uma cópia dos dados anteriores.

    Essa função é importante porque, se uma consulta
    falhar ou exceder o tempo máximo, o monitor não
    apaga as últimas informações válidas do processo.
    """

    numero = texto_limpo(
        cadastro.get(
            "numero",
            ""
        )
    )

    origem = normalizar_origem(
        cadastro.get(
            "origem",
            ""
        ),
        numero
    )

    cod_protocolo = texto_limpo(
        cadastro.get(
            "cod_protocolo",
            ""
        )
    )

    resultado = estrutura_vazia(
        numero,
        origem,
        cod_protocolo
    )

    if isinstance(
        anterior,
        dict
    ):

        campos = (
            "situacao",
            "interessado",
            "assunto",
            "setor",
            "evento",
            "dataMovimentacao",
            "consultado_em",
        )

        for campo in campos:

            valor = anterior.get(
                campo,
                ""
            )

            if valor not in (
                None,
                ""
            ):
                resultado[
                    campo
                ] = valor

        # Compatibilidade com versões anteriores
        # do dados.json.

        if (
            not resultado[
                "dataMovimentacao"
            ]
        ):

            resultado[
                "dataMovimentacao"
            ] = texto_limpo(
                anterior.get(
                    "data_movimentacao",
                    ""
                )
            )

        if (
            not resultado[
                "consultado_em"
            ]
        ):

            resultado[
                "consultado_em"
            ] = texto_limpo(
                anterior.get(
                    "consultadoEm",
                    ""
                )
            )

    resultado[
        "erro"
    ] = ""

    return resultado


# ============================================================
# MARCAR PROCESSO NÃO ATUALIZADO
# ============================================================

def marcar_nao_atualizado(
    cadastro,
    anterior=None,
    motivo="Não atualizado"
):
    """
    Mantém os últimos dados válidos e adiciona um erro.

    O index.html poderá usar o campo "erro" para destacar
    esse processo em vermelho e colocá-lo no final da lista.
    """

    resultado = copiar_dados_anteriores(
        anterior or {},
        cadastro
    )

    resultado[
        "erro"
    ] = texto_limpo(
        motivo
    ) or "Não atualizado"

    return resultado


# ============================================================
# SALVAR DADOS.JSON
# ============================================================

def salvar_dados(
    processos,
    inicio_execucao,
    tempo_excedido=False
):

    agora = agora_iso()

    payload = {
        "ultima_verificacao":
            agora,

        "ultima_atualizacao":
            agora,

        "tempo_excedido":
            bool(
                tempo_excedido
            ),

        "limite_execucao_segundos":
            TEMPO_MAXIMO_EXECUCAO,

        "processos":
            processos
    }

    arquivo_temporario = (
        ARQUIVO_DADOS
        +
        ".tmp"
    )

    with open(
        arquivo_temporario,
        "w",
        encoding="utf-8"
    ) as arquivo:

        json.dump(
            payload,
            arquivo,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        arquivo_temporario,
        ARQUIVO_DADOS
    )

    duracao = (
        time.monotonic()
        -
        inicio_execucao
    )

    print(
        "dados.json salvo com sucesso."
    )

    print(
        "Tempo total:",
        f"{duracao:.1f}",
        "segundos"
    )

    print(
        "Limite global:",
        TEMPO_MAXIMO_EXECUCAO,
        "segundos"
    )


# ============================================================
# TEMPO RESTANTE DA EXECUÇÃO
# ============================================================

def tempo_restante(
    inicio_execucao
):

    decorrido = (
        time.monotonic()
        -
        inicio_execucao
    )

    restante = (
        TEMPO_MAXIMO_EXECUCAO
        -
        decorrido
    )

    return max(
        0,
        restante
    )


def limite_global_atingido(
    inicio_execucao
):

    return (
        tempo_restante(
            inicio_execucao
        )
        <=
        0
    )


# ============================================================
# SESSÃO HTTP
# ============================================================

def criar_sessao():

    sessao = requests.Session()

    sessao.headers.update(
        HEADERS
    )

    return sessao


# ============================================================
# DOWNLOAD SEFAZ
# ============================================================

def baixar_url_sefaz(
    numero
):

    url = url_sefaz(
        numero
    )

    sessao = criar_sessao()

    try:

        resposta = sessao.get(
            url,
            timeout=(
                SEFAZ_CONNECT_TIMEOUT,
                SEFAZ_READ_TIMEOUT
            ),
            allow_redirects=True
        )

        resposta.raise_for_status()

        # A página da SEFAZ pode não informar
        # corretamente o charset no cabeçalho.

        if (
            not resposta.encoding
            or
            resposta.encoding.lower()
            in (
                "iso-8859-1",
                "latin-1"
            )
        ):

            aparente = (
                resposta.apparent_encoding
            )

            if aparente:
                resposta.encoding = (
                    aparente
                )

        html = resposta.text

        if not html:
            raise RuntimeError(
                "A SEFAZ retornou uma página vazia."
            )

        return html

    finally:

        sessao.close()


# ============================================================
# EXTRAÇÃO DE CAMPOS HTML
# ============================================================

def extrair_campos_tabela(
    soup
):
    """
    Lê pares de células de tabelas.

    Exemplo:

    Situação | Em análise
    Assunto  | Restituição
    """

    campos = {}

    for linha in soup.find_all(
        "tr"
    ):

        celulas = linha.find_all(
            [
                "td",
                "th"
            ]
        )

        textos = [
            texto_limpo(
                celula.get_text(
                    " ",
                    strip=True
                )
            )
            for celula
            in celulas
        ]

        textos = [
            texto
            for texto
            in textos
            if texto
        ]

        if len(
            textos
        ) < 2:
            continue

        chave = chave_texto(
            textos[0]
        )

        valor = texto_limpo(
            " ".join(
                textos[
                    1:
                ]
            )
        )

        if (
            chave
            and
            valor
            and
            chave not in campos
        ):
            campos[
                chave
            ] = valor

    return campos


# ============================================================
# LOCALIZAR VALOR POR RÓTULO
# ============================================================

def localizar_valor(
    campos,
    nomes
):

    nomes_normalizados = [
        chave_texto(
            nome
        )
        for nome
        in nomes
    ]

    # Primeiro procura correspondência exata.

    for nome in nomes_normalizados:

        if nome in campos:

            valor = texto_limpo(
                campos[
                    nome
                ]
            )

            if valor:
                return valor

    # Depois aceita rótulos um pouco diferentes.

    for chave, valor in campos.items():

        chave_normalizada = chave_texto(
            chave
        )

        for nome in nomes_normalizados:

            if (
                nome
                and
                (
                    chave_normalizada.startswith(
                        nome
                    )
                    or
                    nome.startswith(
                        chave_normalizada
                    )
                )
            ):

                valor = texto_limpo(
                    valor
                )

                if valor:
                    return valor

    return ""


# ============================================================
# IDENTIFICAR DATA
# ============================================================

PADRAO_DATA = re.compile(
    r"\b"
    r"\d{2}/\d{2}/\d{4}"
    r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"
    r"\b"
)


def extrair_data_texto(
    texto
):

    texto = texto_limpo(
        texto
    )

    correspondencia = (
        PADRAO_DATA.search(
            texto
        )
    )

    if not correspondencia:
        return ""

    return correspondencia.group(
        0
    )


# ============================================================
# NORMALIZAR DATA PARA COMPARAÇÃO
# ============================================================

def converter_data(
    valor
):

    valor = texto_limpo(
        valor
    )

    if not valor:
        return None

    formatos = (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    )

    for formato in formatos:

        try:

            return datetime.strptime(
                valor,
                formato
            )

        except ValueError:
            pass

    return None


# ============================================================
# EXTRAIR MOVIMENTAÇÕES DE TABELAS
# ============================================================

def extrair_movimentacoes(
    soup
):

    movimentacoes = []

    for tabela in soup.find_all(
        "table"
    ):

        for linha in tabela.find_all(
            "tr"
        ):

            celulas = linha.find_all(
                [
                    "td",
                    "th"
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
                for celula
                in celulas
            ]

            textos = [
                texto
                for texto
                in textos
                if texto
            ]

            if not textos:
                continue

            texto_linha = texto_limpo(
                " — ".join(
                    textos
                )
            )

            data = extrair_data_texto(
                texto_linha
            )

            if not data:
                continue

            # Evita considerar cabeçalhos
            # ou linhas sem informação útil.

            evento_partes = []

            data_removida = False

            for texto in textos:

                if (
                    not data_removida
                    and
                    data in texto
                ):

                    texto_sem_data = texto_limpo(
                        texto.replace(
                            data,
                            "",
                            1
                        )
                    )

                    data_removida = True

                    if texto_sem_data:
                        evento_partes.append(
                            texto_sem_data
                        )

                else:

                    evento_partes.append(
                        texto
                    )

            evento = texto_limpo(
                " — ".join(
                    evento_partes
                )
            )

            if not evento:
                evento = texto_linha

            movimentacoes.append({
                "data":
                    data,

                "evento":
                    evento,

                "data_obj":
                    converter_data(
                        data
                    )
            })

    return movimentacoes


# ============================================================
# ESCOLHER MOVIMENTAÇÃO MAIS RECENTE
# ============================================================

def movimentacao_mais_recente(
    movimentacoes
):

    if not movimentacoes:
        return {
            "data":
                "",

            "evento":
                ""
        }

    validas = [
        item
        for item
        in movimentacoes
        if item.get(
            "data_obj"
        )
        is not None
    ]

    if validas:

        mais_recente = max(
            validas,
            key=lambda item:
                item[
                    "data_obj"
                ]
        )

    else:

        mais_recente = (
            movimentacoes[
                0
            ]
        )

    return {
        "data":
            texto_limpo(
                mais_recente.get(
                    "data",
                    ""
                )
            ),

        "evento":
            texto_limpo(
                mais_recente.get(
                    "evento",
                    ""
                )
            )
    }
    # ============================================================
# LIMPEZA ESPECÍFICA DA SEFAZ
# ============================================================

def cortar_no_primeiro_marcador(
    texto,
    marcadores
):
    texto = texto_limpo(
        texto
    )

    if not texto:
        return ""

    menor_posicao = None

    for marcador in marcadores:

        correspondencia = re.search(
            marcador,
            texto,
            flags=re.IGNORECASE
        )

        if not correspondencia:
            continue

        posicao = correspondencia.start()

        if (
            menor_posicao is None
            or
            posicao < menor_posicao
        ):
            menor_posicao = posicao

    if menor_posicao is not None:
        texto = texto[
            :menor_posicao
        ]

    return texto_limpo(
        texto
    )


def limpar_situacao_sefaz(
    valor
):
    return cortar_no_primeiro_marcador(
        valor,
        [
            r"\bAssunto\b",
            r"\bÓrgão\s*/\s*Entidade\b",
            r"\bOrgao\s*/\s*Entidade\b",
            r"\bInteressado\b",
            r"\bCNPJ\b",
        ]
    )


def limpar_assunto_sefaz(
    valor
):
    return cortar_no_primeiro_marcador(
        valor,
        [
            r"\bÓrgão\s*/\s*Entidade\b",
            r"\bOrgao\s*/\s*Entidade\b",
            r"\bInteressado\b",
            r"\bCNPJ\b",
            r"\bProcesso\s+dispon[ií]vel\b",
        ]
    )


def limpar_interessado_sefaz(
    valor
):
    return cortar_no_primeiro_marcador(
        valor,
        [
            r"\bProcesso\s+dispon[ií]vel\b",
            r"\bNova\s+Pesquisa\b",
            r"\bData\s+Setor\s+Evento\b",
        ]
    )


# ============================================================
# EXTRAÇÃO POR TEXTO COMPLETO DA SEFAZ
# ============================================================

def extrair_por_regex(
    texto,
    padrao
):
    correspondencia = re.search(
        padrao,
        texto,
        flags=re.IGNORECASE
    )

    if not correspondencia:
        return ""

    return texto_limpo(
        correspondencia.group(
            1
        )
    )


def extrair_cabecalho_sefaz(
    soup
):
    """
    Extrai somente os campos corretos do cabeçalho da SEFAZ.

    Prioridade:
    1. estrutura de tabelas;
    2. regex sobre o texto completo;
    3. limpeza final.
    """

    campos = extrair_campos_tabela(
        soup
    )

    situacao = localizar_valor(
        campos,
        [
            "Situação",
            "Situacao"
        ]
    )

    assunto = localizar_valor(
        campos,
        [
            "Assunto"
        ]
    )

    interessado = localizar_valor(
        campos,
        [
            "Interessado"
        ]
    )

    texto = texto_limpo(
        soup.get_text(
            " ",
            strip=True
        )
    )

    # --------------------------------------------------------
    # SITUAÇÃO
    # --------------------------------------------------------

    if not situacao:

        situacao = extrair_por_regex(
            texto,
            (
                r"Situa(?:ç|c)(?:ã|a)o\s*:?\s*"
                r"(.*?)"
                r"(?="
                r"\s+Assunto\s*:?"
                r"|\s+[ÓO]rg(?:ã|a)o\s*/\s*Entidade\s*:?"
                r"|\s+Interessado\s*:?"
                r"|$"
                r")"
            )
        )

    # --------------------------------------------------------
    # ASSUNTO
    # --------------------------------------------------------

    if not assunto:

        assunto = extrair_por_regex(
            texto,
            (
                r"Assunto\s*:?\s*"
                r"(.*?)"
                r"(?="
                r"\s+[ÓO]rg(?:ã|a)o\s*/\s*Entidade\s*:?"
                r"|\s+CNPJ\s*:?"
                r"|\s+Interessado\s*:?"
                r"|$"
                r")"
            )
        )

    # --------------------------------------------------------
    # INTERESSADO
    # --------------------------------------------------------

    if not interessado:

        interessado = extrair_por_regex(
            texto,
            (
                r"Interessado\s*:?\s*"
                r"(.*?)"
                r"(?="
                r"\s+Processo\s+dispon[ií]vel"
                r"|\s+Nova\s+Pesquisa"
                r"|\s+Data\s+Setor\s+Evento"
                r"|$"
                r")"
            )
        )

    situacao = limpar_situacao_sefaz(
        situacao
    )

    assunto = limpar_assunto_sefaz(
        assunto
    )

    interessado = limpar_interessado_sefaz(
        interessado
    )

    return {
        "situacao":
            situacao,

        "assunto":
            assunto,

        "interessado":
            interessado,
    }


# ============================================================
# LOCALIZAR TABELA DE MOVIMENTAÇÕES SEFAZ
# ============================================================

def encontrar_tabela_movimentacoes_sefaz(
    soup
):
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
            return tabela

    return None


# ============================================================
# EXTRAIR MOVIMENTAÇÕES DA SEFAZ
# ============================================================

def extrair_movimentacoes_sefaz(
    soup
):
    tabela = (
        encontrar_tabela_movimentacoes_sefaz(
            soup
        )
    )

    if tabela is None:

        print(
            "Aviso: tabela de movimentações "
            "da SEFAZ não encontrada."
        )

        return []

    movimentacoes = []

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

        # Ignora cabeçalho.

        if (
            chave_texto(
                valores[0]
            )
            ==
            "data"
        ):
            continue

        data = texto_limpo(
            valores[0]
        )

        if not re.match(
            r"^\d{2}/\d{2}/\d{4}"
            r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$",
            data
        ):
            continue

        setor = texto_limpo(
            valores[1]
        )

        evento = texto_limpo(
            " ".join(
                valores[2:]
            )
        )

        movimentacoes.append({
            "data":
                data,

            "setor":
                setor,

            "evento":
                evento,

            "data_obj":
                converter_data(
                    data
                ),
        })

    return movimentacoes


# ============================================================
# MOVIMENTAÇÃO MAIS RECENTE SEFAZ
# ============================================================

def movimentacao_mais_recente_sefaz(
    movimentacoes
):
    if not movimentacoes:

        return {
            "data":
                "",

            "setor":
                "",

            "evento":
                ""
        }

    validas = [
        item
        for item
        in movimentacoes
        if item.get(
            "data_obj"
        )
        is not None
    ]

    if validas:

        ultima = max(
            validas,
            key=lambda item:
                item[
                    "data_obj"
                ]
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
# CONSULTAR PROCESSO SEFAZ
# ============================================================

def consultar_sefaz(
    cadastro
):
    numero = texto_limpo(
        cadastro.get(
            "numero",
            ""
        )
    )

    html = baixar_url_sefaz(
        numero
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

    ultima = (
        movimentacao_mais_recente_sefaz(
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

    interessado = texto_limpo(
        cabecalho.get(
            "interessado",
            ""
        )
    )

    if not situacao:
        situacao = (
            "Não identificada"
        )

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
# DOWNLOAD SEMEF / SIGED
# ============================================================

def baixar_url_semef(
    cod_protocolo
):
    url = url_semef(
        cod_protocolo
    )

    ultimo_erro = None

    for tentativa in range(
        1,
        SEMEF_MAX_TENTATIVAS + 1
    ):

        sessao = criar_sessao()

        try:

            resposta = sessao.get(
                url,
                timeout=(
                    SEMEF_CONNECT_TIMEOUT,
                    SEMEF_READ_TIMEOUT
                ),
                allow_redirects=True
            )

            resposta.raise_for_status()

            if (
                not resposta.encoding
                or
                resposta.encoding.lower()
                in (
                    "iso-8859-1",
                    "latin-1"
                )
            ):

                aparente = (
                    resposta.apparent_encoding
                )

                if aparente:
                    resposta.encoding = (
                        aparente
                    )

            html = resposta.text

            if not texto_limpo(
                html
            ):
                raise RuntimeError(
                    "A SEMEF retornou uma página vazia."
                )

            return html

        except Exception as erro:

            ultimo_erro = erro

            print(
                "Falha SEMEF:",
                tentativa,
                "/",
                SEMEF_MAX_TENTATIVAS,
                "-",
                erro
            )

        finally:

            sessao.close()

    raise RuntimeError(
        "Não foi possível consultar a SEMEF: "
        +
        texto_limpo(
            ultimo_erro
        )
    )


# ============================================================
# RESOLVER CÓDIGO DE PROTOCOLO SEMEF
# ============================================================

def resolver_cod_protocolo(
    cadastro
):
    numero = texto_limpo(
        cadastro.get(
            "numero",
            ""
        )
    )

    codigo = texto_limpo(
        cadastro.get(
            "cod_protocolo",
            ""
        )
    )

    if codigo:
        return codigo

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


# ============================================================
# EXTRAIR CABEÇALHO SEMEF
# ============================================================

def extrair_cabecalho_semef(
    soup
):
    campos = extrair_campos_tabela(
        soup
    )

    processo = localizar_valor(
        campos,
        [
            "Processo"
        ]
    )

    situacao = localizar_valor(
        campos,
        [
            "Situação",
            "Situacao"
        ]
    )

    interessado = localizar_valor(
        campos,
        [
            "Interessado"
        ]
    )

    assunto = localizar_valor(
        campos,
        [
            "Assunto"
        ]
    )

    localizacao = localizar_valor(
        campos,
        [
            "Localização Atual",
            "Localizacao Atual"
        ]
    )

    return {
        "numero":
            processo,

        "situacao":
            situacao,

        "interessado":
            interessado,

        "assunto":
            assunto,

        "localizacao":
            localizacao,
    }


# ============================================================
# ENCONTRAR HISTÓRICO SEMEF
# ============================================================

def encontrar_tabela_historico_semef(
    soup
):
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
            "situacao" in texto
            and
            "data" in texto
            and
            "despacho" in texto
        ):
            return tabela

    return None


# ============================================================
# EXTRAIR HISTÓRICO SEMEF
# ============================================================

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
            "Aviso: histórico da SEMEF "
            "não encontrado."
        )

        return []

    historico = []

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
        ) < 2:
            continue

        data = texto_limpo(
            valores[1]
        )

        if not re.match(
            r"^\d{2}/\d{2}/\d{4}"
            r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$",
            data
        ):
            continue

        situacao = (
            texto_limpo(
                valores[0]
            )
            if len(
                valores
            ) > 0
            else ""
        )

        origem = (
            texto_limpo(
                valores[2]
            )
            if len(
                valores
            ) > 2
            else ""
        )

        destino = (
            texto_limpo(
                valores[5]
            )
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
    # ============================================================
# MOVIMENTAÇÃO MAIS RECENTE SEMEF
# ============================================================

def movimentacao_mais_recente_semef(
    historico
):
    if not historico:

        return {
            "situacao":
                "",

            "data":
                "",

            "origem":
                "",

            "destino":
                "",

            "despacho":
                ""
        }

    validos = [
        item
        for item
        in historico
        if item.get(
            "data_obj"
        )
        is not None
    ]

    if validos:

        ultima = max(
            validos,
            key=lambda item:
                item[
                    "data_obj"
                ]
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
                    ""
                )
            ),

        "data":
            texto_limpo(
                ultima.get(
                    "data",
                    ""
                )
            ),

        "origem":
            texto_limpo(
                ultima.get(
                    "origem",
                    ""
                )
            ),

        "destino":
            texto_limpo(
                ultima.get(
                    "destino",
                    ""
                )
            ),

        "despacho":
            texto_limpo(
                ultima.get(
                    "despacho",
                    ""
                )
            ),
    }


# ============================================================
# CONSULTAR PROCESSO SEMEF
# ============================================================

def consultar_semef(
    cadastro
):
    numero = texto_limpo(
        cadastro.get(
            "numero",
            ""
        )
    )

    cod_protocolo = (
        resolver_cod_protocolo(
            cadastro
        )
    )

    html = baixar_url_semef(
        cod_protocolo
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

    ultima = (
        movimentacao_mais_recente_semef(
            historico
        )
    )

    numero_encontrado = texto_limpo(
        cabecalho.get(
            "numero",
            ""
        )
    )

    if (
        numero_encontrado
        and
        numero_encontrado != numero
    ):
        raise RuntimeError(
            "O código do protocolo retornou "
            "um processo diferente do cadastrado."
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

    return {
        "numero":
            numero,

        "origem":
            "semef",

        "cod_protocolo":
            cod_protocolo,

        "situacao":
            situacao,

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


# ============================================================
# CONSULTA POR ORIGEM
# ============================================================

def consultar_processo(
    cadastro
):
    origem = normalizar_origem(
        cadastro.get(
            "origem",
            ""
        ),
        cadastro.get(
            "numero",
            ""
        )
    )

    if origem == "semef":

        return consultar_semef(
            cadastro
        )

    return consultar_sefaz(
        cadastro
    )


# ============================================================
# ASSINATURA DA MOVIMENTAÇÃO
# ============================================================

def assinatura_movimentacao(
    processo
):
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


# ============================================================
# VERIFICAR DADO ANTERIOR VÁLIDO
# ============================================================

def dado_anterior_valido(
    processo
):
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

    assinatura = (
        assinatura_movimentacao(
            processo
        )
    )

    return bool(
        assinatura.replace(
            "|",
            ""
        )
    )


# ============================================================
# ALERTAS
# ============================================================

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
# WORKER DE CONSULTA
# ============================================================

def worker_consulta(
    fila_entrada,
    fila_saida,
    inicio_execucao
):
    while True:

        if limite_global_atingido(
            inicio_execucao
        ):
            return

        try:

            cadastro = fila_entrada.get_nowait()

        except queue.Empty:

            return

        numero = cadastro.get(
            "numero",
            ""
        )

        try:

            resultado = (
                consultar_processo(
                    cadastro
                )
            )

            fila_saida.put({
                "numero":
                    numero,

                "ok":
                    True,

                "resultado":
                    resultado,
            })

        except Exception as erro:

            fila_saida.put({
                "numero":
                    numero,

                "ok":
                    False,

                "erro":
                    texto_limpo(
                        erro
                    )
                    or
                    "Erro na consulta.",
            })

        finally:

            fila_entrada.task_done()


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main():

    inicio_execucao = (
        time.monotonic()
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
        )
    )

    print(
        "Limite global:",
        TEMPO_MAXIMO_EXECUCAO,
        "segundos"
    )

    print(
        "=" * 60
    )

    # --------------------------------------------------------
    # CARREGAR PROCESSOS
    # --------------------------------------------------------

    try:

        cadastros = (
            carregar_processos()
        )

    except Exception as erro:

        print(
            "Erro ao carregar processos.json:",
            erro
        )

        return 1

    print(
        "Processos cadastrados:",
        len(
            cadastros
        )
    )

    # --------------------------------------------------------
    # DADOS ANTERIORES
    # --------------------------------------------------------

    dados_anteriores = (
        carregar_dados_anteriores()
    )

    mapa_anterior = (
        criar_mapa_anterior(
            dados_anteriores
        )
    )

    numeros_ativos = {
        cadastro.get(
            "numero",
            ""
        )
        for cadastro
        in cadastros
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
        )
        in numeros_ativos
    ]

    # --------------------------------------------------------
    # FILAS
    # --------------------------------------------------------

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
        )
    )

    threads = []

    # --------------------------------------------------------
    # INICIAR WORKERS
    # --------------------------------------------------------

    for _ in range(
        quantidade_workers
    ):

        thread = threading.Thread(
            target=worker_consulta,
            args=(
                fila_entrada,
                fila_saida,
                inicio_execucao
            ),
            daemon=True
        )

        thread.start()

        threads.append(
            thread
        )

    # --------------------------------------------------------
    # RECEBER RESULTADOS
    # --------------------------------------------------------

    recebidos = {}

    while True:

        if len(
            recebidos
        ) >= len(
            cadastros
        ):
            break

        restante = (
            tempo_restante(
                inicio_execucao
            )
        )

        if restante <= 0:
            break

        try:

            item = fila_saida.get(
                timeout=min(
                    0.5,
                    restante
                )
            )

            numero = item.get(
                "numero",
                ""
            )

            if numero:

                recebidos[
                    numero
                ] = item

        except queue.Empty:

            continue

    # --------------------------------------------------------
    # DRENAGEM FINAL DA FILA
    # --------------------------------------------------------

    while True:

        try:

            item = (
                fila_saida.get_nowait()
            )

            numero = item.get(
                "numero",
                ""
            )

            if numero:

                recebidos[
                    numero
                ] = item

        except queue.Empty:

            break

    # --------------------------------------------------------
    # CONSTRUIR RESULTADO FINAL
    # --------------------------------------------------------

    processos_finais = []

    quantidade_erros = 0

    quantidade_tempo_excedido = 0

    novos_alertas = 0

    for cadastro in cadastros:

        numero = cadastro.get(
            "numero",
            ""
        )

        anterior = mapa_anterior.get(
            numero
        )

        resposta = recebidos.get(
            numero
        )

        # ----------------------------------------------------
        # NÃO TERMINOU DENTRO DO PRAZO
        # ----------------------------------------------------

        if resposta is None:

            quantidade_erros += 1

            quantidade_tempo_excedido += 1

            processo = marcar_nao_atualizado(
                cadastro,
                anterior,
                (
                    "Tempo excedido. "
                    "O processo não foi atualizado "
                    "nesta consulta."
                )
            )

            processos_finais.append(
                processo
            )

            print(
                "TEMPO EXCEDIDO:",
                numero
            )

            continue

        # ----------------------------------------------------
        # TERMINOU COM ERRO
        # ----------------------------------------------------

        if not resposta.get(
            "ok",
            False
        ):

            quantidade_erros += 1

            processo = marcar_nao_atualizado(
                cadastro,
                anterior,
                resposta.get(
                    "erro",
                    "Erro na consulta."
                )
            )

            processos_finais.append(
                processo
            )

            print(
                "NÃO ATUALIZADO:",
                numero,
                "-",
                resposta.get(
                    "erro",
                    ""
                )
            )

            continue

        # ----------------------------------------------------
        # CONSULTA REALIZADA COM SUCESSO
        # ----------------------------------------------------

        atual = resposta.get(
            "resultado",
            {}
        )

        atual[
            "erro"
        ] = ""

        processos_finais.append(
            atual
        )

        print(
            "OK:",
            numero,
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

        # ----------------------------------------------------
        # VERIFICAR NOVA MOVIMENTAÇÃO
        # ----------------------------------------------------

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
            ):

                if not alerta_ja_existe(
                    alertas,
                    numero,
                    assinatura_atual
                ):

                    alerta = criar_alerta(
                        atual,
                        anterior
                    )

                    alertas.insert(
                        0,
                        alerta
                    )

                    novos_alertas += 1

                    print(
                        "NOVA MOVIMENTAÇÃO:",
                        numero
                    )

    # --------------------------------------------------------
    # STATUS DO LIMITE GLOBAL
    # --------------------------------------------------------

    tempo_excedido = (
        quantidade_tempo_excedido
        >
        0
    )

    # --------------------------------------------------------
    # PAYLOAD FINAL
    # --------------------------------------------------------

    agora = agora_iso()

    payload = {
        "ultima_verificacao":
            agora,

        "ultima_atualizacao":
            agora,

        "timezone":
            TIMEZONE,

        "tempo_excedido":
            tempo_excedido,

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

    # --------------------------------------------------------
    # SALVAR COM SEGURANÇA
    # --------------------------------------------------------

    arquivo_temporario = (
        ARQUIVO_DADOS
        +
        ".tmp"
    )

    with open(
        arquivo_temporario,
        "w",
        encoding="utf-8"
    ) as arquivo:

        json.dump(
            payload,
            arquivo,
            ensure_ascii=False,
            indent=2
        )

        arquivo.write(
            "\n"
        )

    os.replace(
        arquivo_temporario,
        ARQUIVO_DADOS
    )

    # --------------------------------------------------------
    # RESUMO
    # --------------------------------------------------------

    duracao = (
        time.monotonic()
        -
        inicio_execucao
    )

    print(
        "=" * 60
    )

    print(
        "dados.json atualizado."
    )

    print(
        "Duração:",
        f"{duracao:.1f}",
        "segundos"
    )

    print(
        "Total:",
        len(
            processos_finais
        )
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

    print(
        "=" * 60
    )

    return 0


# ============================================================
# INICIAR
# ============================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )
