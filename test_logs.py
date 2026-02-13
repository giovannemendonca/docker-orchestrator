#!/usr/bin/env python3
"""
Script de teste para verificar se o sistema de logs está funcionando corretamente.
Execute este script para validar a configuração de logs.
"""

import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler

# Simula o mesmo setup do app.py
logs_dir = "logs"
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

logger_config = {
    "level": logging.INFO,
    "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
}

logging.basicConfig(**logger_config)

file_handler = TimedRotatingFileHandler(
    filename=os.path.join(logs_dir, "test.log"),
    when="midnight",
    interval=1,
    backupCount=30,
    utc=False,
)
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter(logger_config["format"])
file_handler.setFormatter(formatter)
file_handler.suffix = "%Y-%m-%d"

root_logger = logging.getLogger()
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

# Testes
if __name__ == "__main__":
    print("\n" + "="*60)
    print("🧪 TESTE DO SISTEMA DE LOGS")
    print("="*60 + "\n")
    
    # Info
    logger.info("✅ Mensagem de INFO - Sistema iniciado")
    print("[✅] INFO escrito")
    
    time.sleep(0.5)
    
    # Warning
    logger.warning("⚠️  Mensagem de WARNING - Verificar configuração")
    print("[⚠️ ] WARNING escrito")
    
    time.sleep(0.5)
    
    # Error
    logger.error("❌ Mensagem de ERROR - Verificar sistema")
    print("[❌] ERROR escrito")
    
    time.sleep(0.5)
    
    # Debug (não será exibido pois nível é INFO)
    logger.debug("🔍 Mensagem de DEBUG - Não será salva (nível INFO)")
    print("[🔍] DEBUG tentado (nível: INFO - não será salvo)\n")
    
    print("="*60)
    print("📁 ARQUIVOS CRIADOS")
    print("="*60 + "\n")
    
    # Verifica arquivos criados
    if os.path.exists(logs_dir):
        files = os.listdir(logs_dir)
        if files:
            for f in sorted(files):
                file_path = os.path.join(logs_dir, f)
                size = os.path.getsize(file_path)
                print(f"  📄 {f} ({size} bytes)")
        else:
            print("  ⚠️  Nenhum arquivo encontrado")
    else:
        print("  ❌ Diretório 'logs' não existe")
    
    print("\n" + "="*60)
    print("✨ VERIFICAÇÃO CONCLUÍDA")
    print("="*60)
    print("\n📝 Próximos passos:")
    print("  1. Verificar conteúdo: cat logs/test.log.*")
    print("  2. Buscar patterns: grep INFO logs/test.log.*")
    print("  3. Contar linhas: wc -l logs/test.log.*")
    print("\n")
