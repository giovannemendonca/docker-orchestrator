# Docker VNC Orchestrator - Documentacao Completa

## Visao Geral

Orquestrador HTTP em Python que cria e gerencia containers Docker VNC sob demanda.
Cada cliente (identificado por CPF) recebe um container exclusivo com uma sessao
Firefox em modo kiosk, acessivel pelo navegador via noVNC.

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
         +------- state.json      |   Container VNC     |
                                  |   vnc_99900011122   |
                                  |   porta 5002:6080   |
                                  +---------------------+

         Todos na rede: vnc_network (10.10.0.0/24)
```

---

## Estrutura de Arquivos

```
docker-orchestrator/
  app.py              -> Aplicacao Flask (rotas HTTP + reconciliacao)
  containers.py       -> Operacoes Docker (criar, verificar, remover, rede)
  state.py            -> Persistencia em JSON com thread-safety
  wsgi.py             -> Entry point Gunicorn (reconciliacao no startup)
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

### GET /access?id={CPF}

Rota principal. Cria ou reutiliza um container VNC para o CPF informado.

**Parametros:**
- `id` (obrigatorio): CPF do cliente

**Fluxo:**
1. Valida parametro `id`
2. Busca registro no JSON pelo CPF
3. Se existe e container esta saudavel -> atualiza `last_accessed_at` e redireciona
4. Se existe mas container morreu -> remove registro, trata como novo
5. Se nao existe -> aloca porta livre, cria container, aguarda healthy, redireciona

**Reciclagem automatica:**
Se todas as portas estao ocupadas, o sistema mata o container com `last_accessed_at`
mais antigo (quem esta ha mais tempo sem acessar) e reutiliza a porta.

**Respostas:**
- `302` -> Redirect para `http://{VNC_HOST}:{porta}`
- `400` -> `{"error": "Missing required parameter: id"}`
- `503` -> `{"error": "No available ports..."}`
- `500` -> `{"error": "Failed to create container: ..."}`

**Exemplo:**
```
GET http://localhost:8080/access?id=06798162320
-> 302 redirect para http://localhost:5000
```

---

### GET /status

Lista todos os containers ativos e informacoes de estado.

**Resposta:**
```json
{
  "active_containers": 3,
  "max_slots": 4,
  "records": [
    {
      "client_id": "06798162320",
      "container_id": "b4dd386af519...",
      "container_name": "vnc_06798162320",
      "port": 5000,
      "created_at": "2026-02-08T14:30:00.000000",
      "last_accessed_at": "2026-02-08T16:45:00.000000"
    }
  ]
}
```

---

### GET /remove?id={CPF}

Mata o container de um CPF especifico e remove o registro do JSON.

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

Mata TODOS os containers VNC gerenciados e limpa o JSON.

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

### app.py (Camada HTTP)

Responsabilidades:
- Receber requisicoes HTTP e orquestrar o fluxo
- Redirecionar o cliente para a porta correta
- Reconciliar estado ao iniciar (startup)
- Reciclagem automatica quando portas esgotam

Funcoes:

| Funcao                    | O que faz                                           |
|---------------------------|-----------------------------------------------------|
| _reconcile_on_startup()   | Sincroniza JSON com Docker real ao iniciar           |
| access()                  | Rota /access - cria ou reutiliza container           |
| status()                  | Rota /status - lista containers ativos               |
| remove()                  | Rota /remove - mata container de um CPF              |
| remove_all()              | Rota /remove-all - mata todos os containers          |
| health()                  | Rota /health - health check                          |

### containers.py (Camada Docker)

Responsabilidades:
- Comunicar com o Docker daemon via socket
- Gerenciar a rede Docker dedicada
- Criar containers com a imagem VNC configurada
- Aguardar container ficar healthy antes de redirecionar
- Verificar saude de containers
- Remover containers
- Alocar portas livres no range definido

Funcoes:

| Funcao                              | O que faz                                        |
|-------------------------------------|--------------------------------------------------|
| log_config()                        | Loga toda a configuracao no startup              |
| ensure_network()                    | Cria a rede Docker se nao existir                |
| is_container_healthy(container_id)  | Retorna True se o container esta running         |
| create_container(client_id, port)   | Cria container vnc_{cpf} na porta especificada   |
| wait_container_ready(id, port)      | Aguarda Docker healthcheck reportar "healthy"    |
| remove_container(container_id)      | Remove container com force=True                  |
| allocate_port(used)                 | Retorna a primeira porta livre no range          |
| list_running_orchestrated_containers| Lista todos os containers vnc_* ativos           |

### state.py (Camada de Persistencia)

Responsabilidades:
- Ler e gravar o arquivo JSON
- Garantir thread-safety com threading.Lock
- Escrita atomica (grava em .tmp e faz replace)
- Criar o arquivo automaticamente se nao existir
- Rastrear ultimo acesso de cada cliente

Funcoes:

| Funcao                    | O que faz                                           |
|---------------------------|-----------------------------------------------------|
| load_records()            | Carrega todos os registros do JSON                  |
| save_records(records)     | Salva lista de registros no JSON                    |
| find_by_client(client_id) | Busca registro por CPF                              |
| add_record(...)           | Adiciona registro (nunca duplica client_id)         |
| touch_client(client_id)   | Atualiza last_accessed_at do CPF                    |
| find_oldest_accessed()    | Retorna registro com last_accessed_at mais antigo   |
| remove_by_client(id)      | Remove registro pelo CPF                            |
| used_ports()              | Retorna set de portas em uso                        |

---

## Estrutura do JSON (state.json)

```json
[
  {
    "client_id": "06798162320",
    "container_id": "b4dd386af519a1b2c3d4e5f6...",
    "container_name": "vnc_06798162320",
    "port": 5000,
    "created_at": "2026-02-08T14:30:00.000000",
    "last_accessed_at": "2026-02-08T16:45:00.000000"
  }
]
```

| Campo            | Tipo   | Descricao                                |
|------------------|--------|------------------------------------------|
| client_id        | string | CPF do cliente (identificador unico)     |
| container_id     | string | ID completo do container Docker          |
| container_name   | string | Nome do container (vnc_{CPF})            |
| port             | int    | Porta mapeada no host                    |
| created_at       | string | Data/hora ISO de criacao                 |
| last_accessed_at | string | Data/hora ISO do ultimo acesso           |

---

## Fluxo Principal (/access?id={CPF})

```
Requisicao: GET /access?id=11122233344
        |
        v
  [1] Parametro "id" existe?
        |
     NAO -> Retorna 400
        |
      SIM
        v
  [2] Busca registro no JSON pelo CPF
        |
   ENCONTROU
        |
        v
  [3] Container esta running?
        |
      SIM -> Atualiza last_accessed_at
             Redirect para http://{VNC_HOST}:{porta} (REUSO)
        |
      NAO -> Remove registro do JSON
             Remove container morto
             Segue para [4]
        |
  NAO ENCONTROU
        |
        v
  [4] Aloca porta livre no range
        |
   SEM PORTA LIVRE
        |
        v
  [5] Reciclagem automatica
        - Encontra container com last_accessed_at mais antigo
        - Mata o container
        - Remove registro
        - Reutiliza a porta
        |
   SEM NENHUM REGISTRO -> Retorna 503
        |
   PORTA ALOCADA
        v
  [6] Cria container Docker
        - Nome: vnc_{CPF}
        - Imagem: configurada via VNC_IMAGE
        - Porta: {porta_alocada}:6080
        - Rede: vnc_network
        - ENVs: APPNAME, WIDTH, HEIGHT
        |
   FALHOU -> Retorna 500
        |
    CRIOU
        v
  [7] Aguarda container ficar healthy
        - Verifica Docker healthcheck a cada 1s
        - Timeout de 60s
        |
        v
  [8] Persiste no JSON (com last_accessed_at = agora)
        |
        v
  [9] Redirect para http://{VNC_HOST}:{porta} (NOVO)
```

---

## Reconciliacao no Startup

Quando o orquestrador (re)inicia, `_reconcile_on_startup()` garante consistencia:

```
  [1] Loga toda a configuracao (ENVs, imagem, portas, rede)
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
      - Recupera: cria registro a partir do container ativo
      |
      v
  Salva JSON limpo
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
Host                            Container
 :5000  ---- vnc_cpf1 -------> :6080 (noVNC)
 :5001  ---- vnc_cpf2 -------> :6080 (noVNC)
 :5002  ---- vnc_cpf3 -------> :6080 (noVNC)
 :5003  ---- vnc_cpf4 -------> :6080 (noVNC)

 :8080  ---- orquestrador ----> Flask API
```

---

## Variaveis de Ambiente

### Orquestrador

| Variavel              | Default                        | Descricao                              |
|-----------------------|--------------------------------|----------------------------------------|
| VNC_HOST              | localhost                      | Host usado na URL de redirect          |
| VNC_IMAGE             | ghcr.io/giovannemendonca/...   | Imagem Docker dos containers VNC       |
| VNC_CONTAINER_PORT    | 6080                           | Porta interna do container (noVNC web) |
| PORT_RANGE_MIN        | 5000                           | Inicio do range de portas do host      |
| PORT_RANGE_MAX        | 5003                           | Fim do range de portas do host         |
| ORCHESTRATOR_PORT     | 8080                           | Porta do proprio orquestrador          |
| STATE_FILE            | state.json                     | Caminho do arquivo de estado           |
| DOCKER_NETWORK_NAME   | vnc_network                    | Nome da rede Docker dedicada           |
| DOCKER_NETWORK_SUBNET | 10.10.0.0/24                   | Subnet da rede (evitar conflito)       |

### Repassadas aos Containers VNC

| Variavel do Orquestrador | ENV no Container | Default                                                    |
|--------------------------|------------------|------------------------------------------------------------|
| VNC_APPNAME              | APPNAME          | firefox-kiosk https://mv-proxy.unimedceara.com.br/mvpep/  |
| VNC_WIDTH                | WIDTH            | 410                                                        |
| VNC_HEIGHT               | HEIGHT           | 900                                                        |

---

## Sistema de Logs

Todas as operacoes sao logadas com tags para facilitar filtragem:

| Tag           | Modulo         | O que registra                              |
|---------------|----------------|---------------------------------------------|
| [ACCESS]      | app.py         | Requisicoes de acesso, reuso, criacao        |
| [RECYCLE]     | app.py         | Reciclagem automatica de containers          |
| [RECONCILE]   | app.py         | Reconciliacao no startup                     |
| [STATUS]      | app.py         | Consultas de status                          |
| [REMOVE]      | app.py/cont.py | Remocao de containers individuais            |
| [REMOVE-ALL]  | app.py         | Remocao em massa                             |
| [CREATE]      | containers.py  | Criacao de containers                        |
| [WAIT]        | containers.py  | Espera por healthcheck                       |
| [NETWORK]     | containers.py  | Criacao/reuso de rede Docker                 |
| [PORT]        | containers.py  | Alocacao de portas                           |
| [SCAN]        | containers.py  | Varredura de containers rodando              |
| [HEALTH CHECK]| containers.py  | Verificacao de saude de container            |
| [STATE]       | state.py       | Operacoes de leitura/escrita no JSON         |

Exemplo de saida no terminal:
```
========== STARTUP RECONCILIATION ==========
========== DOCKER CONFIG ==========
  IMAGE           = ghcr.io/giovannemendonca/firefox-flash-kiosk:4bda8f1...
  CONTAINER_PORT  = 6080
  PORT_RANGE      = 5000 - 5003 (4 slots)
  APPNAME         = firefox-kiosk https://mv-proxy.unimedceara.com.br/mvpep/
  WIDTH           = 410
  HEIGHT          = 900
  NETWORK_NAME    = vnc_network
  NETWORK_SUBNET  = 10.10.0.0/24
====================================
[RECONCILE] Found 0 records in JSON
[RECONCILE] Found 0 running vnc_* containers in Docker
[RECONCILE] Done: 0 active records after reconciliation
=============================================
========== ORCHESTRATOR RUNNING on port 8080 ==========

[ACCESS] -------- Request for CPF=06798162320 --------
[ACCESS] No existing record for CPF=06798162320, will create new container
[ACCESS] Ports in use: [] (0/4)
[PORT] Allocated port 5000 (used: 0/4)
[CREATE] Starting creation: name=vnc_06798162320 port=5000
[NETWORK] Network already exists: name=vnc_network id=6679640fff89
[CREATE] Container CREATED: name=vnc_06798162320 id=b4dd386af519 port=5000
[WAIT] Waiting for container b4dd386af519 to be healthy (timeout=60s)...
[WAIT] Container b4dd386af519 is HEALTHY (took 12.3s)
[STATE] ADD record: CPF=06798162320 container=b4dd386af519 port=5000
[ACCESS] SUCCESS: CPF=06798162320 -> container=b4dd386af519 port=5000

[ACCESS] -------- Request for CPF=06798162320 --------
[ACCESS] Container HEALTHY -> REUSING, redirect to http://localhost:5000
[STATE] TOUCH: CPF=06798162320 last_accessed_at=2026-02-08T16:45:00

[RECYCLE] All ports full! Recycling oldest container...
[RECYCLE] Victim: CPF=06798162320 port=5000 last_accessed=2026-02-08T10:15:00
[REMOVE] Killing container: name=vnc_06798162320 id=b4dd386af519
[RECYCLE] Port 5000 freed, reusing for CPF=99999999999

[REMOVE] -------- Remove request for CPF=06798162320 --------
[REMOVE] Killing container: name=vnc_06798162320 id=b4dd386af519
[REMOVE] SUCCESS: CPF=06798162320 container removed

[REMOVE-ALL] -------- Remove all containers --------
[REMOVE-ALL] SUCCESS: 4 containers removed
```

---

## Garantias do Sistema

1. **Um container por CPF**: O JSON nunca permite duplicatas de client_id
2. **Reuso obrigatorio**: Se o container esta running, redireciona sem criar novo
3. **Criacao so quando necessario**: Novo container apenas se nao existe registro ou container morreu
4. **Reciclagem automatica**: Quando portas esgotam, mata o container com acesso mais antigo
5. **Aguarda container pronto**: Espera Docker healthcheck reportar "healthy" antes de redirecionar
6. **Sobrevive a restart**: Reconciliacao sincroniza JSON com Docker real
7. **Sem banco de dados**: Apenas arquivo JSON local
8. **Thread-safe**: Lock em todas as operacoes de leitura/escrita do JSON
9. **Escrita atomica**: Grava em .tmp e faz replace para evitar corrupcao
10. **Rede dedicada**: Subnet configuravel para evitar conflito em producao

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

# Ver containers ativos
curl http://localhost:8080/status

# Remover container de um CPF
curl http://localhost:8080/remove?id=11122233344

# Remover TODOS os containers
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
```
