# Docker VNC Orchestrator

Um orquestrador HTTP em Python que cria e gerencia containers Docker VNC sob demanda. Cada cliente (identificado por CPF) recebe um container exclusivo com uma sessão Firefox em modo kiosk, acessível pelo navegador via noVNC.

## Funcionalidades

- 🐳 **Gerenciamento automático de containers VNC**: Cria e remove containers Docker conforme necessário
- 👤 **Isolamento por cliente**: Cada CPF recebe seu próprio container exclusivo
- 🌐 **Acesso via navegador**: Interface VNC acessível através do noVNC 
- ⏰ **Limpeza automática**: Remove containers ociosos automaticamente
- 📊 **API REST**: Interface HTTP para criar, listar e gerenciar containers
- 🔧 **Configuração flexível**: Totalmente configurável via variáveis de ambiente

## Pré-requisitos

- Python 3.8+
- Docker instalado e em execução
- Acesso ao socket do Docker (`/var/run/docker.sock` no Linux/Mac ou named pipe no Windows)

## Instalação e Configuração

### 1. Clone o repositório
```bash
git clone <url-do-repositorio>
cd docker-orchestrator
```

### 2. Crie e ative o ambiente virtual (venv)

#### No Windows (PowerShell):
```powershell
# Criar ambiente virtual
python -m venv venv

# Ativar ambiente virtual
.\venv\Scripts\Activate.ps1
```

#### No Linux/Mac:
```bash
# Criar ambiente virtual
python3 -m venv venv

# Ativar ambiente virtual
source venv/bin/activate
```

### 3. Instale as dependências
```bash
pip install -r requirements.txt
```

### 4. Configure as variáveis de ambiente (opcional)

Crie um arquivo `.env` na raiz do projeto para personalizar as configurações:

```env
# Configurações do VNC
VNC_HOST=localhost
VNC_IMAGE=ghcr.io/giovannemendonca/firefox-flash-kiosk:4bda8f16af52b0c2593505a7359e49a252728573
VNC_CONTAINER_PORT=6080
VNC_APPNAME=firefox-kiosk https://google.com
VNC_WIDTH=390
VNC_HEIGHT=900

# Configurações de rede
PORT_RANGE_MIN=5000
PORT_RANGE_MAX=5020
DOCKER_NETWORK_NAME=vnc_network
DOCKER_NETWORK_SUBNET=10.10.0.0/24

# Configurações de limpeza
IDLE_TIMEOUT_HOURS=8
CLEANUP_INTERVAL_MINUTES=30

# Arquivo de estado
STATE_FILE=state.json

# Porta do orquestrador
ORCHESTRATOR_PORT=8080
```

## Como Usar

### Opção 1: Execução direta com Python

1. **Ative o ambiente virtual** (se ainda não estiver ativo):
   ```powershell
   # Windows
   .\venv\Scripts\Activate.ps1
   
   # Linux/Mac
   source venv/bin/activate
   ```

2. **Inicie o servidor**:
   ```bash
   python app.py
   ```

3. **Acesse o orquestrador**: Abra seu navegador em `http://localhost:8080`

### Opção 2: Execução com Docker Compose (Recomendado)

1. **Inicie com Docker Compose**:
   ```bash
   docker-compose up -d
   ```

2. **Acesse o orquestrador**: Abra seu navegador em `http://localhost:8080`

3. **Para parar**:
   ```bash
   docker-compose down
   ```

### Opção 3: Execução com Gunicorn (Produção)

```bash
# Ativar venv
.\venv\Scripts\Activate.ps1  # Windows
# source venv/bin/activate   # Linux/Mac

# Executar com Gunicorn
gunicorn -w 4 -b 0.0.0.0:8080 wsgi:app
```

## API Endpoints

### GET `/access?id=<cpf>`
Cria ou acessa um container VNC existente para um CPF. Retorna um redirecionamento para a URL do VNC.

**Parâmetros:**
- `id`: CPF do cliente (obrigatório)

**Exemplo:**
```bash
GET /access?id=111.222.333-44
```

**Response:**
- Redirecionamento HTTP 302 para `http://localhost:5000` (ou porta disponível)
- Em caso de erro:
```json
{
  "error": "Missing required parameter: id"
}
```

### GET `/status`
Lista todos os containers ativos e informações do sistema.

**Response:**
```json
{
  "active_containers": 2,
  "max_slots": 21,
  "records": [
    {
      "client_id": "111.222.333-44",
      "container_id": "abc123def456",
      "container_name": "vnc_11122233344",
      "port": 5000,
      "created_at": "2026-02-08T10:30:00.123456",
      "last_accessed_at": "2026-02-08T11:00:00.123456"
    }
  ]
}
```

### GET `/remove?id=<cpf>`
Remove um container específico.

**Parâmetros:**
- `id`: CPF do cliente (obrigatório)

**Response:**
```json
{
  "status": "removed",
  "client_id": "111.222.333-44",
  "container_id": "abc123def456",
  "port": 5000
}
```

### GET `/remove-all`
Remove todos os containers ativos.

**Response:**
```json
{
  "status": "removed_all",
  "removed": 5
}
```

### GET `/health`
Verifica se o serviço está funcionando.

**Response:**
```json
{
  "status": "ok"
}
```

## Exemplo de Uso

1. **Acessar/criar container para um cliente**:
   ```bash
   curl "http://localhost:8080/access?id=111.222.333-44"
   ```
   Ou abra no navegador: `http://localhost:8080/access?id=111.222.333-44`

2. **Verificar status do sistema e listar containers**:
   ```bash
   curl http://localhost:8080/status
   ```

3. **Remover container específico**:
   ```bash
   curl "http://localhost:8080/remove?id=111.222.333-44"
   ```

4. **Remover todos os containers**:
   ```bash
   curl http://localhost:8080/remove-all
   ```

5. **Verificar saúde do serviço**:
   ```bash
   curl http://localhost:8080/health
   ```

## Estrutura do Projeto

```
docker-orchestrator/
├── app.py              # Aplicação Flask principal
├── containers.py       # Gerenciamento de containers Docker
├── scheduler.py        # Limpeza automática de containers ociosos
├── state.py           # Gerenciamento do arquivo de estado
├── wsgi.py            # Ponto de entrada para WSGI
├── requirements.txt   # Dependências Python
├── docker-compose.yml # Configuração Docker Compose
├── Dockerfile         # Imagem Docker do orquestrador
├── state.json         # Estado dos containers (criado automaticamente)
└── docs/
    └── ARCHITECTURE.md # Documentação detalhada da arquitetura
```

## Logs e Monitoramento

- Os logs são exibidos no console durante a execução
- O arquivo `state.json` mantém o estado de todos os containers
- Use `docker-compose logs -f` para acompanhar os logs em tempo real

## Resolução de Problemas

### Container não inicia
- Verifique se o Docker está em execução
- Confirme as permissões do socket Docker
- Verifique se as portas não estão em uso

### Erro de rede
- Confirme se a rede `vnc_network` foi criada corretamente
- Verifique conflitos de subnet com outras redes Docker

### VNC não carrega
- Confirme se a porta está acessível
- Verifique os logs do container VNC
- Teste a conectividade de rede

## Desenvolvimento

### Ativando o ambiente de desenvolvimento:
```powershell
# Windows
.\venv\Scripts\Activate.ps1

# Linux/Mac  
source venv/bin/activate
```

### Executando em modo debug:
```bash
export FLASK_DEBUG=1  # Linux/Mac
$env:FLASK_DEBUG=1    # Windows PowerShell
python app.py
```

## Licença

Este projeto é distribuído sob a licença MIT. Veja o arquivo LICENSE para mais detalhes.
