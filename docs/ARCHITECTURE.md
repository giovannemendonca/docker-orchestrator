# Docker VNC Orchestrator - Arquitetura

## Visao Geral

O sistema e um orquestrador HTTP que cria e gerencia containers Docker VNC sob demanda.
Cada cliente (identificado por CPF) recebe um container exclusivo com uma sessao Firefox em modo kiosk.

```
                                 +---------------------+
                                 |   Container VNC     |
                                 |   vnc_11122233344   |
  Cliente (CPF: 111.222.333-44)  |   porta 5000:6080   |
         |                       +---------------------+
         |
         v                       +---------------------+
  +----------------+             |   Container VNC     |
  |  Orquestrador  |----------->|   vnc_55566677788   |
  |  Flask :8080   |             |   porta 5001:6080   |
  +----------------+             +---------------------+
         |
         |                       +---------------------+
         +------- state.json     |   Container VNC     |
                                 |   vnc_99900011122   |
                                 |   porta 5002:6080   |
                                 +---------------------+
```

## Estrutura de Arquivos

```
docker-orchestrator/
  app.py            -> Aplicacao Flask (rotas HTTP + reconciliacao)
  containers.py     -> Operacoes Docker (criar, verificar, remover containers)
  state.py          -> Persistencia em JSON com thread-safety
  wsgi.py           -> Entry point Gunicorn (chama reconciliacao no startup)
  requirements.txt  -> Dependencias Python
  Dockerfile        -> Imagem do orquestrador
  docker-compose.yml-> Compose para rodar o orquestrador
```

## Modulos

### app.py (Camada HTTP)

Responsabilidades:
- Receber requisicoes HTTP
- Orquestrar o fluxo de criacao/reuso de containers
- Redirecionar o cliente para a porta correta
- Reconciliar estado ao iniciar

Rotas:

| Rota          | Metodo | Descricao                                      |
|---------------|--------|-------------------------------------------------|
| /access?id=X  | GET    | Fluxo principal - cria ou reutiliza container   |
| /status       | GET    | Lista todos os containers ativos e slots livres |
| /health       | GET    | Health check (retorna {"status": "ok"})         |

### containers.py (Camada Docker)

Responsabilidades:
- Comunicar com o Docker daemon via socket
- Criar containers com a imagem VNC configurada
- Verificar se um container esta saudavel (running)
- Remover containers
- Alocar portas livres no range definido
- Listar containers orquestrados que estao rodando

Funcoes:

| Funcao                              | O que faz                                        |
|-------------------------------------|--------------------------------------------------|
| is_container_healthy(container_id)  | Retorna True se o container esta running         |
| create_container(client_id, port)   | Cria container vnc_{cpf} na porta especificada   |
| remove_container(container_id)      | Remove container com force=True                  |
| allocate_port(used)                 | Retorna a primeira porta livre no range          |
| list_running_orchestrated_containers| Lista todos os containers vnc_* que estao ativos |

### state.py (Camada de Persistencia)

Responsabilidades:
- Ler e gravar o arquivo JSON
- Garantir thread-safety com threading.Lock
- Escrita atomica (grava em .tmp e faz replace)
- Criar o arquivo automaticamente se nao existir

Estrutura do JSON (state.json):
```json
[
  {
    "client_id": "11122233344",
    "container_id": "d5fce517e87f...",
    "container_name": "vnc_11122233344",
    "port": 5000,
    "created_at": "2026-02-08T14:30:00.000000"
  }
]
```

## Fluxo Principal (/access?id={CPF})

```
Requisicao: GET /access?id=11122233344
        |
        v
  [1] Parametro "id" existe?
        |
     NAO -> Retorna 400 {"error": "Missing required parameter: id"}
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
      SIM -> Redirect para http://{VNC_HOST}:{porta} (REUSO)
        |
      NAO -> Remove registro do JSON
             Remove container morto
             Segue para [4]
        |
  NAO ENCONTROU
        |
        v
  [4] Aloca porta livre no range (5000-5020)
        |
   SEM PORTA LIVRE -> Retorna 503 {"error": "No available ports..."}
        |
   PORTA ALOCADA
        v
  [5] Cria container Docker
        - Nome: vnc_{CPF}
        - Imagem: configurada via VNC_IMAGE
        - Porta: {porta_alocada}:6080
        - ENVs: APPNAME, WIDTH, HEIGHT
        |
   FALHOU -> Retorna 500 {"error": "Failed to create container: ..."}
        |
    CRIOU
        v
  [6] Persiste no JSON
        |
        v
  [7] Redirect para http://{VNC_HOST}:{porta} (NOVO)
```

## Reconciliacao no Startup

Quando o orquestrador (re)inicia, a funcao `_reconcile_on_startup()` garante
consistencia entre o JSON e os containers reais do Docker:

```
  [1] Le registros do JSON
  [2] Lista containers vnc_* rodando no Docker
      |
      v
  Para cada registro no JSON:
      - Container esta running? -> Mantem no JSON
      - Container morreu?       -> Remove registro + tenta remover container
      - Registro duplicado?     -> Remove container + descarta
      |
      v
  Para cada container vnc_* rodando MAS sem registro no JSON:
      - Recupera: cria registro no JSON a partir do container ativo
      |
      v
  Salva JSON limpo
```

Isso garante que:
- Containers orfaos (registro existe, container morreu) sao limpos
- Containers rodando sem registro (ex: JSON foi apagado) sao recuperados
- Nunca existe duplicata de CPF

## Variaveis de Ambiente

### Orquestrador

| Variavel           | Default                        | Descricao                              |
|--------------------|--------------------------------|----------------------------------------|
| VNC_HOST           | localhost                      | Host usado na URL de redirect          |
| VNC_IMAGE          | ghcr.io/giovannemendonca/...   | Imagem Docker dos containers VNC       |
| VNC_CONTAINER_PORT | 6080                           | Porta interna do container (noVNC web) |
| PORT_RANGE_MIN     | 5000                           | Inicio do range de portas do host      |
| PORT_RANGE_MAX     | 5020                           | Fim do range de portas do host         |
| ORCHESTRATOR_PORT  | 8080                           | Porta do proprio orquestrador          |
| STATE_FILE         | state.json                     | Caminho do arquivo de estado           |

### Repassadas aos Containers VNC

| Variavel do Orquestrador | ENV no Container | Default                          |
|--------------------------|------------------|----------------------------------|
| VNC_APPNAME              | APPNAME          | firefox-kiosk https://google.com |
| VNC_WIDTH                | WIDTH            | 390                              |
| VNC_HEIGHT               | HEIGHT           | 900                              |

## Portas da Imagem VNC

A imagem `firefox-flash-kiosk` expoe duas portas:

| Porta | Protocolo | Funcao                                         |
|-------|-----------|------------------------------------------------|
| 6080  | TCP       | noVNC - acesso VNC pelo navegador via HTTP     |
| 5900  | TCP       | VNC nativo - para clientes VNC desktop         |

O orquestrador mapeia apenas a porta 6080 (acesso web).

## Mapeamento de Portas

```
Host                          Container
 :5000  ---- vnc_cpf1 -----> :6080 (noVNC)
 :5001  ---- vnc_cpf2 -----> :6080 (noVNC)
 :5002  ---- vnc_cpf3 -----> :6080 (noVNC)
  ...
 :5020  ---- vnc_cpf21 ----> :6080 (noVNC)

 :8080  ---- orquestrador --> Flask API
```

Maximo de 21 containers simultaneos (portas 5000 a 5020).

## Garantias do Sistema

1. **Um container por CPF**: O JSON nunca permite duplicatas de client_id
2. **Reuso obrigatorio**: Se o container esta running, redireciona sem criar novo
3. **Criacao so quando necessario**: Novo container apenas se nao existe registro ou container morreu
4. **Sobrevive a restart**: Reconciliacao sincroniza JSON com Docker real
5. **Sem banco de dados**: Apenas arquivo JSON local
6. **Thread-safe**: Lock em todas as operacoes de leitura/escrita do JSON
7. **Escrita atomica**: Grava em .tmp e faz replace para evitar corrupcao

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

# Health check
curl http://localhost:8080/health
```
