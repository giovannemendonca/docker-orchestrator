#!/bin/bash

###############################################################################
# Script de inicialização do Docker Orchestrator (Linux)
# Executa em background (segundo plano)
# Uso: ./start.sh
# Para parar: kill $(cat orchestrator.pid) ou ./start.sh stop
###############################################################################

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Função para parar
stop_orchestrator() {
    if [ ! -f "orchestrator.pid" ]; then
        print_warning "Nenhuma instância rodando"
        exit 0
    fi

    PID=$(cat orchestrator.pid)

    if ! ps -p $PID > /dev/null 2>&1; then
        print_warning "Processo com PID $PID não está rodando"
        rm orchestrator.pid
        exit 0
    fi

    print_info "Parando Docker Orchestrator (PID: $PID)..."
    kill -TERM $PID

    for i in {1..10}; do
        if ! ps -p $PID > /dev/null 2>&1; then
            print_success "Docker Orchestrator parado"
            rm orchestrator.pid
            exit 0
        fi
        sleep 1
    done

    print_warning "Forçando parada..."
    kill -9 $PID
    rm orchestrator.pid
    print_success "Docker Orchestrator parado (forcefully)"
    exit 0
}

# Header
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║    Docker Orchestrator - Inicialização (Background)        ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Verificar comando "stop"
if [ "$1" = "stop" ]; then
    stop_orchestrator
fi

# Verificar se app.py existe
if [ ! -f "app.py" ]; then
    print_error "app.py não encontrado. Execute no diretório raiz do projeto."
    exit 1
fi

print_info "Diretório: $(pwd)"

# Verificar se já está rodando
if [ -f "orchestrator.pid" ]; then
    PID=$(cat orchestrator.pid)
    if ps -p $PID > /dev/null 2>&1; then
        print_warning "Docker Orchestrator já está rodando (PID: $PID)"
        echo "  • Ver logs: tail -f logs/app.log.\$(date +%Y-%m-%d)"
        echo "  • Parar: ./start.sh stop"
        exit 0
    else
        print_info "Limpando PID anterior..."
        rm orchestrator.pid
    fi
fi

# Criar venv se não existir
if [ ! -d "venv" ]; then
    print_info "Criando ambiente virtual..."
    python3.10 -m venv venv
    print_success "Ambiente virtual criado"
fi

# Ativar venv
print_info "Ativando ambiente virtual..."
source venv/bin/activate
print_success "Ambiente virtual ativado"

# Instalar dependências
print_info "Verificando dependências..."
pip install -q -r requirements.txt
print_success "Dependências instaladas"

# Criar diretório de logs
mkdir -p logs

echo ""
print_info "Iniciando Docker Orchestrator em background..."
echo ""

# Iniciar em background
nohup python3.10 app.py > /dev/null 2>&1 &

# Salvar PID
echo $! > orchestrator.pid
PID=$!

sleep 2

# Verificar se iniciou corretamente
if ps -p $PID > /dev/null 2>&1; then
    print_success "Docker Orchestrator iniciado com sucesso"
    echo ""
    echo "╔═══════════════════════════════════════════════════════════════════════════╗"
    echo "║                         INICIADO COM SUCESSO!                             ║"
    echo "╠═══════════════════════════════════════════════════════════════════════════╣"
    echo "║ PID:                    $PID                                              ║"
    echo "║ Status:                 rodando em background                             ║"
    echo "║ Arquivo de Log:         logs/app.log.\$(date +%Y-%m-%d)                   ║"
    echo "║                                                                           ║"
    echo "║ COMANDOS ÚTEIS:                                                           ║"
    echo "║ • Ver logs em tempo real:  tail -f logs/app.log.\$(date +%Y-%m-%d)        ║"
    echo "║ • Últimas 50 linhas:       tail -50 logs/app.log.\$(date +%Y-%m-%d)       ║"
    echo "║ • Procurar erro:           grep ERROR logs/app.log.\$(date +%Y-%m-%d)     ║"
    echo "║ • Parar:                   ./start.sh stop                                ║"
    echo "╚═══════════════════════════════════════════════════════════════════════════╝"
    echo ""
else
    print_error "Erro ao iniciar Docker Orchestrator"
    rm orchestrator.pid
    exit 1
fi
