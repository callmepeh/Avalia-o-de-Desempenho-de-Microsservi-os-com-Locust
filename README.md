# Avaliação de Desempenho de Microsserviços com Locust — Trabalho Prático 06

Repositório da entrega do **Trabalho Prático 06**, avaliando o desempenho do
[Spring PetClinic Microservices](https://github.com/spring-petclinic/spring-petclinic-microservices)
com o [Locust](https://locust.io/), medindo o impacto da quantidade de usuários
virtuais e de diferentes perfis de requisições.

**Vídeo demonstrativo (4–6 min):** `<<COLE AQUI O LINK DO VÍDEO>>`

---

## 1. Estrutura do repositório

```
.
├── locustfile.py               # Locustfile com os DOIS perfis de carga (leitura/escrita)
├── docker-compose.yml          # Sobe o PetClinic Microservices (imagens oficiais)
├── requirements.txt            # Dependências (locust, pandas, matplotlib)
├── scripts/
│   ├── run_experiments.sh      # Executa os 60 experimentos (2 perfis x 3 cenários x 10 reps)
│   ├── collect_stats.sh        # Amostra CPU/memória dos contêineres (docker stats)
│   └── analyze.py              # Descarta aquecimento, gera tabelas e gráficos
└── results/
    ├── raw/                    # CSVs brutos do Locust e do docker stats (1 CSV por execução)
    ├── tables/                 # Tabelas agregadas (resumo_geral, operacoes, cpu_servicos)
    └── charts/                 # Gráficos comparativos (*.png)
```

## 2. Descrição do ambiente

| Item | Descrição |
|---|---|
| Aplicação | Spring PetClinic Microservices (config-server, discovery-server/Eureka, api-gateway, customers-service, visits-service, vets-service) |
| Execução | Docker Compose (`docker-compose.yml`, imagens oficiais `springcommunity/*`) |
| Geração de carga | Locust (headless), 1 processo por execução |
| Monitoramento | `docker stats` (CPU/memória por contêiner) |
| S.O. / CPU / RAM | `<<preencher: p.ex. Ubuntu 24.04 / 8 vCPU / 16 GB RAM>>` |
| Docker | `<<preencher: docker --version, docker compose version>>` |
| Locust (`locust --version`) | `<<preencher>>` |

## 3. Perfis de carga (implementados em `locustfile.py`)

| Operação | Perfil 1 — Leitura (`PROFILE=read`) | Perfil 2 — Escrita (`PROFILE=write`) |
|---|---|---|
| `GET /owners` | 45% | 20% |
| `GET /owners/{id}` | 35% | 20% |
| `GET /vets` | 15% | 20% |
| `POST /owners` | 5% | 40% |

Os Endpoints usados são os do API Gateway (`:8080`), verificados na versão
executada da aplicação:

- `GET  /api/customer/owners`
- `GET  /api/customer/owners/{id}`  (ids válidos lidos a partir da lista de owners)
- `GET  /api/vet/vets`
- `POST /api/customer/owners`

Cada usuário virtual escolhe a próxima operação ponderadamente pelo perfil ativo
(`tasks = [(função, peso), ...]` no Locust), com espera de 1–2 s entre requisições.

## 4. Cenários experimentais e metodologia

| Cenário | Usuários | Duração (medição) | Aquecimento (descartado) | Repetições |
|---|---|---|---|---|
| A — Leve | 30 | 6 min | 1 min | 10 |
| B — Moderado | 80 | 6 min | 1 min | 10 |
| C — Elevado | 150 | 6 min | 1 min | 10 |

- **60 execuções** no total: 2 perfis × 3 cenários × 10 repetições.
- **Aquecimento:** cada repetição executa `1 min` em um processo Locust separado
  (`*_warmup*`, não considerado pela análise) e depois **6 min de medição**.
  O resultado do aquecimento é, portanto, **descartado por construção**.
- A taxa de subida de usuários (ramp-up) sempre leva ~30 s, garantindo que a
  medição ocorra com a carga plena do cenário.
- **Métricas coletadas por repetição:** tempo médio (ms), P95 (ms), vazão (req/s),
  total de requisições, taxa de falhas (%) — via CSV do Locust — e utilização de
  CPU dos contêineres `customers-service`, `vets-service`, `visits-service` e
  `api-gateway` (amostras de 10 s via `docker stats`).
- Os resultados das repetições são agregados por média (e desvio padrão) em
  `scripts/analyze.py`.

## 5. Instruções de reprodução

### 5.1 Subir a aplicação

```bash
docker compose up -d --wait      # baixa as imagens e espera os healthchecks
./scripts/verificar_endpoints.sh # valida os 4 endpoints do gateway (opcional)
```

Acesse `http://localhost:8080` (UI) e `http://localhost:8761` (Eureka).

> Requisitos: Docker + Docker Compose. Portas usadas: 8080, 8761, 8888,
> 8081, 8082, 8083.
> Se a porta 8080 do host já estiver ocupada, suba com
> `GATEWAY_PORT=18080 docker compose up -d --wait` e use
> `TARGET_HOST=http://localhost:18080` no Locust/run_experiments.sh.

### 5.2 Instalar as dependências do Locust

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5.3 Teste rápido do Locust (opcional)

```bash
PROFILE=read locust -f locustfile.py --headless -u 5 -r 1 -t 30s \
  --csv smoke_read --only-summary
PROFILE=write locust -f locustfile.py --headless -u 5 -r 1 -t 30s \
  --csv smoke_write --only-summary
```

### 5.4 Executar os 60 experimentos

```bash
./scripts/run_experiments.sh                      # matriz completa (~7 h)
./scripts/run_experiments.sh --dryrun            # só lista os 60 runs
./scripts/run_experiments.sh --profiles read     # só o Perfil 1 (~3.5 h)
./scripts/run_experiments.sh --users 30 --reps 2 # subconjunto (para testes)
```

### 5.5 Gerar tabelas e gráficos

```bash
python3 scripts/analyze.py
```

Gera `results/tables/*.md|csv` (resumo geral, por operação, CPU por serviço e
`numeros_chave.md`) e `results/charts/*.png`.

## 6. Resultados

As tabelas completas estão em [`results/tables/resumo_geral.md`](results/tables/resumo_geral.md),
[`results/tables/operacoes.md`](results/tables/operacoes.md) e
[`results/tables/cpu_servicos.md`](results/tables/cpu_servicos.md). Os CSVs
brutos de cada uma das 60 execuções estão em `results/raw/`.

### 6.1 Resumo geral (média das 10 repetições, aquecimento descartado)

![Tempo médio](results/charts/tempo_medio_vs_usuarios.png)
![P95](results/charts/p95_vs_usuarios.png)
![Vazão](results/charts/vazao_vs_usuarios.png)
![Falhas](results/charts/falhas_vs_usuarios.png)
![CPU](results/charts/cpu_vs_usuarios.png)
![Operações](results/charts/operacoes_vs_cenarios.png)

### 6.2 Utilização de CPU por serviço

Os dois serviços monitorados de acordo com o requisito são `customers-service`
e `vets-service` (além de `visits-service` e `api-gateway` por contexto).
Detalhes em [`results/tables/cpu_servicos.md`](results/tables/cpu_servicos.md).

## 7. Análise dos resultados — respostas às questões

> Os números preenchidos abaixo vêm de `results/tables/numeros_chave.md`,
> gerado por `scripts/analyze.py` a partir das 60 execuções.

**1. Como o aumento de usuários afeta o tempo de resposta?**

Aumento no número de usuários eleva gradualmente o tempo médio de resposta,
até o cenário elevado (150u), onde há degradação mais intensa do P95, indicando
aproximação da capacidade de processamento dos serviços. Números: tempo médio
mínimo de `___ ms` e P95 máximo de `___ ms` (ver `numeros_chave.md`).

**2. Qual perfil apresenta maior vazão?**

O perfil de leitura (`read`) apresenta maior vazão, pois é composto
majoritariamente por operações GET baratas, enquanto no perfil de escrita 40%
das requisições são `POST /owners`, que custam mais no `customers-service`.
Maior vazão observada: `___ req/s` (config `___`).

**3. Quais operações apresentam maior degradação?**

Comparando 30u → 150u em `results/tables/operacoes.md`, `POST /owners` tende a
degradar mais (escrita no banco e maior custo no `customers-service`), e entre
as leituras, `GET /owners` responde mais dados por chamada. Conforme os dados:
`___`, `___`.

**4. Como o consumo de CPU varia entre os cenários?**

O consumo de CPU dos serviços cresce com o número de usuários e satura a partir
do cenário moderado/elevado, quando a vazão deixa de crescer na mesma
proporção. `customers-service` concentra o maior uso por receber `GET/POST /owners`.
Médias: ver `results/tables/cpu_servicos.md`.

**5. Qual cenário apresenta maior taxa de falhas?**

O cenário elevado (150 usuários) apresenta a maior taxa de falhas, por timeouts
em cascata entre API Gateway e os microsserviços. Taxa máxima: `___ %`
(config `___`).

> **Importante:** após rodar os experimentos, substitua os trechos `___` pelos
> números reais de `results/tables/numeros_chave.md` e ajuste o texto conforme
> os gráficos observados.

## 8. Conclusões

Com o aumento do número de usuários, o PetClinic Microservices mostra
degradação progressiva de tempo de resposta e CPU até o limite de escalonamento
dos contêineres. O perfil de leitura sustenta maior vazão; o perfil de escrita
domina a taxa de erros sob alta carga, em função do custo das `POST`.
Em ambiente com limites de CPU/memória (Docker), aumentar usuários sem aumentar
recursos leva a acúmulo de filas no gateway e timeouts internos entre os
serviços.

Referências aplicadas para chegar a esta conclusão: tabelas de
`results/tables/` e gráficos de `results/charts/`.
