import json

import os

import re

import sys

import time

import unicodedata

from concurrent.futures import ThreadPoolExecutor, as_completed

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

SEMEF_BASE_URL = (

    "https://sigedweb.manaus.am.gov.br/"

    "protonweb/detalhe.aspx"

)

# Consulta rápida para não segurar o monitor

SEFAZ_CONNECT_TIMEOUT = 8

SEFAZ_READ_TIMEOUT = 15

SEMEF_CONNECT_TIMEOUT = 8

SEMEF_READ_TIMEOUT = 15

SEMEF_MAX_TENTATIVAS = 2

SEMEF_ESPERA = 2

# Quantos processos podem ser consultados simultaneamente

MAX_WORKERS = 8

HEADERS = {

    "User-Agent": (

        "Mozilla/5.0 "

        "(iPhone; CPU iPhone OS 18_0 like Mac OS X) "

        "AppleWebKit/605.1.15 "

        "(KHTML, like Gecko) "

        "Version/18.0 Mobile/15E148 Safari/604.1"

    ),

    "Accept": (

        "text/html,application/xhtml+xml,"

        "application/xml;q=0.9,*/*;q=0.8"

    ),

    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",

    "Cache-Control": "no-cache",

    "Pragma": "no-cache",

}

# ============================================================

# CÓDIGOS SEMEF CONHECIDOS

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

        ZoneInfo("America/Manaus")

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

    Corrige textos como:

    NÃ£o -> Não

    SituaÃ§Ã£o -> Situação

    ÓrgÃ£o -> Órgão

    """

    if valor is None:

        return ""

    texto = str(valor)

    if not any(

        sinal in texto

        for sinal in (

            "Ã",

            "Â",

            "â€",

            "ðŸ"

        )

    ):

        return texto

    try:

        corrigido = texto.encode(

            "latin1"

        ).decode(

            "utf-8"

        )

        return corrigido

    except Exception:

        return texto

def texto_limpo(valor):

    texto = reparar_mojibake(

        valor

    )

    return re.sub(

        r"\s+",

        " ",

        texto

    ).strip()

def chave_texto(valor):

    """

    Normaliza texto para comparação:

    SITUAÇÃO -> situacao

    ÓRGÃO/ENTIDADE -> orgao entidade

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

def normalizar_origem(valor):

    origem = chave_texto(

        valor

    )

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

# ============================================================

# URLs

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

            continue

        vistos.add(

            numero

        )

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

# DADOS.JSON

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

        arquivo.write(

            "\n"

        )

# ============================================================

# REQUISIÇÃO

# ============================================================

def baixar(

    url,

    connect_timeout,

    read_timeout

):

    resposta = requests.get(

        url,

        headers=HEADERS,

        timeout=(

            connect_timeout,

            read_timeout

        ),

        allow_redirects=True

    )

    resposta.raise_for_status()

    # Usamos bytes diretamente.

    # O BeautifulSoup detecta melhor o charset da página.

    return (

        resposta.content,

        resposta.url

    )

# ============================================================

# FUNÇÕES DE EXTRAÇÃO POR RÓTULO

# ============================================================

def valor_apos_rotulo(

    soup,

    nomes

):

    """

    Procura uma célula com um rótulo

    e devolve a célula seguinte.

    Funciona melhor que capturar todo

    o texto da página.

    """

    alvos = {

        chave_texto(

            nome

        )

        for nome in nomes

    }

    for celula in soup.find_all(

        [

            "td",

            "th",

            "label",

            "span",

            "div"

        ]

    ):

        texto = chave_texto(

            celula.get_text(

                " ",

                strip=True

            )

        )

        if texto not in alvos:

            continue

        # Primeiro procura irmão direto

        proxima = celula.find_next_sibling(

            [

                "td",

                "th",

                "span",

                "div"

            ]

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

                chave_texto(

                    valor

                )

                not in alvos

            ):

                return valor

        # Depois procura próxima célula

        proxima = celula.find_next(

            "td"

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

                chave_texto(

                    valor

                )

                not in alvos

            ):

                return valor

    return ""

# ============================================================

# LIMPEZA DOS CAMPOS SEFAZ

# ============================================================

def limpar_assunto_sefaz(valor):

    texto = texto_limpo(

        valor

    )

    marcadores = [

        "Órgão/Entidade",

        "Orgao/Entidade",

        "Interessado",

        "CNPJ",

        "Processo disponível",

        "Processo disponivel",

    ]

    for marcador in marcadores:

        posicao = chave_texto(

            texto

        ).find(

            chave_texto(

                marcador

            )

        )

        if posicao >= 0:

            # precisa localizar também no original;

            # regex é mais confiável aqui

            texto = re.split(

                re.escape(

                    marcador

                ),

                texto,

                maxsplit=1,

                flags=re.IGNORECASE

            )[0]

    return texto_limpo(

        texto

    )

def limpar_interessado_sefaz(

    valor

):

    texto = texto_limpo(

        valor

    )

    texto = re.split(

        r"Processo\s+dispon[ií]vel",

        texto,

        maxsplit=1,

        flags=re.IGNORECASE

    )[0]

    texto = re.split(

        r"Nova\s+Pesquisa",

        texto,

        maxsplit=1,

        flags=re.IGNORECASE

    )[0]

    return texto_limpo(

        texto

    )

# ============================================================

# CABEÇALHO SEFAZ

# ============================================================

def extrair_cabecalho_sefaz(

    soup

):

    # --------------------------------------------------------

    # 1. Primeiro tenta extrair pela estrutura HTML

    # --------------------------------------------------------

    situacao = valor_apos_rotulo(

        soup,

        [

            "Situação",

            "Situacao"

        ]

    )

    assunto = valor_apos_rotulo(

        soup,

        [

            "Assunto"

        ]

    )

    interessado = valor_apos_rotulo(

        soup,

        [

            "Interessado"

        ]

    )

    # --------------------------------------------------------

    # 2. Fallback: texto completo corrigido

    # --------------------------------------------------------

    texto = texto_limpo(

        soup.get_text(

            " ",

            strip=True

        )

    )

    if not situacao:

        match = re.search(

            r"Situa[cç][aã]o\s*:\s*"

            r"(.*?)"

            r"(?=\s+Assunto\s*:|"

            r"\s+[ÓO]rg[aã]o/Entidade\s*:|"

            r"\s+Interessado\s*:|$)",

            texto,

            flags=re.IGNORECASE

        )

        if match:

            situacao = texto_limpo(

                match.group(1)

            )

    if not assunto:

        match = re.search(

            r"Assunto\s*:\s*"

            r"(.*?)"

            r"(?=\s+[ÓO]rg[aã]o/Entidade\s*:|"

            r"\s+CNPJ\s*:|"

            r"\s+Interessado\s*:|$)",

            texto,

            flags=re.IGNORECASE

        )

        if match:

            assunto = texto_limpo(

                match.group(1)

            )

    if not interessado:

        match = re.search(

            r"Interessado\s*:\s*"

            r"(.*?)"

            r"(?=\s+Processo\s+dispon[ií]vel|"

            r"\s+Nova\s+Pesquisa|"

            r"\s+Data\s+Setor\s+Evento|$)",

            texto,

            flags=re.IGNORECASE

        )

        if match:

            interessado = texto_limpo(

                match.group(1)

            )

    # --------------------------------------------------------

    # 3. Limpeza final

    # --------------------------------------------------------

    assunto = limpar_assunto_sefaz(

        assunto

    )

    interessado = limpar_interessado_sefaz(

        interessado

    )

    # Situação eventualmente vem com texto extra

    situacao = re.split(

        r"\s+Assunto\s*:",

        texto_limpo(

            situacao

        ),

        maxsplit=1,

        flags=re.IGNORECASE

    )[0]

    return {

        "situacao":

            texto_limpo(

                situacao

            ),

        "assunto":

            assunto,

        "interessado":

            interessado,

    }

# ============================================================

# MOVIMENTAÇÕES SEFAZ

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

def extrair_movimentacoes_sefaz(

    soup

):

    tabela = (

        encontrar_tabela_movimentacoes_sefaz(

            soup

        )

    )

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

                    strip=True

                )

            )

            for celula

            in linha.find_all(

                [

                    "td",

                    "th"

                ]

            )

        ]

        if len(

            valores

        ) < 3:

            continue

        if (

            chave_texto(

                valores[0]

            )

            == "data"

        ):

            continue

        data = valores[0]

        if not re.match(

            r"^\d{2}/\d{2}/\d{4}$",

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

        })

    return movimentacoes

# ============================================================

# CONSULTAR SEFAZ

# ============================================================

def consultar_sefaz(

    processo

):

    numero = processo[

        "numero"

    ]

    conteudo, url_final = baixar(

        url_sefaz(

            numero

        ),

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

        movimentacoes[0]

        if movimentacoes

        else {

            "data": "",

            "setor": "",

            "evento": "",

        }

    )

    situacao = texto_limpo(

        cabecalho[

            "situacao"

        ]

    )

    # Não gravamos mojibake no JSON

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

            texto_limpo(

                cabecalho[

                    "interessado"

                ]

            ),

        "assunto":

            texto_limpo(

                cabecalho[

                    "assunto"

                ]

            ),

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

def resolver_cod_protocolo(

    processo

):

    numero = processo[

        "numero"

    ]

    codigo = texto_limpo(

        processo.get(

            "cod_protocolo",

            ""

        )

    )

    if codigo:

        return codigo

    codigo = SEMEF_PROTOCOLS.get(

        numero,

        ""

    )

    if codigo:

        return codigo

    raise ValueError(

        "Processo SEMEF sem código de protocolo."

    )

def extrair_cabecalho_semef(

    soup

):

    return {

        "numero":

            valor_apos_rotulo(

                soup,

                [

                    "PROCESSO",

                    "Processo"

                ]

            ),

        "situacao":

            valor_apos_rotulo(

                soup,

                [

                    "SITUAÇÃO",

                    "Situação"

                ]

            ),

        "interessado":

            valor_apos_rotulo(

                soup,

                [

                    "INTERESSADO",

                    "Interessado"

                ]

            ),

        "assunto":

            valor_apos_rotulo(

                soup,

                [

                    "ASSUNTO",

                    "Assunto"

                ]

            ),

        "localizacao":

            valor_apos_rotulo(

                soup,

                [

                    "LOCALIZAÇÃO ATUAL",

                    "Localização Atual"

                ]

            ),

    }

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

            and

            "movimentacao" in texto

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

        return []

    linhas = []

    for linha in tabela.find_all(

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

                    "th"

                ]

            )

        ]

        if len(

            valores

        ) < 2:

            continue

        data = (

            valores[1]

            if len(

                valores

            ) > 1

            else ""

        )

        if not re.match(

            r"^\d{2}/\d{2}/\d{4}$",

            data

        ):

            continue

        linhas.append({

            "situacao":

                valores[0]

                if len(

                    valores

                ) > 0

                else "",

            "data":

                data,

            "origem":

                valores[2]

                if len(

                    valores

                ) > 2

                else "",

            "destino":

                valores[5]

                if len(

                    valores

                ) > 5

                else "",

            "despacho":

                texto_limpo(

                    " ".join(

                        valores[6:]

                    )

                )

                if len(

                    valores

                ) > 6

                else "",

        })

    return linhas

def consultar_semef(

    processo

):

    numero = processo[

        "numero"

    ]

    codigo = (

        resolver_cod_protocolo(

            processo

        )

    )

    ultimo_erro = None

    for tentativa in range(

        1,

        SEMEF_MAX_TENTATIVAS + 1

    ):

        try:

            conteudo, url_final = baixar(

                url_semef(

                    codigo

                ),

                SEMEF_CONNECT_TIMEOUT,

                SEMEF_READ_TIMEOUT

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

                historico[0]

                if historico

                else {

                    "situacao": "",

                    "data": "",

                    "origem": "",

                    "destino": "",

                    "despacho": "",

                }

            )

            situacao = (

                texto_limpo(

                    cabecalho[

                        "situacao"

                    ]

                )

                or

                texto_limpo(

                    ultima[

                        "situacao"

                    ]

                )

                or

                "Não identificada"

            )

            setor = (

                texto_limpo(

                    cabecalho[

                        "localizacao"

                    ]

                )

                or

                texto_limpo(

                    ultima[

                        "destino"

                    ]

                )

                or

                texto_limpo(

                    ultima[

                        "origem"

                    ]

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

                    texto_limpo(

                        cabecalho[

                            "interessado"

                        ]

                    ),

                "assunto":

                    texto_limpo(

                        cabecalho[

                            "assunto"

                        ]

                    ),

                "dataMovimentacao":

                    texto_limpo(

                        ultima[

                            "data"

                        ]

                    ),

                "setor":

                    setor,

                "evento":

                    texto_limpo(

                        ultima[

                            "despacho"

                        ]

                    ),

                "url":

                    url_final,

                "consultado_em":

                    agora_iso(),

                "erro":

                    None,

            }

        except Exception as erro:

            ultimo_erro = erro

            if (

                tentativa

                <

                SEMEF_MAX_TENTATIVAS

            ):

                time.sleep(

                    SEMEF_ESPERA

                )

    raise RuntimeError(

        "Não foi possível atualizar o processo SEMEF. "

        f"{ultimo_erro}"

    )

# ============================================================

# CONSULTA POR ORIGEM

# ============================================================

def consultar_processo(

    processo

):

    if (

        processo.get(

            "origem"

        )

        ==

        "semef"

    ):

        return consultar_semef(

            processo

        )

    return consultar_sefaz(

        processo

    )

# ============================================================

# DADOS ANTERIORES

# ============================================================

def localizar_anterior(

    dados,

    numero

):

    for item in dados.get(

        "processos",

        []

    ):

        if (

            item.get(

                "numero"

            )

            ==

            numero

        ):

            return item

    return None

def assinatura_movimentacao(

    processo

):

    if not processo:

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

def anterior_valido(

    anterior

):

    if not anterior:

        return False

    if anterior.get(

        "erro"

    ):

        return False

    return bool(

        assinatura_movimentacao(

            anterior

        ).replace(

            "|",

            ""

        )

    )

# ============================================================

# ALERTAS

# ============================================================

def alerta_ja_existe(

    alertas,

    numero,

    assinatura

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

# ============================================================

# RESULTADO DE ERRO

# ============================================================

def criar_resultado_erro(

    cadastro,

    anterior,

    erro

):

    numero = cadastro[

        "numero"

    ]

    origem = cadastro[

        "origem"

    ]

    mensagem = texto_limpo(

        erro

    )

    # Preserva os últimos dados válidos

    if anterior:

        resultado = dict(

            anterior

        )

        resultado[

            "numero"

        ] = numero

        resultado[

            "origem"

        ] = origem

        if origem == "semef":

            resultado[

                "cod_protocolo"

            ] = cadastro.get(

                "cod_protocolo",

                SEMEF_PROTOCOLS.get(

                    numero,

                    ""

                )

            )

        resultado[

            "erro"

        ] = mensagem

        resultado[

            "consultado_em"

        ] = agora_iso()

        return resultado

    return {

        "numero":

            numero,

        "origem":

            origem,

        "cod_protocolo":

            cadastro.get(

                "cod_protocolo",

                SEMEF_PROTOCOLS.get(

                    numero,

                    ""

                )

            ),

        "situacao":

            "Não atualizado",

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

            (

                url_semef(

                    cadastro.get(

                        "cod_protocolo",

                        ""

                    )

                )

                if (

                    origem == "semef"

                    and

                    cadastro.get(

                        "cod_protocolo"

                    )

                )

                else (

                    url_sefaz(

                        numero

                    )

                    if origem == "sefaz"

                    else "https://sigedweb.manaus.am.gov.br/protonweb/"

                )

            ),

        "consultado_em":

            agora_iso(),

        "erro":

            mensagem,

    }

# ============================================================

# EXECUÇÃO

# ============================================================

def main():

    print(

        "=" * 60

    )

    print(

        "MONITOR SEFAZ-AM + SEMEF"

    )

    print(

        agora_manaus().strftime(

            "%d/%m/%Y %H:%M:%S"

        )

    )

    print(

        "=" * 60

    )

    try:

        cadastros = (

            carregar_processos()

        )

    except Exception as erro:

        print(

            "Erro:",

            erro

        )

        return 1

    dados_anteriores = (

        carregar_dados()

    )

    anteriores = {

        item.get(

            "numero"

        ):

        item

        for item

        in dados_anteriores.get(

            "processos",

            []

        )

        if item.get(

            "numero"

        )

    }

    numeros_ativos = {

        item[

            "numero"

        ]

        for item

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

    resultados = {}

    erros = 0

    novos_alertas = 0

    # ========================================================

    # CONSULTAS EM PARALELO

    # ========================================================

    with ThreadPoolExecutor(

        max_workers=MAX_WORKERS

    ) as executor:

        futuros = {

            executor.submit(

                consultar_processo,

                cadastro

            ):

            cadastro

            for cadastro

            in cadastros

        }

        for futuro in as_completed(

            futuros

        ):

            cadastro = futuros[

                futuro

            ]

            numero = cadastro[

                "numero"

            ]

            anterior = anteriores.get(

                numero

            )

            try:

                atual = futuro.result()

                resultados[

                    numero

                ] = atual

                print(

                    "OK:",

                    numero,

                    atual.get(

                        "setor",

                        ""

                    )

                )

                if anterior_valido(

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

                        !=

                        assinatura_anterior

                    ):

                        if not alerta_ja_existe(

                            alertas,

                            numero,

                            assinatura_atual

                        ):

                            alertas.insert(

                                0,

                                criar_alerta(

                                    numero,

                                    atual,

                                    anterior

                                )

                            )

                            novos_alertas += 1

            except Exception as erro:

                erros += 1

                print(

                    "ERRO:",

                    numero,

                    erro

                )

                resultados[

                    numero

                ] = criar_resultado_erro(

                    cadastro,

                    anterior,

                    erro

                )

    # ========================================================

    # MANTÉM A ORDEM DO PROCESSOS.JSON

    # ========================================================

    lista_final = [

        resultados[

            cadastro[

                "numero"

            ]

        ]

        for cadastro

        in cadastros

        if cadastro[

            "numero"

        ]

        in resultados

    ]

    saida = {

        "ultima_verificacao":

            agora_iso(),

        "timezone":

            "America/Manaus",

        "total_processos":

            len(

                lista_final

            ),

        "erros":

            erros,

        "novos_alertas":

            novos_alertas,

        "processos":

            lista_final,

        "alertas":

            alertas[:100],

    }

    salvar_dados(

        saida

    )

    print(

        "=" * 60

    )

    print(

        "dados.json atualizado"

    )

    print(

        "Processos:",

        len(

            lista_final

        )

    )

    print(

        "Erros:",

        erros

    )

    print(

        "Novos alertas:",

        novos_alertas

    )

    print(

        "=" * 60

    )

    return 0

if __name__ == "__main__":

    sys.exit(

        main()

    )
