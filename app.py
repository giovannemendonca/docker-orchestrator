from dotenv import load_dotenv
load_dotenv()

import logging
import os
from datetime import datetime

from flask import Flask, request, redirect, jsonify

import state
import containers
import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

VNC_HOST = os.environ.get("VNC_HOST", "localhost")


def _reconcile_on_startup() -> None:
    """Sync JSON state with actual Docker containers after a restart."""
    logger.info("========== STARTUP RECONCILIATION ==========")

    containers.log_config()

    logger.info("[RECONCILE] VNC_HOST = %s", VNC_HOST)
    logger.info("[RECONCILE] STATE_FILE = %s", state.STATE_FILE)
    logger.info("[RECONCILE] Loading existing records from JSON...")

    records = state.load_records()
    logger.info("[RECONCILE] Found %d records in JSON", len(records))

    running = containers.list_running_orchestrated_containers()
    logger.info("[RECONCILE] Found %d running vnc_* containers in Docker", len(running))

    cleaned: list[dict] = []
    seen_clients: set[str] = set()

    for rec in records:
        cid = rec["client_id"]
        cname = rec.get("container_name", f"vnc_{cid}")

        if cid in seen_clients:
            logger.warning("[RECONCILE] Duplicate record for CPF %s, removing container %s", cid, rec["container_id"][:12])
            containers.remove_container(rec["container_id"])
            continue

        if containers.is_container_healthy(rec["container_id"]):
            cleaned.append(rec)
            seen_clients.add(cid)
            running.pop(cname, None)
            logger.info("[RECONCILE] KEPT record: CPF=%s container=%s port=%d", cid, rec["container_id"][:12], rec["port"])
        else:
            logger.warning("[RECONCILE] STALE record: CPF=%s container=%s is dead, removing...", cid, rec["container_id"][:12])
            containers.remove_container(rec["container_id"])

    # Containers running but not in JSON (manual restart, etc.)
    for cname, info in running.items():
        if cname.startswith("vnc_"):
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
    logger.info("[RECONCILE] Done: %d active records after reconciliation", len(cleaned))
    logger.info("=============================================")


@app.route("/access")
def access():
    client_id = request.args.get("id", "").strip()

    if not client_id:
        logger.warning("[ACCESS] Request with missing 'id' parameter")
        return jsonify({"error": "Missing required parameter: id"}), 400

    logger.info("[ACCESS] -------- Request for CPF=%s --------", client_id)

    # 1. Check existing record
    record = state.find_by_client(client_id)

    if record:
        logger.info("[ACCESS] Found existing record: CPF=%s container=%s port=%d", client_id, record["container_id"][:12], record["port"])

        if containers.is_container_healthy(record["container_id"]):
            state.touch_client(client_id)
            logger.info("[ACCESS] Container HEALTHY -> REUSING, redirect to http://%s:%d", VNC_HOST, record["port"])
            return redirect(f"http://{VNC_HOST}:{record['port']}")
        else:
            logger.warning("[ACCESS] Container DEAD -> cleaning up CPF=%s container=%s", client_id, record["container_id"][:12])
            containers.remove_container(record["container_id"])
            state.remove_by_client(client_id)
            logger.info("[ACCESS] Cleanup done for CPF=%s, will create new container", client_id)
    else:
        logger.info("[ACCESS] No existing record for CPF=%s, will create new container", client_id)

    # 2. Allocate a free port
    used = state.used_ports()
    logger.info("[ACCESS] Ports in use: %s (%d/%d)", sorted(used), len(used), containers.PORT_MAX - containers.PORT_MIN + 1)
    port = containers.allocate_port(used)

    if port is None:
        # Recycle: kill the container with oldest last_accessed_at
        oldest = state.find_oldest_accessed()
        if oldest:
            logger.warning("[RECYCLE] All ports full! Recycling oldest container...")
            logger.warning("[RECYCLE] Victim: CPF=%s container=%s port=%d last_accessed=%s",
                           oldest["client_id"], oldest["container_id"][:12], oldest["port"],
                           oldest.get("last_accessed_at", "unknown"))
            containers.remove_container(oldest["container_id"])
            state.remove_by_client(oldest["client_id"])
            port = oldest["port"]
            logger.info("[RECYCLE] Port %d freed from CPF=%s, reusing for CPF=%s", port, oldest["client_id"], client_id)
        else:
            logger.error("[ACCESS] No available ports and no containers to recycle for CPF=%s", client_id)
            return jsonify({
                "error": "No available ports. All VNC slots are in use.",
                "max_slots": containers.PORT_MAX - containers.PORT_MIN + 1,
            }), 503

    # 3. Create container
    logger.info("[ACCESS] Creating new container for CPF=%s on port %d...", client_id, port)
    try:
        info = containers.create_container(client_id, port)
    except Exception as e:
        logger.exception("[ACCESS] FAILED to create container for CPF=%s: %s", client_id, e)
        return jsonify({"error": f"Failed to create container: {e}"}), 500

    # 4. Persist
    state.add_record(
        client_id=client_id,
        container_id=info["container_id"],
        container_name=info["container_name"],
        port=info["port"],
    )

    logger.info("[ACCESS] SUCCESS: CPF=%s -> container=%s port=%d, redirect to http://%s:%d",
                client_id, info["container_id"][:12], port, VNC_HOST, port)
    return redirect(f"http://{VNC_HOST}:{port}")


@app.route("/status")
def status():
    records = state.load_records()
    logger.info("[STATUS] Returning %d records", len(records))
    return jsonify({
        "active_containers": len(records),
        "max_slots": containers.PORT_MAX - containers.PORT_MIN + 1,
        "records": records,
    })


@app.route("/remove")
def remove():
    client_id = request.args.get("id", "").strip()

    if not client_id:
        logger.warning("[REMOVE] Request with missing 'id' parameter")
        return jsonify({"error": "Missing required parameter: id"}), 400

    logger.info("[REMOVE] -------- Remove request for CPF=%s --------", client_id)

    record = state.find_by_client(client_id)

    if not record:
        logger.warning("[REMOVE] No record found for CPF=%s", client_id)
        return jsonify({"error": f"No container found for id {client_id}"}), 404

    logger.info("[REMOVE] Found record: CPF=%s container=%s port=%d", client_id, record["container_id"][:12], record["port"])
    containers.remove_container(record["container_id"])
    state.remove_by_client(client_id)
    logger.info("[REMOVE] SUCCESS: CPF=%s container removed and record deleted", client_id)

    return jsonify({
        "status": "removed",
        "client_id": client_id,
        "container_id": record["container_id"],
        "port": record["port"],
    })


@app.route("/remove-all")
def remove_all():
    logger.info("[REMOVE-ALL] -------- Remove all containers --------")

    records = state.load_records()

    if not records:
        logger.info("[REMOVE-ALL] No containers to remove")
        return jsonify({"status": "empty", "removed": 0})

    removed = 0
    for rec in records:
        logger.info("[REMOVE-ALL] Removing: CPF=%s container=%s port=%d", rec["client_id"], rec["container_id"][:12], rec["port"])
        containers.remove_container(rec["container_id"])
        removed += 1

    state.save_records([])
    logger.info("[REMOVE-ALL] SUCCESS: %d containers removed", removed)

    return jsonify({"status": "removed_all", "removed": removed})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    _reconcile_on_startup()
    scheduler.start_scheduler()
    port = int(os.environ.get("ORCHESTRATOR_PORT", 8080))
    logger.info("========== ORCHESTRATOR RUNNING on port %d ==========", port)
    app.run(host="0.0.0.0", port=port)
