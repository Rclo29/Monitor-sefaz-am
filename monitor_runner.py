import monitor

# Consulta os processos estaduais (SEFAZ) e municipais (SIGEDWEB)
# cadastrados em processos.json, respeitando a origem de cada registro.
monitor.TEMPO_MAXIMO_EXECUCAO = 120

if __name__ == "__main__":
    raise SystemExit(monitor.main())
