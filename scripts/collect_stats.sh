#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# collect_stats.sh — amostra a utilização de CPU e memória dos contêineres
# do PetClinic durante uma execução de experimento (metrica obrigatória:
# "utilização de CPU de pelo menos dois serviços").
#
# Uso: ./scripts/collect_stats.sh <arquivo_csv_de_saida> <duracao_em_segundos> [intervalo_em_segundos]
#
# Gera CSV com colunas: timestamp,container,cpu_percent,mem_used_mb,mem_limit_mb,mem_percent
# ---------------------------------------------------------------------------
set -euo pipefail

OUT_CSV="${1:?Uso: $0 <arquivo_csv> <duracao_s> [intervalo_s]}"
DURATION="${2:?Uso: $0 <arquivo_csv> <duracao_s> [intervalo_s]}"
INTERVAL="${3:-10}"

# Serviços monitorados (customers e vets são obrigatórios; visits/gateway dão contexto)
CONTAINERS=(
  customers-service
  vets-service
  visits-service
  api-gateway
)

echo "timestamp,container,cpu_percent,mem_used_mb,mem_limit_mb,mem_percent" >> "${OUT_CSV}"

END=$(( $(date +%s) + DURATION ))
while [ "$(date +%s)" -lt "${END}" ]; do
  TS=$(date +%s)
  docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}" 2>/dev/null \
  | while IFS=, read -r NAME CPU MUSAGE MPERC; do
      case "${NAME}" in
        customers-service|vets-service|visits-service|api-gateway)
          CPU=${CPU//\ /}; CPU=${CPU//\%/}
          MEM_USED=$(echo "${MUSAGE}" | cut -d'/' -f1)
          MEM_LIMIT=$(echo "${MUSAGE}" | cut -d'/' -f2)
          MPERC=${MPERC//\ /}; MPERC=${MPERC//\%/}
          printf '%s,%s,%s,%s,%s,%s\n' "${TS}" "${NAME}" "${CPU}" "${MEM_USED}" "${MEM_LIMIT}" "${MPERC}"
          ;;
      esac
    done >> "${OUT_CSV}" || true
  sleep "${INTERVAL}"
done
