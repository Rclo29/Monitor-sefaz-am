import monitor

# Monitor dedicado somente aos processos da SEFAZ.
# A lista de processos é lida de processos.json e contém apenas origem=sefaz.
monitor.TEMPO_MAXIMO_EXECUCAO = 120

if __name__ == "__main__":
    raise SystemExit(monitor.main())
