from dotenv import load_dotenv
load_dotenv()

import logging
import os

from flask import Flask

from routes import bp as routes_bp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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
    app.run(host="0.0.0.0", port=port)
