#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_experiments.sh — executa a matriz de experimentos do Trabalho Prático 06.
#
# Matriz experimental:
#   2 perfis (read = Perfil 1 | write = Perfil 2)
#   x 3 cenários (A = 30 users | B = 80 users | C = 150 users)
#   x 10 repetições
#   = 60 execuções
#
# Cada execução tem 2 estágios:
#   1) AQUECIMENTO (default 1m — resultados gravados com sufixo _warmup e
#                    DESCARTADOS na análise)
#   2) MEDIÇÃO     (default 6m — CSVs em results/raw/)
#
# Durante cada estágio, scripts/collect_stats.sh amostra a CPU dos contêineres.
# Tempo total estimado: 60 x (1m + 6m + overhead) ≈ 7 horas.
#
# Uso:
#   ./scripts/run_experiments.sh                       # matriz completa
#   ./scripts/run_experiments.sh --profiles read       # só um perfil
#   ./scripts/run_experiments.sh --users 30            # só um cenário
#   ./scripts/run_experiments.sh --reps 1 --max-runs 2 # teste rápido
#   ./scripts/run_experiments.sh --dryrun              # só lista o que faria
#   TARGET_HOST=http://10.0.0.5:8080 ./scripts/run_experiments.sh
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."   # raiz do projeto

PROFILES=(read write)
USERS=(30 80 150)
REPS=10
WARMUP="1m"
DURATION="6m"
SPECIFIC_MAX_RUNS=""

# ------------------- parsing de argumentos -------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profiles) IFS=',' read -r -a PROFILES <<< "$2"; shift 2 ;;
    --users)    IFS=',' read -r -a USERS    <<< "$2"; shift 2 ;;
    --reps)     REPS="$2"; shift 2 ;;
    --warmup)   WARMUP="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --max-runs) SPECIFIC_MAX_RUNS="$2"; shift 2 ;;
    --dryrun)   DRYRUN=1; shift ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Argumento desconhecido: $1"; exit 1 ;;
  esac
done

TARGET_HOST="${TARGET_HOST:-http://localhost:8080}"
LOCUST="${LOCUST:-}"
if [[ -z "${LOCUST}" ]]; then
  if [[ -x "./venv/bin/locust" ]]; then LOCUST="./venv/bin/locust";
  else LOCUST="locust"; fi
fi
MAX_RUNS="${SPECIFIC_MAX_RUNS:-}"

# converte durações do Locust (ex.: 1m, 90s, 2m30s) para segundos
to_seconds() {
  python3 - "$1" <<'PYEOF'
import re, sys
total = 0
for value, unit in re.findall(r'(\d+)([hms]?)', sys.argv[1]):
    total += int(value) * {'h': 3600, 'm': 60, 's': 1, '': 1}[unit]
print(total)
PYEOF
}

# ------------------- checagens de ambiente -------------------
if ! command -v "${LOCUST}" >/dev/null 2>&1; then
  echo "ERRO: locust não encontrado. Rode: pip install -r requirements.txt" >&2
  exit 1
fi

mkdir -p results/raw results/tables results/charts

# ------------------- checagem da aplicação -------------------
echo "==> Verificando aplicação em ${TARGET_HOST} ..."
if ! curl -fsS -o /dev/null --max-time 10 "${TARGET_HOST}/api/customer/owners"; then
  echo "ERRO: aplicação não respondeu em ${TARGET_HOST}/api/customers/owners." >&2
  echo "      Suba o PetClinic antes: docker compose up -d --wait" >&2
  exit 1
fi
echo "OK: aplicação responder com sucesso."

# ------------------- planejamento dos runs -------------------
plan=()
for profile in "${PROFILES[@]}"; do
  for users in "${USERS[@]}"; do
    for rep in $(seq 1 "${REPS}"); do
      plan+=("${profile}|${users}|${rep}")
    done
  done
done
TOTAL_RUNS=${#plan[@]}

if [[ -n "${MAX_RUNS}" ]]; then
  plan=("${plan[@]:0:${MAX_RUNS}}")
fi

echo ""
echo "=============================================================="
echo " Perfis   : ${PROFILES[*]}"
echo " Cenários : ${USERS[*]} usuários"
echo " Reps     : ${REPS}"
echo " Runs     : ${#plan[@]} (de um total de ${TOTAL_RUNS})"
echo " Aquec.   : ${WARMUP} (descartado) | Medição: ${DURATION}"
echo " Alvo     : ${TARGET_HOST}"
echo " Tempo est: $(( ${#plan[@]} * 8 )) min (aprox.)"
echo "=============================================================="
echo ""

if [[ -n "${DRYRUN:-}" ]]; then
  for item in "${plan[@]}"; do
    IFS='|' read -r profile users rep <<< "${item}"
    echo "DRYRUN -> ${profile}|${users}u|rep${rep}"
  done
  exit 0
fi

# ------------------- execução -------------------
RUN_NUM=0
FAILED_RUNS=0
for item in "${plan[@]}"; do
  IFS='|' read -r profile users rep <<< "${item}"
  RUN_NUM=$(( RUN_NUM + 1 ))
  RUN_ID="${profile}_${users}u_rep${rep}"

  # rampa para atingir o teto de usuários em ~30 s
  SPAWN_RATE=$(awk "BEGIN { printf \"%.2f\", ${users} / 30 + 0.01 }")

  echo ""
  echo "=============================================================="
  echo "[${RUN_NUM}/${#plan[@]}] Run=${RUN_ID}  users=${users}  profile=${profile}"
  echo "=============================================================="

  # ---- estágio 1: aquecimento (descartado na análise) ----
  WARMUP_SECS=$(to_seconds "${WARMUP}")
  echo "  [1/2] Aquecimento (${WARMUP}) ..."
  ./scripts/collect_stats.sh "results/raw/${RUN_ID}_warmup_dockerstats.csv" "${WARMUP_SECS}" 10 >/dev/null &
  STATS_PID=$!
  PROFILE="${profile}" TARGET_HOST="${TARGET_HOST}" \
    ${LOCUST} -f locustfile.py --headless \
      -u "${users}" -r "${SPAWN_RATE}" -t "${WARMUP}" \
      --csv "results/raw/${RUN_ID}_warmup" \
      --only-summary --loglevel INFO \
      --exit-code-on-error 0 \
      > "results/raw/${RUN_ID}_warmup.log" 2>&1 || {
        echo "  AVISO: aquecimento terminou com erros (ver log)."
      }
  kill "${STATS_PID}" 2>/dev/null || true

  # ---- estágio 2: medição (6 min) ----
  echo "  [2/2] Medição (${DURATION}) ..."
  DURATION_SECS=$(to_seconds "${DURATION}")
  ./scripts/collect_stats.sh "results/raw/${RUN_ID}_dockerstats.csv" "${DURATION_SECS}" 10 >/dev/null &
  STATS_PID=$!
  PROFILE="${profile}" TARGET_HOST="${TARGET_HOST}" \
    ${LOCUST} -f locustfile.py --headless \
      -u "${users}" -r "${SPAWN_RATE}" -t "${DURATION}" \
      --csv "results/raw/${RUN_ID}" \
      --only-summary --loglevel INFO \
      --exit-code-on-error 0 \
      > "results/raw/${RUN_ID}.log" 2>&1 || FAILED_RUNS=$(( FAILED_RUNS + 1 ))
  kill "${STATS_PID}" 2>/dev/null || true

  if [[ -f "results/raw/${RUN_ID}_stats.csv" ]]; then
    echo "  OK -> results/raw/${RUN_ID}_stats.csv"
  else
    echo "  ERRO: CSV da medição não foi gerado (ver results/raw/${RUN_ID}.log)."
  fi
done

echo ""
echo "=============================================================="
echo " Execução concluída."
echo " Runs com falha no Locust : ${FAILED_RUNS}"
echo " Próximo passo            : python3 scripts/analyze.py"
echo "=============================================================="
