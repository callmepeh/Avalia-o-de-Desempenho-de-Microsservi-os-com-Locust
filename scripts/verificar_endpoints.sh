#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# verificar_endpoints.sh — valida os endpoints usados pelos perfis de carga
# no API Gateway do PetClinic Microservices.
#
# Uso: ./scripts/verificar_endpoints.sh [http://localhost:8080]
# ---------------------------------------------------------------------------
set -euo pipefail

HOST="${1:-http://localhost:8080}"

check() {
  local method="$1" url="$2" data="${3:-}"
  if [ "$method" = "POST" ]; then
    code=$(curl -s -o /tmp/petclinic_check.json -w "%{http_code}" -X POST \
      -H "Content-Type: application/json" -d "$data" "${HOST}${url}")
  else
    code=$(curl -s -o /tmp/petclinic_check.json -w "%{http_code}" "${HOST}${url}")
  fi
  if [ "$code" = "200" ] || [ "$code" = "201" ]; then
    echo "OK   [$method $url] -> HTTP $code"
  else
    echo "ERRO [$method $url] -> HTTP $code"
    exit 1
  fi
}

echo "Verificando aplicação em ${HOST} ..."
check GET "/api/customer/owners"
check GET "/api/customer/owners/1"
check GET "/api/vet/vets"
check POST "/api/customer/owners" \
      '{"firstName":"Verificacao","lastName":"Script","address":"Rua Teste","city":"Sao Paulo","telephone":"11999999999"}'
echo "Todos os endpoints responderam corretamente."
