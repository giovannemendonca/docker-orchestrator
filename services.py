import logging
import os
from datetime import datetime

import state
import containers
import warm_pool

logger = logging.getLogger(__name__)

VNC_HOST = os.environ.get("VNC_HOST", "localhost")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def reconcile_on_startup() -> None:
    """Sync JSON state with actual Docker containers after a restart."""
    logger.info("========== STARTUP RECONCILIATION ==========")

    containers.log_config()

    logger.info("[RECONCILE] VNC_HOST = %s", VNC_HOST)
    logger.info("[RECONCILE] STATE_FILE = %s", state.STATE_FILE)
    logger.info("[RECONCILE] WARM_POOL_SIZE = %d", warm_pool.WARM_POOL_SIZE)
    logger.info("[RECONCILE] Loading existing records from JSON...")

    records = state.load_records()
    logger.info("[RECONCILE] Found %d records in JSON", len(records))

    running = containers.list_running_orchestrated_containers()
    logger.info("[RECONCILE] Found %d running vnc_* containers in Docker", len(running))

    cleaned: list[dict] = []
    seen_clients: set[str] = set()
    seen_pools: int = 0

    for rec in records:
        cid = rec["client_id"]
        cname = rec.get("container_name", f"vnc_{cid}")

        # Allow multiple __pool__ records
        if cid != "__pool__" and cid in seen_clients:
            logger.warning("[RECONCILE] Duplicate record for CPF %s, removing container %s", cid, rec["container_id"][:12])
            containers.remove_container(rec["container_id"])
            continue

        if containers.is_container_healthy(rec["container_id"]):
            cleaned.append(rec)
            if cid != "__pool__":
                seen_clients.add(cid)
            else:
                seen_pools += 1
            running.pop(cname, None)
            logger.info("[RECONCILE] KEPT record: CPF=%s container=%s port=%d", cid, rec["container_id"][:12], rec["port"])
        else:
            logger.warning("[RECONCILE] STALE record: CPF=%s container=%s is dead, removing...", cid, rec["container_id"][:12])
            containers.remove_container(rec["container_id"])

    # Containers running but not in JSON (manual restart, orphans, etc.)
    for cname, info in running.items():
        if cname.startswith("vnc_pool_"):
            # Pool container orphan
            now = datetime.now().isoformat()
            rec = {
                "client_id": "__pool__",
                "container_id": info["container_id"],
                "container_name": cname,
                "port": info["port"],
                "created_at": now,
                "last_accessed_at": now,
            }
            cleaned.append(rec)
            seen_pools += 1
            logger.info("[RECONCILE] RECOVERED orphan pool container: name=%s port=%d", cname, info["port"])
        elif cname.startswith("vnc_"):
            cpf = cname[4:]
            if cpf and cpf not in seen_clients:
                now = datetime.now().isoformat()
                rec = {
                    "client_id": cpf,
                    "container_id": info["container_id"],
                    "container_name": cname,
                    "port": info["port"],
                    "created_at": now,
                    "last_accessed_at": now,
                }
                cleaned.append(rec)
                seen_clients.add(cpf)
                logger.info("[RECONCILE] RECOVERED orphan container: name=%s CPF=%s port=%d", cname, cpf, info["port"])

    state.save_records(cleaned)
    logger.info("[RECONCILE] Done: %d active records (%d clients + %d pool) after reconciliation",
                len(cleaned), len(seen_clients), seen_pools)
    logger.info("=============================================")


# ---------------------------------------------------------------------------
# Access (main flow)
# ---------------------------------------------------------------------------

def get_or_create_access(client_id: str) -> dict:
    """Main access flow for a client.

    Returns:
        dict with keys:
            "action": "reused" | "pool" | "created"
            "url": str
    Raises:
        ValueError: no ports available and nothing to recycle
        RuntimeError: container creation failed
    """
    logger.info("[ACCESS] -------- Request for CPF=%s --------", client_id)

    # 1. Check existing record
    record = state.find_by_client(client_id)

    if record:
        logger.info("[ACCESS] Found existing record: CPF=%s container=%s port=%d",
                     client_id, record["container_id"][:12], record["port"])

        if containers.is_container_healthy(record["container_id"]):
            state.touch_client(client_id)
            url = f"http://{VNC_HOST}:{record['port']}"
            logger.info("[ACCESS] Container HEALTHY -> REUSING, redirect to %s", url)
            return {"action": "reused", "url": url}
        else:
            logger.warning("[ACCESS] Container DEAD -> cleaning up CPF=%s container=%s",
                           client_id, record["container_id"][:12])
            containers.remove_container(record["container_id"])
            state.remove_by_client(client_id)
            logger.info("[ACCESS] Cleanup done for CPF=%s, will assign or create", client_id)
    else:
        logger.info("[ACCESS] No existing record for CPF=%s", client_id)

    # 2. Try to claim a pool container (instant!)
    pool_rec = state.claim_pool_container(client_id)
    if pool_rec:
        if containers.is_container_healthy(pool_rec["container_id"]):
            url = f"http://{VNC_HOST}:{pool_rec['port']}"
            logger.info("[ACCESS] POOL -> assigned container=%s port=%d to CPF=%s (instant!)",
                         pool_rec["container_id"][:12], pool_rec["port"], client_id)

            # Replenish pool in background
            warm_pool.replenish_pool()

            return {"action": "pool", "url": url}
        else:
            logger.warning("[ACCESS] Pool container DEAD, cleaning up and continuing...")
            containers.remove_container(pool_rec["container_id"])
            state.remove_by_client(client_id)

    logger.info("[ACCESS] No pool containers available, creating new one...")

    # 3. Allocate a free port
    used = state.used_ports()
    logger.info("[ACCESS] Ports in use: %s (%d/%d)",
                sorted(used), len(used), containers.PORT_MAX - containers.PORT_MIN + 1)
    port = containers.allocate_port(used)

    if port is None:
        port = _recycle_oldest_container(client_id)

    if port is None:
        logger.error("[ACCESS] No available ports and no containers to recycle for CPF=%s", client_id)
        raise ValueError("No available ports. All VNC slots are in use.")

    # 4. Create container
    logger.info("[ACCESS] Creating new container for CPF=%s on port %d...", client_id, port)
    try:
        info = containers.create_container(client_id, port)
    except Exception as e:
        logger.exception("[ACCESS] FAILED to create container for CPF=%s: %s", client_id, e)
        raise RuntimeError(f"Failed to create container: {e}") from e

    # 5. Persist
    state.add_record(
        client_id=client_id,
        container_id=info["container_id"],
        container_name=info["container_name"],
        port=info["port"],
    )

    url = f"http://{VNC_HOST}:{port}"
    logger.info("[ACCESS] SUCCESS: CPF=%s -> container=%s port=%d, redirect to %s",
                client_id, info["container_id"][:12], port, url)

    # Replenish pool in background
    warm_pool.replenish_pool()

    return {"action": "created", "url": url}


def _recycle_oldest_container(requesting_client_id: str) -> int | None:
    """Kill the container with the oldest last_accessed_at and return its port."""
    oldest = state.find_oldest_accessed()
    if not oldest:
        return None

    logger.warning("[RECYCLE] All ports full! Recycling oldest container...")
    logger.warning("[RECYCLE] Victim: CPF=%s container=%s port=%d last_accessed=%s",
                   oldest["client_id"], oldest["container_id"][:12], oldest["port"],
                   oldest.get("last_accessed_at", "unknown"))

    containers.remove_container(oldest["container_id"])
    state.remove_by_client(oldest["client_id"])

    port = oldest["port"]
    logger.info("[RECYCLE] Port %d freed from CPF=%s, reusing for CPF=%s",
                port, oldest["client_id"], requesting_client_id)
    return port


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def get_status() -> dict:
    """Return current status of all active containers."""
    records = state.load_records()
    pool_count = sum(1 for r in records if r["client_id"] == "__pool__")
    assigned_count = len(records) - pool_count
    logger.info("[STATUS] Returning %d records (%d assigned + %d pool)",
                len(records), assigned_count, pool_count)
    return {
        "active_containers": assigned_count,
        "pool_containers": pool_count,
        "max_slots": containers.PORT_MAX - containers.PORT_MIN + 1,
        "records": records,
    }


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------

def remove_client(client_id: str) -> dict | None:
    """Remove a specific client's container. Returns dict or None if not found."""
    logger.info("[REMOVE] -------- Remove request for CPF=%s --------", client_id)

    record = state.find_by_client(client_id)

    if not record:
        logger.warning("[REMOVE] No record found for CPF=%s", client_id)
        return None

    logger.info("[REMOVE] Found record: CPF=%s container=%s port=%d",
                client_id, record["container_id"][:12], record["port"])
    containers.remove_container(record["container_id"])
    state.remove_by_client(client_id)
    logger.info("[REMOVE] SUCCESS: CPF=%s container removed and record deleted", client_id)

    # Replenish pool in background (port freed)
    warm_pool.replenish_pool()

    return {
        "status": "removed",
        "client_id": client_id,
        "container_id": record["container_id"],
        "port": record["port"],
    }


def remove_all_clients() -> dict:
    """Remove ALL managed containers (including pool) and clear state."""
    logger.info("[REMOVE-ALL] -------- Remove all containers --------")

    records = state.load_records()

    if not records:
        logger.info("[REMOVE-ALL] No containers to remove")
        return {"status": "empty", "removed": 0}

    removed = 0
    for rec in records:
        logger.info("[REMOVE-ALL] Removing: CPF=%s container=%s port=%d",
                    rec["client_id"], rec["container_id"][:12], rec["port"])
        containers.remove_container(rec["container_id"])
        removed += 1

    state.save_records([])
    logger.info("[REMOVE-ALL] SUCCESS: %d containers removed", removed)

    # Replenish pool in background (all ports freed)
    warm_pool.replenish_pool()

    return {"status": "removed_all", "removed": removed}
