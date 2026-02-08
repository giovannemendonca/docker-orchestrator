import logging
import os
import threading

import state
import containers

logger = logging.getLogger(__name__)

WARM_POOL_SIZE = int(os.environ.get("WARM_POOL_SIZE", "1"))


def replenish_pool() -> None:
    """Ensure the warm pool has WARM_POOL_SIZE containers ready.

    Runs the actual filling in a background thread so it never blocks
    the caller (HTTP request, startup, cleanup, etc.).
    """
    if WARM_POOL_SIZE <= 0:
        logger.debug("[POOL] WARM_POOL_SIZE=0, pool disabled")
        return

    t = threading.Thread(target=_fill_pool, daemon=True)
    t.start()


def _fill_pool() -> None:
    """Create pool containers until we reach WARM_POOL_SIZE (if ports available)."""
    current_pool = state.find_unassigned()
    current_count = len(current_pool)
    needed = WARM_POOL_SIZE - current_count

    if needed <= 0:
        logger.info("[POOL] Pool already full: %d/%d containers ready", current_count, WARM_POOL_SIZE)
        return

    logger.info("[POOL] Replenishing pool: current=%d target=%d need=%d",
                current_count, WARM_POOL_SIZE, needed)

    created = 0
    for _ in range(needed):
        used = state.used_ports()
        port = containers.allocate_port(used)

        if port is None:
            logger.warning("[POOL] No free ports available, stopping pool replenishment (created %d/%d)",
                           created, needed)
            break

        try:
            logger.info("[POOL] Creating pool container on port %d...", port)
            info = containers.create_pool_container(port)

            state.add_record(
                client_id="__pool__",
                container_id=info["container_id"],
                container_name=info["container_name"],
                port=info["port"],
            )

            created += 1
            logger.info("[POOL] Pool container READY: name=%s port=%d (%d/%d)",
                        info["container_name"], port, current_count + created, WARM_POOL_SIZE)

        except Exception as e:
            logger.exception("[POOL] FAILED to create pool container on port %d: %s", port, e)

    logger.info("[POOL] Replenishment done: created %d containers (pool: %d/%d)",
                created, current_count + created, WARM_POOL_SIZE)
