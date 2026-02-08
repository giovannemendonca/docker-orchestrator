import logging
import os

from flask import Flask, request, redirect, jsonify

import state
import containers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

VNC_HOST = os.environ.get("VNC_HOST", "localhost")


def _reconcile_on_startup() -> None:
    """Sync JSON state with actual Docker containers after a restart."""
    records = state.load_records()
    running = containers.list_running_orchestrated_containers()

    cleaned: list[dict] = []
    seen_clients: set[str] = set()

    for rec in records:
        cid = rec["client_id"]
        cname = rec.get("container_name", f"vnc_{cid}")

        if cid in seen_clients:
            # Duplicate — remove the container and skip
            containers.remove_container(rec["container_id"])
            logger.info("Removed duplicate record for %s", cid)
            continue

        if containers.is_container_healthy(rec["container_id"]):
            cleaned.append(rec)
            seen_clients.add(cid)
            running.pop(cname, None)
        else:
            # Orphan record — container is dead
            logger.info("Removing stale record for %s (container not running)", cid)
            containers.remove_container(rec["container_id"])

    # Containers running but not in JSON (manual restart, etc.)
    for cname, info in running.items():
        # Extract CPF from name pattern vnc_{cpf}
        if cname.startswith("vnc_"):
            cpf = cname[4:]
            if cpf and cpf not in seen_clients:
                rec = {
                    "client_id": cpf,
                    "container_id": info["container_id"],
                    "container_name": cname,
                    "port": info["port"],
                    "created_at": "recovered",
                }
                cleaned.append(rec)
                seen_clients.add(cpf)
                logger.info("Recovered running container %s for CPF %s", cname, cpf)

    state.save_records(cleaned)
    logger.info("Reconciliation complete: %d active records", len(cleaned))


@app.route("/access")
def access():
    client_id = request.args.get("id", "").strip()
    if not client_id:
        return jsonify({"error": "Missing required parameter: id"}), 400

    # 1. Check existing record
    record = state.find_by_client(client_id)

    if record:
        if containers.is_container_healthy(record["container_id"]):
            logger.info("Reusing container for %s on port %d", client_id, record["port"])
            return redirect(f"http://{VNC_HOST}:{record['port']}")
        else:
            # Container is dead — clean up
            logger.info("Container for %s is unhealthy, removing", client_id)
            containers.remove_container(record["container_id"])
            state.remove_by_client(client_id)

    # 2. Allocate a free port
    used = state.used_ports()
    port = containers.allocate_port(used)
    if port is None:
        logger.error("No available ports for %s", client_id)
        return jsonify({
            "error": "No available ports. All VNC slots are in use.",
            "max_slots": containers.PORT_MAX - containers.PORT_MIN + 1,
        }), 503

    # 3. Create container
    try:
        info = containers.create_container(client_id, port)
    except Exception as e:
        logger.exception("Failed to create container for %s", client_id)
        return jsonify({"error": f"Failed to create container: {e}"}), 500

    # 4. Persist
    state.add_record(
        client_id=client_id,
        container_id=info["container_id"],
        container_name=info["container_name"],
        port=info["port"],
    )

    logger.info("New container for %s on port %d", client_id, port)
    return redirect(f"http://{VNC_HOST}:{port}")


@app.route("/status")
def status():
    records = state.load_records()
    return jsonify({
        "active_containers": len(records),
        "max_slots": containers.PORT_MAX - containers.PORT_MIN + 1,
        "records": records,
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    _reconcile_on_startup()
    port = int(os.environ.get("ORCHESTRATOR_PORT", 8080))
    app.run(host="0.0.0.0", port=port)
