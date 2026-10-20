"""
Trabalho Prático 06 — Avaliação de Desempenho de Microsserviços com Locust
Aplicação: Spring PetClinic Microservices (https://github.com/spring-petclinic/spring-petclinic-microservices)

Perfis de carga (definidos pelo enunciado):

| Operação            | Perfil 1 - Leitura | Perfil 2 - Escrita |
|---------------------|--------------------|--------------------|
| GET  /owners        |        45%         |        20%         |
| GET  /owners/{id}   |        35%         |        20%         |
| GET  /vets          |        15%         |        20%         |
| POST /owners        |         5%         |        40%         |

Como selecionar o perfil:
    PROFILE=read  locust ...   (Perfil 1 - Leitura, padrão)
    PROFILE=write locust ...   (Perfil 2 - Escrita)

Variáveis de ambiente:
    TARGET_HOST  -> host do API Gateway (padrão http://localhost:8080)
    PROFILE      -> "read" (Perfil 1) ou "write" (Perfil 2)
"""

import os
import random
import logging

from locust import HttpUser, between

log = logging.getLogger("petclinic_load")

PROFILE = os.environ.get("PROFILE", "read").strip().lower()
TARGET_HOST = os.environ.get("TARGET_HOST", "http://localhost:8080").rstrip("/")

# Pesos por operação, conforme a tabela do enunciado.
PROFILE_WEIGHTS = {
    "read": {  # Perfil 1 — Leitura
        "list_owners": 45,
        "get_owner": 35,
        "list_vets": 15,
        "create_owner": 5,
    },
    "write": {  # Perfil 2 — Escrita
        "list_owners": 20,
        "get_owner": 20,
        "list_vets": 20,
        "create_owner": 40,
    },
}

if PROFILE not in PROFILE_WEIGHTS:
    raise SystemExit(
        f"PROFILE inválido: '{PROFILE}'. Use 'read' (Perfil 1) ou 'write' (Perfil 2)."
    )

NAMES = {
    "list_owners": "GET /api/customer/owners",
    "get_owner": "GET /api/customer/owners/{id}",
    "list_vets": "GET /api/vet/vets",
    "create_owner": "POST /api/customer/owners",
}


def list_owners(user: "PetClinicUser") -> None:
    """GET /api/customer/owners — lista todos os tutores."""
    with user.client.get(
        "/api/customer/owners",
        name=NAMES["list_owners"],
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            try:
                body = resp.json()
                if isinstance(body, list) and body:
                    user.cache_owner_ids(body)
                resp.success()
            except (ValueError, TypeError):
                resp.failure("Resposta 200 sem JSON válido")
        else:
            resp.failure(f"HTTP {resp.status_code}")


def get_owner(user: "PetClinicUser") -> None:
    """GET /api/customer/owners/{id} — detalhe de um tutor (id válido conhecido)."""
    owner_id = user.pick_owner_id()
    with user.client.get(
        f"/api/customer/owners/{owner_id}",
        name=NAMES["get_owner"],
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            resp.success()
        elif resp.status_code == 404:
            resp.failure(f"Owner {owner_id} não encontrado (HTTP 404)")
        else:
            resp.failure(f"HTTP {resp.status_code}")


def list_vets(user: "PetClinicUser") -> None:
    """GET /api/vet/vets — lista dos veterinários."""
    with user.client.get(
        "/api/vet/vets",
        name=NAMES["list_vets"],
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            resp.success()
        else:
            resp.failure(f"HTTP {resp.status_code}")


def create_owner(user: "PetClinicUser") -> None:
    """POST /api/customer/owners — criação de tutor (operação de escrita)."""
    n = user.user_id
    first = random.choice(["Ana", "Bruno", "Carla", "Diego", "Elisa", "Felipe"])
    last = random.choice(["Souza", "Lima", "Costa", "Alves", "Rocha", "Dias"])
    payload = {
        "firstName": f"{first}{n}",
        "lastName": f"{last}{user.iteration}",
        "address": f"Rua {random.randint(1, 9999)}",
        "city": "São Paulo",
        "telephone": str(random.randint(2 * 10**9, 3 * 10**9 - 1)),
    }
    with user.client.post(
        "/api/customer/owners",
        json=payload,
        name=NAMES["create_owner"],
        catch_response=True,
    ) as resp:
        if resp.status_code in (200, 201):
            resp.success()
        else:
            resp.failure(f"HTTP {resp.status_code}")


# Monta a tabela de tarefas com os pesos do perfil ativo.
# Formato (callable, weight) é suportado nativamente pelo Locust.
TASKS = [
    (fn, PROFILE_WEIGHTS[PROFILE][op])
    for op, fn in (
        ("list_owners", list_owners),
        ("get_owner", get_owner),
        ("list_vets", list_vets),
        ("create_owner", create_owner),
    )
]


class PetClinicUser(HttpUser):
    """Usuário virtual do Locust para o PetClinic Microservices."""

    host = TARGET_HOST
    tasks = TASKS

    # pacing entre requisições de um mesmo usuário virtual
    wait_time = between(1.0, 2.0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner_ids: list[int] = []

    def on_start(self) -> None:
        """Ações iniciais: garante uma lista base de ids válidos para GET /owners/{id}."""
        log.info("Usuário iniciando (perfil=%s) -> %s", PROFILE, self.host)
        try:
            with self.client.get(
                "/api/customer/owners",
                name="on_start GET /api/customer/owners (aquecimento interno)",
                catch_response=True,
                timeout=15,
            ) as resp:
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                        if isinstance(body, list):
                            self.cache_owner_ids(body)
                    except (ValueError, TypeError):
                        pass
        except Exception as exc:  # noqa: BLE001 - mantém o usuário vivo nem que falhe
            log.warning("on_start falhou: %s", exc)

        # fallback: ids 1..10 existem na inicialização padrão do PetClinic
        if not self._owner_ids:
            self._owner_ids = list(range(1, 11))

    # ---------------------------------------------------------------- helpers
    def cache_owner_ids(self, owners_payload) -> None:
        body = owners_payload if isinstance(owners_payload, list) else owners_payload.get("content", [])
        ids = [o["id"] for o in body if isinstance(o, dict) and "id" in o]
        if ids:
            self._owner_ids = ids

    def pick_owner_id(self) -> int:
        if not self._owner_ids:
            return random.randint(1, 10)
        return random.choice(self._owner_ids)

    @property
    def user_id(self) -> str:
        return f"{random.randint(100, 999)}"

    @property
    def iteration(self) -> str:
        return str(random.randint(10, 99))
