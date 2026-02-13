from dotenv import load_dotenv
load_dotenv()

import logging
import os
from logging.handlers import TimedRotatingFileHandler

from flask import Flask

from routes import bp as routes_bp

# Create logs directory if it doesn't exist
logs_dir = "logs"
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

# Configure logging to both console and file
logger_config = {
    "level": logging.INFO,
    "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
}

logging.basicConfig(**logger_config)

# Add file handler with daily rotation
# Formato dos arquivos: logs/app.log.2026-02-13
from datetime import datetime

current_date = datetime.now().strftime("%Y-%m-%d")
log_filename = os.path.join(logs_dir, f"app.log.{current_date}")

file_handler = TimedRotatingFileHandler(
    filename=log_filename,
    when="midnight",  # Rotaciona à meia-noite
    interval=1,  # A cada dia
    backupCount=7,  # Mantém 7 dias de logs
    utc=False,  # Usa horário local
)
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter(logger_config["format"])
file_handler.setFormatter(formatter)

# Define o formato do sufixo com a data (ex: .2026-02-14)
file_handler.suffix = "%Y-%m-%d"
file_handler.extMatch = None  # Para evitar conflitos

# Adiciona ao logger raiz
root_logger = logging.getLogger()
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.register_blueprint(routes_bp)


if __name__ == "__main__":
    from services import reconcile_on_startup
    import scheduler
    import warm_pool

    reconcile_on_startup()
    scheduler.start_scheduler()
    warm_pool.replenish_pool()

    port = int(os.environ.get("ORCHESTRATOR_PORT", 8080))
    logger.info("========== ORCHESTRATOR RUNNING on port %d ==========", port)

    context = ("/opt/docker-orchestrator/fullchain.crt", "/opt/docker-orchestrator/server.key")

    app.run(
           host="0.0.0.0",
           port=port,
           ssl_context=context
           )
