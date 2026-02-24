# Docker VNC Orchestrator - Documentacao Completa

## Visao Geral

Orquestrador HTTP em Python que cria e gerencia containers Docker VNC sob demanda.
Cada cliente (identificado por CPF) recebe um container exclusivo com uma sessao
Firefox em modo kiosk, acessivel pelo navegador via noVNC.

O sistema mantem um **pool de containers pre-aquecidos** (warm pool) para que o
usuario receba resposta instantanea, sem esperar o healthcheck (~12s).

```
                                  +---------------------+
                                  |   Container VNC     |
                                  |   vnc_11122233344   |
  Cliente (CPF: 111.222.333-44)   |   porta 5000:6080   |
         |                        +---------------------+
         |
         v                        +---------------------+
  +----------------+              |   Container VNC     |
  |  Orquestrador  |------------>|   vnc_55566677788   |
  |  Flask :8080   |              |   porta 5001:6080   |
  +----------------+              +---------------------+
         |
         |                        +---------------------+
         +------- state.json      |   Container POOL    |
                                  |   vnc_pool_5002     |
                                  |   porta 5002:6080   |
                                  |   (pronto, sem CPF) |
                                  +---------------------+

         Todos na rede: vnc_network (10.10.0.0/24)
```

---

## Estrutura de Arquivos

```
docker-orchestrator/
  app.py              -> Setup Flask minimo (load_dotenv, Blueprint, __main__)
  routes.py           -> Rotas HTTP (Blueprint): valida params, chama services
  services.py         -> Logica de negocio: access, remove, reconciliacao, reciclagem
  containers.py       -> Operacoes Docker (criar, verificar, remover, rede)
  state.py            -> Persistencia em JSON com thread-safety
  scheduler.py        -> Agendador de limpeza automatica de containers ociosos
  warm_pool.py        -> Gerenciador do pool de containers pre-aquecidos
  wsgi.py             -> Entry point Gunicorn (reconciliacao + scheduler + pool no startup)
  requirements.txt    -> Dependencias Python
  Dockerfile          -> Imagem do orquestrador
  docker-compose.yml  -> Compose para rodar o orquestrador
  .env                -> Variaveis de ambiente locais
  .dockerignore       -> Arquivos ignorados no build
  docs/
    ARCHITECTURE.md   -> Este documento
```

---

## Rotas HTTP

### GET /access?id={CPF}[&width={W}&height={H}]

Rota principal. Atribui um container VNC ao CPF informado.

**Parametros:**
- `id` (obrigatorio): CPF do cliente
- `width` (opcional): Largura da tela em pixels
- `height` (opcional): Altura da tela em pixels

> **Regra das dimensoes:** `width` e `height` devem ser informados **juntos**.
> Se apenas um for enviado, ambos sao ignorados e o sistema usa os valores default
> das variaveis de ambiente (`VNC_WIDTH` / `VNC_HEIGHT`).

**Fluxo:**
1. Valida parametro `id`
2. Resolve dimensoes: se vieram ambos `width` e `height` -> usa custom; caso contrario usa ENVs
3. Busca registro no JSON pelo CPF
   - Se existe e container esta saudavel:
     - Dimensoes **iguais** -> atualiza `last_accessed_at` e redireciona (REUSO)
     - Dimensoes **diferentes** -> mata container, recria com novas dimensoes
   - Se existe mas container morreu -> remove registro, trata como novo
4. **Se NAO houver dimensoes custom**: tenta usar container do pool (`__pool__`) - atribuicao instantanea (POOL)
5. **Se houver dimensoes custom**: pula o pool (containers do pool usam dimensoes default)
6. Se nao tem pool ou dimensoes custom -> aloca porta livre, cria container com as dimensoes resolvidas, aguarda healthy (CRIACAO)

**Reciclagem automatica:**
Se todas as portas estao ocupadas, o sistema mata o container com `last_accessed_at`
mais antigo (quem esta ha mais tempo sem acessar) e reutiliza a porta.

**Reposicao do pool:**
Apos atribuir um container do pool ou criar um novo, o sistema repoe o pool
em background (cria novo container `__pool__` se houver porta livre).

**Respostas:**
- `302` -> Redirect para `https://{VNC_HOST}:{porta}`
- `400` -> `{"error": "Missing required parameter: id"}`
- `503` -> `{"error": "No available ports..."}`
- `500` -> `{"error": "Failed to create container: ..."}`

**Exemplos:**
```
# Dimensoes default (usa pool se disponivel)
GET http://localhost:8080/access?id=06798162320
-> 302 redirect para https://localhost:5001

# Dimensoes customizadas (pula pool, cria container dedicado)
GET http://localhost:8080/access?id=06798162320&width=1024&height=768
-> 302 redirect para https://localhost:5001

# Somente um parametro -> ignorado, usa default
GET http://localhost:8080/access?id=06798162320&width=1024
-> usa VNC_WIDTH e VNC_HEIGHT das ENVs
```

---

### GET /status

Lista todos os containers ativos e informacoes de estado.

**Resposta:**
```json
{
  "active_containers": 2,
  "pool_containers": 1,
  "max_slots": 20,
  "records": [
    {
      "client_id": "06798162320",
      "container_id": "b4dd386af519...",
      "container_name": "vnc_06798162320",
      "port": 5001,
      "width": "1024",
      "height": "768",
      "created_at": "2026-02-08T14:30:00.000000",
      "last_accessed_at": "2026-02-08T16:45:00.000000"
    },
    {
      "client_id": "__pool__",
      "container_id": "c5ee497bg620...",
      "container_name": "vnc_pool_5002",
      "port": 5002,
      "width": "410",
      "height": "900",
      "created_at": "2026-02-08T14:30:00.000000",
      "last_accessed_at": "2026-02-08T14:30:00.000000"
    }
  ]
}
```

---

### GET /remove?id={CPF}

Mata o container de um CPF especifico e remove o registro do JSON.
Apos remover, repoe o pool em background.

**Parametros:**
- `id` (obrigatorio): CPF do cliente

**Respostas:**
- `200` -> Container removido com sucesso
- `400` -> Parametro `id` ausente
- `404` -> Nenhum container encontrado para o CPF

**Exemplo:**
```
GET http://localhost:8080/remove?id=06798162320

{
  "status": "removed",
  "client_id": "06798162320",
  "container_id": "b4dd386af519...",
  "port": 5000
}
```

---

### GET /remove-all

Mata TODOS os containers VNC gerenciados (incluindo pool) e limpa o JSON.
Apos remover, repoe o pool em background.

**Resposta:**
```json
{
  "status": "removed_all",
  "removed": 4
}
```

Se nao houver containers:
```json
{
  "status": "empty",
  "removed": 0
}
```

---

### GET /health

Health check simples.

**Resposta:**
```json
{
  "status": "ok"
}
```

---

## Modulos

### app.py (Setup Flask)

Responsabilidades:
- Carregar `.env` com `load_dotenv()` (DEVE ser a primeira linha antes de qualquer import)
- Configurar logging
- Criar instancia Flask
- Registrar Blueprint de rotas

### routes.py (Camada HTTP)

Responsabilidades:
- Receber requisicoes HTTP
- Validar parametros
- Chamar funcoes de `services.py`
- Traduzir resultados para respostas HTTP (redirect, jsonify, status codes)

Funcoes:

| Funcao       | O que faz                                            |
|--------------|------------------------------------------------------|
| access()     | Rota /access - valida id, chama services, redirect   |
| status()     | Rota /status - retorna JSON do services              |
| remove()     | Rota /remove - valida id, chama services             |
| remove_all() | Rota /remove-all - chama services                    |
| health()     | Rota /health - retorna ok                            |

### services.py (Camada de Negocio)

Responsabilidades:
- Logica de orquestracao: acesso, remocao, reconciliacao
- Reciclagem automatica quando portas esgotam
- Integracao com pool de containers
- Nao conhece Flask (nao importa request/response)

Funcoes:

| Funcao                              | O que faz                                                         |
|-------------------------------------|-------------------------------------------------------------------|
| reconcile_on_startup()              | Sincroniza JSON com Docker real ao iniciar                        |
| get_or_create_access(id, w, h)      | Fluxo principal: reuso (com checagem de dimensoes) -> pool -> criacao |
| get_status()                        | Retorna dict com status (containers + pool)                       |
| remove_client(id)                   | Remove container de 1 CPF, repoe pool                             |
| remove_all_clients()                | Remove todos os containers, repoe pool                            |
| _recycle_oldest_container()         | Mata container mais antigo e retorna porta                        |

### containers.py (Camada Docker)

Responsabilidades:
- Comunicar com o Docker daemon via socket
- Gerenciar a rede Docker dedicada
- Criar containers com a imagem VNC configurada (com CPF ou pool)
- Aguardar container ficar healthy antes de redirecionar
- Verificar saude de containers
- Remover containers
- Alocar portas livres no range definido

Funcoes:

| Funcao                              | O que faz                                                      |
|-------------------------------------|----------------------------------------------------------------|
| log_config()                        | Loga toda a configuracao no startup                            |
| ensure_network()                    | Cria a rede Docker se nao existir                              |
| is_container_healthy(container_id)  | Retorna True se o container esta running                       |
| create_container(id, port, w, h)    | Cria container vnc_{cpf} com dimensoes resolvidas (custom/ENV) |
| create_pool_container(port)         | Cria container vnc_pool_{port} com dimensoes default das ENVs  |
| wait_container_ready(id, port)      | Aguarda Docker healthcheck reportar "healthy"                  |
| remove_container(container_id)      | Remove container com force=True                                |
| allocate_port(used)                 | Retorna a primeira porta livre no range                        |
| list_running_orchestrated_containers| Lista todos os containers vnc_* ativos                         |

### warm_pool.py (Pool de Containers)

Responsabilidades:
- Manter N containers pre-aquecidos e prontos sem CPF
- Repor pool automaticamente em background (thread daemon)
- So criar se houver porta disponivel

Funcoes:

| Funcao            | O que faz                                                     |
|-------------------|---------------------------------------------------------------|
| replenish_pool()  | Verifica pool e cria containers ate WARM_POOL_SIZE (background) |
| _fill_pool()      | Funcao interna que cria os containers necessarios             |

### scheduler.py (Limpeza Automatica)

Responsabilidades:
- Executar limpeza periodica de containers ociosos em background
- Remover containers que nao sao acessados ha mais de N horas
- Ignorar containers `__pool__` (sao reserva, nao ociosos)
- Repor pool apos limpeza liberar portas
- Rodar como thread daemon (nao bloqueia shutdown da aplicacao)

Funcoes:

| Funcao                        | O que faz                                           |
|-------------------------------|-----------------------------------------------------|
| start_scheduler()             | Inicia o agendador de limpeza periodica             |
| stop_scheduler()              | Para o agendador (cancela o timer)                  |
| _cleanup_idle_containers()    | Executa a limpeza: remove containers ociosos        |
| _schedule_next()              | Agenda a proxima execucao do cleanup                |

### state.py (Camada de Persistencia)

Responsabilidades:
- Ler e gravar o arquivo JSON
- Garantir thread-safety com threading.Lock
- Escrita atomica (grava em .tmp e faz replace)
- Criar o arquivo automaticamente se nao existir
- Rastrear ultimo acesso de cada cliente
- Gerenciar registros do pool (`__pool__`)

Funcoes:

| Funcao                           | O que faz                                                        |
|----------------------------------|------------------------------------------------------------------|
| load_records()                   | Carrega todos os registros do JSON                               |
| save_records(records)            | Salva lista de registros no JSON                                 |
| find_by_client(client_id)        | Busca registro por CPF                                           |
| add_record(..., width, height)   | Adiciona registro com dimensoes (nunca duplica client_id)        |
| touch_client(client_id)          | Atualiza last_accessed_at do CPF                                 |
| find_oldest_accessed()           | Retorna registro com last_accessed_at mais antigo                |
| remove_by_client(id)             | Remove registro pelo CPF                                         |
| used_ports()                     | Retorna set de portas em uso                                     |
| find_unassigned()                | Retorna lista de registros __pool__                              |
| claim_pool_container(cpf, w, h)  | Atribui container __pool__ a um CPF e grava dimensoes no registro|

---

## Estrutura do JSON (state.json)

```json
[
  {
    "client_id": "06798162320",
    "container_id": "b4dd386af519a1b2c3d4e5f6...",
    "container_name": "vnc_06798162320",
    "port": 5001,
    "width": "1024",
    "height": "768",
    "created_at": "2026-02-08T14:30:00.000000",
    "last_accessed_at": "2026-02-08T16:45:00.000000"
  },
  {
    "client_id": "__pool__",
    "container_id": "c5ee497bg620a1b2c3d4e5f6...",
    "container_name": "vnc_pool_5002",
    "port": 5002,
    "width": "410",
    "height": "900",
    "created_at": "2026-02-08T14:30:00.000000",
    "last_accessed_at": "2026-02-08T14:30:00.000000"
  }
]
```

| Campo            | Tipo   | Descricao                                                          |
|------------------|--------|--------------------------------------------------------------------|
| client_id        | string | CPF do cliente ou `__pool__` (container reserva)                   |
| container_id     | string | ID completo do container Docker                                    |
| container_name   | string | Nome: `vnc_{CPF}` ou `vnc_pool_{porta}`                            |
| port             | int    | Porta mapeada no host                                              |
| width            | string | Largura da tela (pixels) usada na criacao do container             |
| height           | string | Altura da tela (pixels) usada na criacao do container              |
| created_at       | string | Data/hora ISO de criacao                                           |
| last_accessed_at | string | Data/hora ISO do ultimo acesso                                     |

> **Nota:** Os campos `width` e `height` sao usados para detectar mudanca de resolucao.
> Se uma nova requisicao chegar com dimensoes diferentes das gravadas, o container antigo
> e destruido e um novo e criado com as novas dimensoes.

---

## Fluxo Principal (/access?id={CPF}[&width={W}&height={H}])

```
Requisicao: GET /access?id=11122233344[&width=W&height=H]
        |
        v
  [1] Parametro "id" existe?
        |
     NAO -> Retorna 400
        |
      SIM
        v
  [2] Resolve dimensoes:
        - Vieram AMBOS width e height? -> custom_dimensions=True, usa os valores
        - Veio so 1 ou nenhum?         -> custom_dimensions=False, usa VNC_WIDTH/VNC_HEIGHT das ENVs
        |
        v
  [3] Busca registro no JSON pelo CPF
        |
   ENCONTROU
        |
        v
  [4] Container esta running?
        |
      SIM -> Dimensoes do registro == dimensoes da requisicao?
               SIM -> Atualiza last_accessed_at -> Redirect (REUSO)
               NAO -> Remove container + registro (dimensoes mudaram)
                      Segue para [5]
        |
      NAO -> Remove registro + container morto
             Segue para [5]
        |
  NAO ENCONTROU
        |
        v
  [5] custom_dimensions == False?
        |
      SIM -> Tem container __pool__ disponivel?
               SIM -> Atribui CPF + grava dimensoes no registro
                      Redirect (POOL - instantaneo!)
                      replenish_pool() em background
               NAO -> Segue para [6]
        |
      NAO (custom) -> Pula o pool diretamente para [6]
        v
  [6] Aloca porta livre no range
        |
   SEM PORTA LIVRE
        |
        v
  [7] Reciclagem automatica
        - Encontra container com last_accessed_at mais antigo
        - Mata o container
        - Remove registro
        - Reutiliza a porta
        |
   SEM NENHUM REGISTRO -> Retorna 503
        |
   PORTA ALOCADA
        v
  [8] Cria container Docker com dimensoes resolvidas
        - Nome: vnc_{CPF}
        - Imagem: VNC_IMAGE
        - Porta: {porta}:6080
        - Rede: vnc_network
        - ENV WIDTH, HEIGHT (custom ou default)
        |
   FALHOU -> Retorna 500
        |
    CRIOU
        v
  [9] Aguarda container ficar healthy (~12s)
        |
        v
  [10] Persiste no JSON (inclui width e height)
        |
        v
  [11] Redirect (CRIACAO)
       replenish_pool() em background
```

---

## Pool de Containers Pre-aquecidos (Warm Pool)

O `warm_pool.py` mantem N containers Docker ja iniciados e saudaveis, sem CPF
atribuido, prontos para serem usados instantaneamente.

```
STARTUP:
  reconcile -> scheduler -> replenish_pool()
                              |
                              v
                         Porta livre? -> Cria N containers vnc_pool_* (background)
                         (usando dimensoes default VNC_WIDTH / VNC_HEIGHT das ENVs)

/access?id=CPF [sem width/height customizados]:
  1. CPF ja tem container com mesmas dimensoes?  -> REUSO (atualiza timestamp)
  2. CPF tem container com dimensoes diferentes? -> MATA + RECRIA com novas dimensoes
  3. Tem container __pool__ pronto?              -> ATRIBUI CPF (0s de espera!)
     -> replenish_pool() em background (repoe o pool)
  4. Sem pool disponivel                         -> CRIA novo container (~12s)
     -> replenish_pool() em background

/access?id=CPF&width=W&height=H [com dimensoes customizadas]:
  1. CPF ja tem container com mesmas dimensoes?  -> REUSO (atualiza timestamp)
  2. CPF tem container com dimensoes diferentes? -> MATA + RECRIA com novas dimensoes
  3. PULA o pool (pool usa dimensoes default, nao custom)
  4. CRIA novo container com WIDTH=W, HEIGHT=H (~12s)
     -> replenish_pool() em background

/remove ou /remove-all:
  -> Apos remover, replenish_pool() em background (porta liberada)

Cleanup (scheduler):
  -> Apos limpar containers ociosos, replenish_pool() em background
```

**Configuracao:**

| Variavel        | Default | Descricao                                         |
|-----------------|---------|---------------------------------------------------|
| WARM_POOL_SIZE  | 1       | Numero de containers pre-aquecidos sem CPF         |

Se `WARM_POOL_SIZE=0`, o pool e desabilitado e o comportamento e identico ao antigo
(cria container sob demanda com espera do healthcheck).

---

## Reconciliacao no Startup

Quando o orquestrador (re)inicia, `reconcile_on_startup()` garante consistencia:

```
  [1] Loga toda a configuracao (ENVs, imagem, portas, rede, pool)
  [2] Le registros do JSON
  [3] Lista containers vnc_* rodando no Docker
      |
      v
  Para cada registro no JSON:
      - Container running?     -> Mantem no JSON
      - Container morreu?      -> Remove registro + container
      - Registro duplicado?    -> Remove container + descarta
      |
      v
  Para cada container vnc_* rodando SEM registro no JSON:
      - vnc_pool_* -> Recupera como __pool__
      - vnc_{CPF}  -> Recupera com CPF extraido do nome
      |
      v
  Salva JSON limpo
```

---

## Limpeza Automatica de Containers Ociosos

O `scheduler.py` roda uma thread em background que periodicamente verifica
containers que nao foram acessados ha mais de `IDLE_TIMEOUT_HOURS` horas
e os remove automaticamente. Containers `__pool__` sao ignorados (sao reserva).

```
  A cada CLEANUP_INTERVAL_MINUTES (default: 30 min):
      |
      v
  [1] Carrega registros do JSON
  [2] Para cada registro:
      - Se __pool__ -> pula (nao e ocioso)
      - Calcula tempo ocioso: now - last_accessed_at
      - Se ocioso > IDLE_TIMEOUT_HOURS:
          -> Mata o container Docker
          -> Remove registro do JSON
      - Se nao:
          -> Pula (container ainda ativo)
  [3] Loga total de removidos
  [4] Se removeu algum -> replenish_pool() (repoe pool com portas liberadas)
  [5] Agenda proxima execucao
```

---

## Rede Docker

Todos os containers VNC sao criados em uma rede Docker dedicada com subnet configuravel.

| Configuracao       | Descricao                                           |
|--------------------|-----------------------------------------------------|
| Nome da rede       | Configuravel via DOCKER_NETWORK_NAME                |
| Subnet             | Configuravel via DOCKER_NETWORK_SUBNET              |
| Driver             | bridge                                              |
| Criacao automatica | Se a rede nao existir, e criada automaticamente     |

Isso evita conflito com redes existentes no servidor de producao.

---

## Portas da Imagem VNC

A imagem `firefox-flash-kiosk` expoe duas portas:

| Porta | Protocolo | Funcao                                         |
|-------|-----------|------------------------------------------------|
| 6080  | TCP       | noVNC - acesso VNC pelo navegador via HTTP     |
| 5900  | TCP       | VNC nativo - para clientes VNC desktop         |

O orquestrador mapeia apenas a porta 6080 (acesso web).

---

## Mapeamento de Portas

```
Host                              Container
 :5000  ---- vnc_cpf1 ----------> :6080 (noVNC)
 :5001  ---- vnc_cpf2 ----------> :6080 (noVNC)
 :5002  ---- vnc_pool_5002 -----> :6080 (noVNC) [POOL - pronto]
 :5003  ---- vnc_cpf3 ----------> :6080 (noVNC)

 :8080  ---- orquestrador ------> Flask API
```

---

## Variaveis de Ambiente

### Orquestrador

| Variavel                 | Default                      | Descricao                              |
|--------------------------|------------------------------|----------------------------------------|
| VNC_HOST                 | localhost                    | Host usado na URL de redirect          |
| VNC_IMAGE                | ghcr.io/giovannemendonca/... | Imagem Docker dos containers VNC       |
| VNC_CONTAINER_PORT       | 6080                         | Porta interna do container (noVNC web) |
| PORT_RANGE_MIN           | 5000                         | Inicio do range de portas do host      |
| PORT_RANGE_MAX           | 5003                         | Fim do range de portas do host         |
| ORCHESTRATOR_PORT        | 8080                         | Porta do proprio orquestrador          |
| STATE_FILE               | state.json                   | Caminho do arquivo de estado           |
| DOCKER_NETWORK_NAME      | vnc_network                  | Nome da rede Docker dedicada           |
| DOCKER_NETWORK_SUBNET    | 10.10.0.0/24                 | Subnet da rede (evitar conflito)       |
| IDLE_TIMEOUT_HOURS       | 8                            | Horas de inatividade para limpeza      |
| CLEANUP_INTERVAL_MINUTES | 30                           | Intervalo (min) entre limpezas         |
| WARM_POOL_SIZE           | 1                            | Qtd de containers pre-aquecidos        |

### Repassadas aos Containers VNC

| Variavel do Orquestrador | ENV no Container | Default                           |
|--------------------------|------------------|-----------------------------------|
| VNC_APPNAME              | APPNAME          | firefox-kiosk https://google.com  |
| VNC_WIDTH                | WIDTH            | 410                               |
| VNC_HEIGHT               | HEIGHT           | 900                               |

---

## Sistema de Logs

Todas as operacoes sao logadas com tags para facilitar filtragem:

| Tag           | Modulo         | O que registra                              |
|---------------|----------------|---------------------------------------------|
| [ACCESS]      | services.py    | Requisicoes de acesso, reuso, pool, criacao  |
| [RECYCLE]     | services.py    | Reciclagem automatica de containers          |
| [RECONCILE]   | services.py    | Reconciliacao no startup                     |
| [STATUS]      | services.py    | Consultas de status                          |
| [REMOVE]      | services/cont. | Remocao de containers individuais            |
| [REMOVE-ALL]  | services.py    | Remocao em massa                             |
| [CREATE]      | containers.py  | Criacao de containers (CPF e pool)           |
| [WAIT]        | containers.py  | Espera por healthcheck                       |
| [NETWORK]     | containers.py  | Criacao/reuso de rede Docker                 |
| [PORT]        | containers.py  | Alocacao de portas                           |
| [SCAN]        | containers.py  | Varredura de containers rodando              |
| [HEALTH CHECK]| containers.py  | Verificacao de saude de container            |
| [STATE]       | state.py       | Operacoes de leitura/escrita no JSON         |
| [CLEANUP]     | scheduler.py   | Limpeza automatica de containers ociosos     |
| [POOL]        | warm_pool.py   | Pool de containers pre-aquecidos             |

Exemplo de saida no terminal:
```
========== STARTUP RECONCILIATION ==========
========== DOCKER CONFIG ==========
  IMAGE           = ghcr.io/giovannemendonca/firefox-flash-kiosk:4bda8f1...
  CONTAINER_PORT  = 6080
  PORT_RANGE      = 5000 - 5003 (4 slots)
  APPNAME         = firefox-kiosk https://youtube.com
  WIDTH           = 410
  HEIGHT          = 900
  NETWORK_NAME    = vnc_network
  NETWORK_SUBNET  = 10.10.0.0/24
====================================
[RECONCILE] WARM_POOL_SIZE = 1
[RECONCILE] Done: 0 active records (0 clients + 0 pool) after reconciliation
=============================================

========== CLEANUP SCHEDULER ==========
[CLEANUP] IDLE_TIMEOUT_HOURS      = 8
[CLEANUP] CLEANUP_INTERVAL_MINUTES = 30
=======================================

[POOL] Replenishing pool: current=0 target=1 need=1
[POOL] Creating pool container on port 5000...
[CREATE] Starting POOL creation: name=vnc_pool_5000 port=5000
[WAIT] Container abc123 is HEALTHY (took 12.3s)
[POOL] Pool container READY: name=vnc_pool_5000 port=5000 (1/1)

========== ORCHESTRATOR RUNNING on port 8080 ==========

[ACCESS] -------- Request for CPF=06798162320 --------
[ACCESS] No existing record for CPF=06798162320
[STATE] CLAIM pool: container=abc123 port=5000 -> CPF=06798162320
[ACCESS] POOL -> assigned container=abc123 port=5000 to CPF=06798162320 (instant!)
[POOL] Replenishing pool: current=0 target=1 need=1
[POOL] Creating pool container on port 5001...
```

---

## Garantias do Sistema

1. **Um container por CPF**: O JSON nunca permite duplicatas de client_id
2. **Reuso obrigatorio**: Se o container esta running, redireciona sem criar novo
3. **Pool pre-aquecido**: Containers prontos para atribuicao instantanea
4. **Reposicao automatica do pool**: Apos atribuir, remover ou limpar, repoe em background
5. **Reciclagem automatica**: Quando portas esgotam, mata o container com acesso mais antigo
6. **Aguarda container pronto**: Espera Docker healthcheck reportar "healthy"
7. **Sobrevive a restart**: Reconciliacao sincroniza JSON com Docker real
8. **Sem banco de dados**: Apenas arquivo JSON local
9. **Thread-safe**: Lock em todas as operacoes de leitura/escrita do JSON
10. **Escrita atomica**: Grava em .tmp e faz replace para evitar corrupcao
11. **Rede dedicada**: Subnet configuravel para evitar conflito em producao
12. **Limpeza automatica**: Remove containers ociosos a cada N minutos (configuravel)
13. **Separacao de responsabilidades**: Routes (HTTP) / Services (negocio) / Containers (Docker)

---

## Como Rodar

### Direto com Python (desenvolvimento)
```bash
pip install -r requirements.txt
python app.py
```

### Com Docker Compose (producao)
```bash
docker compose up -d
```

### Testando
```bash
# Criar/acessar container para um CPF
curl -L http://localhost:8080/access?id=11122233344

# Ver containers ativos (inclui pool)
curl http://localhost:8080/status

# Remover container de um CPF
curl http://localhost:8080/remove?id=11122233344

# Remover TODOS os containers (incluindo pool)
curl http://localhost:8080/remove-all

# Health check
curl http://localhost:8080/health
```

### Customizar via .env
```env
VNC_HOST=192.168.1.100
VNC_WIDTH=1024
VNC_HEIGHT=768
VNC_APPNAME=firefox-kiosk https://meu-site.com/
PORT_RANGE_MIN=7000
PORT_RANGE_MAX=7050
DOCKER_NETWORK_SUBNET=10.20.0.0/24
IDLE_TIMEOUT_HOURS=8
CLEANUP_INTERVAL_MINUTES=30
WARM_POOL_SIZE=2
```

---

## Scripts de Inicialização

### Arquivo: start.sh

Script Bash para Linux que inicia o Docker Orchestrator em background (segundo plano).

**Primeira utilização:**
```bash
chmod +x start.sh
./start.sh
```

**O que o script faz automaticamente:**
- ✅ Cria ambiente virtual (venv/) se não existir
- ✅ Ativa o ambiente virtual
- ✅ Instala dependências do requirements.txt
- ✅ Cria diretório logs/
- ✅ Inicia a aplicação em background
- ✅ Salva PID em arquivo orchestrator.pid

**Comandos:**
```bash
# Iniciar
./start.sh

# Parar
./start.sh stop

# Ver logs em tempo real
tail -f logs/app.log.$(date +%Y-%m-%d)

# Ver últimas 50 linhas
tail -50 logs/app.log.$(date +%Y-%m-%d)

# Procurar erros
grep ERROR logs/app.log.$(date +%Y-%m-%d)

# Ver status do processo
ps aux | grep app.py
```

**Vantagens:**
- Terminal fica livre para outras tarefas
- Aplicação continua rodando mesmo após fechar o terminal
- Logs separados por data em `logs/app.log.YYYY-MM-DD`
- Fácil parar com `./start.sh stop`

---

## Sistema de Logs

### Localização e Estrutura

Os logs são salvos automaticamente pelo app.py em:
```
logs/app.log.YYYY-MM-DD
```

Exemplo:
```
logs/
├── app.log.2026-02-13  ← Logs de hoje (arquivo ativo)
├── app.log.2026-02-12  ← Logs de ontem
├── app.log.2026-02-11
├── app.log.2026-02-10
├── app.log.2026-02-09
├── app.log.2026-02-08
├── app.log.2026-02-07
└── (arquivos com 8+ dias são automaticamente deletados)
```

**Características:**
- Um arquivo por dia (rotação automática à meia-noite)
- Mantém 7 dias de histórico
- Sem confusão de múltiplos arquivos
- Logs aparecem no arquivo conforme a aplicação roda

### Configuração Técnica

Implementado em `app.py` usando `TimedRotatingFileHandler`:

```python
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

# Cria pasta logs/ se não existir
logs_dir = "logs"
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

# Data atual
current_date = datetime.now().strftime("%Y-%m-%d")
log_filename = os.path.join(logs_dir, f"app.log.{current_date}")

# Handler com rotação diária
file_handler = TimedRotatingFileHandler(
    filename=log_filename,
    when="midnight",      # Rotaciona à meia-noite
    interval=1,          # A cada dia
    backupCount=7,       # Mantém 7 dias
    utc=False,          # Usa horário local
)
file_handler.suffix = "%Y-%m-%d"
```

### Retenção de Logs

| Configuração | Valor |
|--------------|-------|
| Intervalo de rotação | Diário (à meia-noite) |
| Formato do arquivo | app.log.YYYY-MM-DD |
| Dias mantidos | 7 dias |
| Limpeza automática | Sim (arquivos com 8+ dias) |

### Exemplos de Uso

```bash
# Ver logs de hoje em tempo real
tail -f logs/app.log.$(date +%Y-%m-%d)

# Ver logs de ontem
tail -f logs/app.log.$(date -d yesterday +%Y-%m-%d)

# Ver últimas 50 linhas
tail -50 logs/app.log.$(date +%Y-%m-%d)

# Contar erros de hoje
grep -c ERROR logs/app.log.$(date +%Y-%m-%d)

# Procurar um CPF específico
grep "06798162320" logs/app.log.$(date +%Y-%m-%d)

# Ver WARNING
grep WARNING logs/app.log.$(date +%Y-%m-%d)

# Ver todos os logs dos últimos 7 dias
tail -f logs/app.log.*
```

### Tags de Log para Filtragem

Os logs incluem tags dos módulos para fácil filtragem:

```bash
# Ver apenas reconciliação
grep "\[RECONCILE\]" logs/app.log.$(date +%Y-%m-%d)

# Ver apenas acessos
grep "\[ACCESS\]" logs/app.log.$(date +%Y-%m-%d)

# Ver apenas criação de containers
grep "\[CREATE\]" logs/app.log.$(date +%Y-%m-%d)

# Ver apenas limpeza automática
grep "\[CLEANUP\]" logs/app.log.$(date +%Y-%m-%d)

# Ver apenas pool
grep "\[POOL\]" logs/app.log.$(date +%Y-%m-%d)
```
