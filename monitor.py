import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ARQUIVO_DADOS = "dados.json"
ARQUIVO_PROCESSOS = "processos.json"

SEFAZ_BASE_URL = "https://online.sefaz.am.gov.br/processo/"
SEMEF_BASE_URL = "https://sigedweb.manaus.am.gov.br/protonweb/detalhe.aspx"

TIMEOUT_SEFAZ = 30
SEMEF_CONNECT_TIMEOUT = 45
SEMEF_READ_TIMEOUT = 60
SEMEF_MAX_TENTATIVAS = 3
SEMEF_ESPERA_BASE = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
    return datetime.now(ZoneInfo("America/Manaus"))


def agora_iso():
    return agora_manaus().isoformat(timespec="seconds")


def texto_limpo(valor):
    if valor is None:
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def normalizar_origem(valor):
    return "semef" if texto_limpo(valor).lower() in ("semef", "siged") else "sefaz"


def detectar_origem(numero):
    numero = texto_limpo(numero)
    if re.match(r"^\d{4}\.\d{5}\.\d{5}\.\d\.\d{6}$", numero):
        return "semef"
    return "sefaz"


def url_sefaz(numero):
    return SEFAZ_BASE_URL + quote(numero, safe="/")


def url_semef(cod_protocolo):
    return f"{SEMEF_BASE_URL}?origem=1&cod_protocolo={quote(str(cod_protocolo))}"


def carregar_processos():
    if not os.path.exists(ARQUIVO_PROCESSOS):
        raise FileNotFoundError("Arquivo processos.json nÃ£o encontrado.")

    with open(ARQUIVO_PROCESSOS, "r", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)

    if not isinstance(dados, dict):
        raise ValueError("processos.json possui formato invÃ¡lido.")

    lista = dados.get("processos", [])
    if not isinstance(lista, list):
        raise ValueError('O campo "processos" precisa ser uma lista.')

    processos = []
    vistos = set()

    for item in lista:
        if isinstance(item, str):
            numero = texto_limpo(item)
            origem = detectar_origem(numero)
            cod_protocolo = SEMEF_PROTOCOLS.get(numero, "") if origem == "semef" else ""
        elif isinstance(item, dict):
            numero = texto_limpo(item.get("numero", item.get("processo", "")))
            origem = normalizar_origem(item.get("origem", detectar_origem(numero)))
            cod_protocolo = texto_limpo(item.get("cod_protocolo", item.get("codProtocolo", "")))
            if origem == "semef" and not cod_protocolo:
                cod_protocolo = SEMEF_PROTOCOLS.get(numero, "")
        else:
            continue

        if not numero or numero in vistos:
            continue

        vistos.add(numero)
        processos.append({
            "numero": numero,
            "origem": origem,
            "cod_protocolo": cod_protocolo,
        })

    if not processos:
        raise ValueError("Nenhum processo cadastrado em processos.json.")

    return processos


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
    if not os.path.exists(ARQUIVO_DADOS):
        return estrutura_vazia()

    try:
        with open(ARQUIVO_DADOS, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)

        if not isinstance(dados, dict):
            return estrutura_vazia()

        dados.setdefault("processos", [])
        dados.setdefault("alertas", [])
        return dados
    except Exception as erro:
        print("Aviso ao ler dados.json:", erro)
        return estrutura_vazia()


def salvar_dados(dados):
    with open(ARQUIVO_DADOS, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        arquivo.write("\n")


def baixar_url(url, descricao):
    print(f"Consultando {descricao}")
    print(f"URL: {url}")

    resposta = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT_SEFAZ,
        allow_redirects=True,
    )

    print("HTTP:", resposta.status_code)
    print("URL final:", resposta.url)

    resposta.raise_for_status()

    if resposta.encoding is None:
        resposta.encoding = resposta.apparent_encoding or "utf-8"

    return resposta.text, resposta.url


def baixar_url_semef(url, descricao):
    ultimo_erro = None

    for tentativa in range(1, SEMEF_MAX_TENTATIVAS + 1):
        print()
        print(f"Consultando {descricao}")
        print(f"Tentativa {tentativa}/{SEMEF_MAX_TENTATIVAS}")
        print(f"URL: {url}")

        try:
            resposta = requests.get(
                url,
                headers=HEADERS,
                timeout=(SEMEF_CONNECT_TIMEOUT, SEMEF_READ_TIMEOUT),
                allow_redirects=True,
            )

            print("HTTP:", resposta.status_code)
            print("URL final:", resposta.url)

            resposta.raise_for_status()

            if resposta.encoding is None:
                resposta.encoding = resposta.apparent_encoding or "utf-8"

            html = resposta.text
            if not texto_limpo(html):
                raise ValueError("SIGED retornou uma pÃ¡gina vazia.")

            print("Consulta SEMEF recebida com sucesso.")
            return html, resposta.url

        except (requests.RequestException, ValueError) as erro:
            ultimo_erro = erro
            print(f"Falha na tentativa {tentativa}: {erro}")

            if tentativa < SEMEF_MAX_TENTATIVAS:
                espera = SEMEF_ESPERA_BASE * tentativa
                print(f"Nova tentativa em {espera} segundos...")
                time.sleep(espera)

    raise RuntimeError(
        f"NÃ£o foi possÃ­vel consultar o SIGED/SEMEF apÃ³s "
        f"{SEMEF_MAX_TENTATIVAS} tentativas. Ãltimo erro: {ultimo_erro}"
    )


def extrair_cabecalho_sefaz(soup):
    texto = texto_limpo(soup.get_text(" ", strip=True))

    def pegar(padrao):
        match = re.search(padrao, texto, flags=re.IGNORECASE)
        return texto_limpo(match.group(1)) if match else ""

    return {
        "situacao": pegar(
            r"SituaÃ§Ã£o\s*:\s*(.*?)(?=\s+Assunto\s*:|\s+ÃrgÃ£o/Entidade\s*:|\s+Interessado\s*:|$)"
        ),
        "assunto": pegar(
            r"Assunto\s*:\s*(.*?)(?=\s+ÃrgÃ£o/Entidade\s*:|\s+CNPJ\s*:|\s+Interessado\s*:|$)"
        ),
        "interessado": pegar(
            r"Interessado\s*:\s*(.*?)(?=\s+Processo disponÃ­vel|\s+Nova Pesquisa|\s+Data\s+Setor\s+Evento|$)"
        ),
    }


def encontrar_tabela_movimentacoes_sefaz(soup):
    for tabela in soup.find_all("table"):
        texto = texto_limpo(tabela.get_text(" ", strip=True)).lower()
        if "data" in texto and "setor" in texto and "evento" in texto:
            return tabela
    return None


def extrair_movimentacoes_sefaz(soup):
    tabela = encontrar_tabela_movimentacoes_sefaz(soup)
    movimentacoes = []

    if tabela is None:
        print("Aviso: tabela de movimentaÃ§Ãµes SEFAZ nÃ£o encontrada.")
        return movimentacoes

    for linha in tabela.find_all("tr"):
        valores = [
            texto_limpo(celula.get_text(" ", strip=True))
            for celula in linha.find_all(["td", "th"])
        ]

        if len(valores) < 3:
            continue

        if valores[0].lower() == "data" and valores[1].lower() == "setor":
            continue

        data = valores[0]
        if not re.match(r"^\d{2}/\d{2}/\d{4}$", data):
            continue

        movimentacoes.append({
            "data": data,
            "setor": valores[1],
            "evento": texto_limpo(" ".join(valores[2:])),
        })

    return movimentacoes


def consultar_sefaz(processo):
    numero = processo["numero"]
    html, url_final = baixar_url(url_sefaz(numero), f"SEFAZ - {numero}")
    soup = BeautifulSoup(html, "html.parser")

    cabecalho = extrair_cabecalho_sefaz(soup)
    movimentacoes = extrair_movimentacoes_sefaz(soup)
    ultima = movimentacoes[0] if movimentacoes else {
        "data": "",
        "setor": "",
        "evento": "",
    }

    return {
        "numero": numero,
        "origem": "sefaz",
        "cod_protocolo": "",
        "situacao": cabecalho["situacao"] or "NÃ£o identificada",
        "interessado": cabecalho["interessado"],
        "assunto": cabecalho["assunto"],
        "dataMovimentacao": ultima["data"],
        "setor": ultima["setor"],
        "evento": ultima["evento"],
        "url": url_final,
        "consultado_em": agora_iso(),
        "erro": None,
    }


def localizar_valor_rotulo(soup, rotulo):
    alvo = texto_limpo(rotulo).replace(":", "").upper()

    for celula in soup.find_all(["td", "th"]):
        texto = texto_limpo(celula.get_text(" ", strip=True)).replace(":", "").upper()

        if texto != alvo:
            continue

        proxima = celula.find_next("td")
        if proxima:
            valor = texto_limpo(proxima.get_text(" ", strip=True))
            if valor and valor.upper() != alvo:
                return valor

    return ""


def extrair_cabecalho_semef(soup):
    texto = texto_limpo(soup.get_text(" ", strip=True))

    def regex_valor(inicio, finais):
        padrao_finais = "|".join(re.escape(item) for item in finais)

        match = re.search(
            re.escape(inicio)
            + r"\s*:\s*(.*?)"
            + r"(?=\s+(?:"
            + padrao_finais
            + r")\s*:|$)",
            texto,
            flags=re.IGNORECASE,
        )

        return texto_limpo(match.group(1)) if match else ""

    resultado = {
        "numero": regex_valor(
            "PROCESSO",
            ["DATA DO PROCESSO", "SITUAÃÃO", "INTERESSADO"],
        ),
        "data_processo": regex_valor(
            "DATA DO PROCESSO",
            ["SITUAÃÃO", "INTERESSADO"],
        ),
        "situacao": regex_valor(
            "SITUAÃÃO",
            ["INTERESSADO", "ASSUNTO", "LOCALIZAÃÃO ATUAL"],
        ),
        "interessado": regex_valor(
            "INTERESSADO",
            ["ASSUNTO", "LOCALIZAÃÃO ATUAL"],
        ),
        "assunto": regex_valor(
            "ASSUNTO",
            ["LOCALIZAÃÃO ATUAL", "DATA DO SOBRESTAMENTO", "DESPACHO"],
        ),
        "localizacao": regex_valor(
            "LOCALIZAÃÃO ATUAL",
            ["DATA DO SOBRESTAMENTO", "DESPACHO", "MOTIVO", "HistÃ³rico do Processo"],
        ),
    }

    for chave, rotulo in (
        ("situacao", "SITUAÃÃO"),
        ("interessado", "INTERESSADO"),
        ("assunto", "ASSUNTO"),
        ("localizacao", "LOCALIZAÃÃO ATUAL"),
    ):
        if not resultado[chave]:
            resultado[chave] = localizar_valor_rotulo(soup, rotulo)

    return resultado


def encontrar_tabela_historico_semef(soup):
    for tabela in soup.find_all("table"):
        texto = texto_limpo(tabela.get_text(" ", strip=True)).upper()

        if (
            "SITUAÃÃO" in texto
            and "DATA" in texto
            and "DEPTO" in texto
            and "DESPACHO" in texto
            and "MOVIMENTAÃÃO" in texto
        ):
            return tabela

    return None


def extrair_historico_semef(soup):
    tabela = encontrar_tabela_historico_semef(soup)

    if tabela is None:
        print("Aviso: histÃ³rico SEMEF nÃ£o encontrado.")
        return []

    linhas = []

    for linha in tabela.find_all("tr"):
        valores = [
            texto_limpo(celula.get_text(" ", strip=True))
            for celula in linha.find_all(["td", "th"])
        ]

        if not valores:
            continue

        texto_linha = " ".join(valores).upper()

        if "DESPACHO MOVIMENTAÃÃO" in texto_linha or "DEPTO. ORIGEM" in texto_linha:
            continue

        if len(valores) < 2:
            continue

        data = valores[1] if len(valores) > 1 else ""

        if not re.match(r"^\d{2}/\d{2}/\d{4}$", data):
            continue

        linhas.append({
            "situacao": valores[0] if len(valores) > 0 else "",
            "data": data,
            "origem": valores[2] if len(valores) > 2 else "",
            "recebido": valores[4] if len(valores) > 4 else "",
            "destino": valores[5] if len(valores) > 5 else "",
            "despacho": texto_limpo(" ".join(valores[6:])) if len(valores) > 6 else "",
        })

    return linhas


def resolver_cod_protocolo(processo):
    numero = processo["numero"]
    cod_protocolo = texto_limpo(processo.get("cod_protocolo", ""))

    if cod_protocolo:
        return cod_protocolo

    cod_protocolo = SEMEF_PROTOCOLS.get(numero, "")
    if cod_protocolo:
        return cod_protocolo

    raise ValueError(
        "Processo SEMEF sem cÃ³digo de protocolo conhecido. "
        "A pesquisa inicial do SIGED exige validaÃ§Ã£o por cÃ³digo de acesso."
    )


def consultar_semef(processo):
    numero = processo["numero"]
    cod_protocolo = resolver_cod_protocolo(processo)
    url = url_semef(cod_protocolo)

    html, url_final = baixar_url_semef(url, f"SEMEF - {numero}")
    soup = BeautifulSoup(html, "html.parser")

    cabecalho = extrair_cabecalho_semef(soup)
    historico = extrair_historico_semef(soup)

    ultima = historico[0] if historico else {
        "situacao": "",
        "data": "",
        "origem": "",
        "recebido": "",
        "destino": "",
        "despacho": "",
    }

    numero_pagina = texto_limpo(cabecalho.get("numero", ""))

    if numero_pagina and numero_pagina != numero:
        raise ValueError(
            f"O cÃ³digo de protocolo SEMEF nÃ£o corresponde ao nÃºmero {numero}."
        )

    situacao = texto_limpo(cabecalho.get("situacao", ""))
    if not situacao:
        situacao = texto_limpo(ultima.get("situacao", ""))

    setor = texto_limpo(cabecalho.get("localizacao", ""))
    if not setor:
        setor = texto_limpo(ultima.get("destino", ""))
    if not setor:
        setor = texto_limpo(ultima.get("origem", ""))

    return {
        "numero": numero,
        "origem": "semef",
        "cod_protocolo": cod_protocolo,
        "situacao": situacao or "NÃ£o identificada",
        "interessado": texto_limpo(cabecalho.get("interessado", "")),
        "assunto": texto_limpo(cabecalho.get("assunto", "")),
        "dataMovimentacao": texto_limpo(ultima.get("data", "")),
        "setor": setor,
        "evento": texto_limpo(ultima.get("despacho", "")),
        "url": url_final,
        "consultado_em": agora_iso(),
        "erro": None,
    }


def consultar_processo(processo):
    if processo.get("origem", "sefaz") == "semef":
        return consultar_semef(processo)

    return consultar_sefaz(processo)


def assinatura_movimentacao(processo):
    if not processo:
        return ""

    data = texto_limpo(processo.get("dataMovimentacao", ""))
    setor = texto_limpo(processo.get("setor", ""))
    evento = texto_limpo(processo.get("evento", ""))

    if not (data or setor or evento):
        return ""

    return "|".join([data, setor, evento])


def localizar_anterior(dados, numero):
    for processo in dados.get("processos", []):
        if processo.get("numero") == numero:
            return processo

    return None


def anterior_e_valido(anterior):
    if not anterior or anterior.get("erro"):
        return False

    if "erro" in texto_limpo(anterior.get("situacao", "")).lower():
        return False

    return bool(
        assinatura_movimentacao(
            anterior
        )
    )


def criar_alerta(numero, novo, anterior):
    return {
        "numero": numero,
        "origem": novo.get("origem", "sefaz"),
        "data": agora_iso(),
        "mensagem": (
            "Nova movimentaÃ§Ã£o: "
            + (novo.get("evento") or "movimentaÃ§Ã£o atualizada")
        ),
        "movimentacao_anterior": assinatura_movimentacao(anterior),
        "movimentacao_atual": assinatura_movimentacao(novo),
        "data_movimentacao": novo.get("dataMovimentacao", ""),
        "setor": novo.get("setor", ""),
        "evento": novo.get("evento", ""),
    }


def alerta_ja_existe(alertas, numero, assinatura):
    return any(
        alerta.get("numero") == numero
        and alerta.get("movimentacao_atual") == assinatura
        for alerta in alertas
    )


def url_do_processo(processo):
    if processo.get("origem") == "semef":
        try:
            return url_semef(
                resolver_cod_protocolo(
                    processo
                )
            )
        except Exception:
            return "https://sigedweb.manaus.am.gov.br/protonweb/"

    return url_sefaz(
        processo["numero"]
    )


def main():
    print("=" * 60)
    print("MONITOR SEFAZ + SEMEF")
    print("InÃ­cio:", agora_manaus().strftime("%d/%m/%Y %H:%M:%S"))
    print("=" * 60)

    try:
        processos_monitorados = carregar_processos()
    except Exception as erro:
        print("ERRO ao carregar processos.json:", erro)
        return 1

    print("Processos cadastrados:", len(processos_monitorados))

    dados_anteriores = carregar_dados()
    novos_processos = []

    numeros_ativos = {
        item["numero"]
        for item in processos_monitorados
    }

    novos_alertas = [
        alerta
        for alerta in dados_anteriores.get("alertas", [])
        if alerta.get("numero") in numeros_ativos
    ]

    erros = 0
    novos_alertas_detectados = 0

    for cadastro in processos_monitorados:
        numero = cadastro["numero"]
        origem = cadastro["origem"]

        print()
        print("-" * 60)
        print(f"{origem.upper()} - {numero}")
        print("-" * 60)

        anterior = localizar_anterior(
            dados_anteriores,
            numero
        )

        try:
            atual = consultar_processo(
                cadastro
            )

            print("Origem:", atual["origem"].upper())
            print("SituaÃ§Ã£o:", atual["situacao"])
            print("Interessado:", atual["interessado"])
            print("Assunto:", atual["assunto"])
            print("Setor:", atual["setor"])
            print("Data:", atual["dataMovimentacao"])
            print("Ãltima movimentaÃ§Ã£o:", atual["evento"] or "â")

            if anterior_e_valido(anterior):
                assinatura_anterior = assinatura_movimentacao(anterior)
                assinatura_atual = assinatura_movimentacao(atual)

                if assinatura_atual and assinatura_atual != assinatura_anterior:
                    if not alerta_ja_existe(
                        novos_alertas,
                        numero,
                        assinatura_atual
                    ):
                        novos_alertas.insert(
                            0,
                            criar_alerta(
                                numero,
                                atual,
                                anterior
                            )
                        )

                        novos_alertas_detectados += 1
                        print("NOVA MOVIMENTAÃÃO DETECTADA!")
                    else:
                        print("MovimentaÃ§Ã£o jÃ¡ possui alerta registrado.")
                else:
                    print("Nenhuma nova movimentaÃ§Ã£o.")
            else:
                print("Sem consulta anterior vÃ¡lida para comparaÃ§Ã£o.")
                print("Estado atual salvo como referÃªncia inicial.")

            novos_processos.append(
                atual
            )

        except Exception as erro:
            erros += 1
            print(f"ERRO ao consultar {numero}: {erro}")

            if anterior:
                copia = dict(
                    anterior
                )

                copia["origem"] = origem

                if origem == "semef":
                    copia["cod_protocolo"] = cadastro.get(
                        "cod_protocolo",
                        SEMEF_PROTOCOLS.get(
                            numero,
                            ""
                        )
                    )

                copia["erro"] = str(
                    erro
                )

                copia["consultado_em"] = agora_iso()

                novos_processos.append(
                    copia
                )

            else:
                novos_processos.append({
                    "numero": numero,
                    "origem": origem,
                    "cod_protocolo": cadastro.get(
                        "cod_protocolo",
                        SEMEF_PROTOCOLS.get(
                            numero,
                            ""
                        )
                    ),
                    "situacao": "Erro na consulta",
                    "interessado": "",
                    "assunto": "",
                    "dataMovimentacao": "",
                    "setor": "",
                    "evento": "",
                    "url": url_do_processo(cadastro),
                    "consultado_em": agora_iso(),
                    "erro": str(erro),
                })

    novos_alertas = novos_alertas[:100]

    saida = {
        "ultima_verificacao": agora_iso(),
        "timezone": "America/Manaus",
        "total_processos": len(novos_processos),
        "erros": erros,
        "novos_alertas": novos_alertas_detectados,
        "processos": novos_processos,
        "alertas": novos_alertas,
    }

    salvar_dados(
        saida
    )

    print("=" * 60)
    print("dados.json atualizado.")
    print("Processos:", len(novos_processos))
    print("Erros:", erros)
    print("Novos alertas:", novos_alertas_detectados)
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(
        main()
    )
