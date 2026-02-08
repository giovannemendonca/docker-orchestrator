import logging
import os
import threading
from datetime import datetime, timedelta

import state
import containers

logger = logging.getLogger(__name__)

# How often the cleanup job runs (in minutes)
CLEANUP_INTERVAL_MINUTES = int(os.environ.get("CLEANUP_INTERVAL_MINUTES", "30"))

# Containers idle for longer than this will be removed
IDLE_TIMEOUT_HOURS = int(os.environ.get("IDLE_TIMEOUT_HOURS", "8"))

_timer: threading.Timer | None = None


def _cleanup_idle_containers() -> None:
    """Remove containers that have been idle for more than IDLE_TIMEOUT_HOURS."""
    logger.info("[CLEANUP] -------- Scheduled cleanup started --------")
    logger.info("[CLEANUP] IDLE_TIMEOUT_HOURS = %d", IDLE_TIMEOUT_HOURS)

    cutoff = datetime.now() - timedelta(hours=IDLE_TIMEOUT_HOURS)
    logger.info("[CLEANUP] Cutoff time: %s (removing containers idle since before this)", cutoff.isoformat())

    records = state.load_records()
    logger.info("[CLEANUP] Total records: %d", len(records))

    removed = 0
    for rec in records:
        last_accessed = rec.get("last_accessed_at", rec.get("created_at", ""))

        if not last_accessed:
            logger.warning("[CLEANUP] Record CPF=%s has no timestamp, skipping", rec["client_id"])
            continue

        try:
            last_dt = datetime.fromisoformat(last_accessed)
        except (ValueError, TypeError):
            logger.warning("[CLEANUP] Record CPF=%s has invalid timestamp '%s', skipping", rec["client_id"], last_accessed)
            continue

        idle_hours = (datetime.now() - last_dt).total_seconds() / 3600

        if last_dt < cutoff:
            logger.info(
                "[CLEANUP] IDLE container: CPF=%s container=%s port=%d last_accessed=%s (idle %.1fh > %dh)",
                rec["client_id"], rec["container_id"][:12], rec["port"],
                last_accessed, idle_hours, IDLE_TIMEOUT_HOURS,
            )
            containers.remove_container(rec["container_id"])
            state.remove_by_client(rec["client_id"])
            removed += 1
        else:
            logger.debug(
                "[CLEANUP] ACTIVE container: CPF=%s last_accessed=%s (idle %.1fh < %dh)",
                rec["client_id"], last_accessed, idle_hours, IDLE_TIMEOUT_HOURS,
            )

    logger.info("[CLEANUP] Done: removed %d idle containers", removed)
    logger.info("[CLEANUP] ----------------------------------------")

    # Schedule next run
    _schedule_next()


def _schedule_next() -> None:
    """Schedule the next cleanup run."""
    global _timer
    interval_seconds = CLEANUP_INTERVAL_MINUTES * 60
    _timer = threading.Timer(interval_seconds, _cleanup_idle_containers)
    _timer.daemon = True  # Won't block app shutdown
    _timer.start()
    logger.info("[CLEANUP] Next cleanup scheduled in %d minutes", CLEANUP_INTERVAL_MINUTES)


def start_scheduler() -> None:
    """Start the background cleanup scheduler."""
    logger.info("========== CLEANUP SCHEDULER ==========")
    logger.info("[CLEANUP] IDLE_TIMEOUT_HOURS      = %d", IDLE_TIMEOUT_HOURS)
    logger.info("[CLEANUP] CLEANUP_INTERVAL_MINUTES = %d", CLEANUP_INTERVAL_MINUTES)
    logger.info("=======================================")
    _schedule_next()


def stop_scheduler() -> None:
    """Stop the background cleanup scheduler."""
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None
        logger.info("[CLEANUP] Scheduler stopped")
