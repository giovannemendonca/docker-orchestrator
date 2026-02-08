import docker
import logging
import os

logger = logging.getLogger(__name__)

IMAGE = os.environ.get(
    "VNC_IMAGE",
    "ghcr.io/giovannemendonca/firefox-flash-kiosk:4bda8f16af52b0c2593505a7359e49a252728573",
)
CONTAINER_PORT = os.environ.get("VNC_CONTAINER_PORT", "6080")
PORT_MIN = int(os.environ.get("PORT_RANGE_MIN", "5000"))
PORT_MAX = int(os.environ.get("PORT_RANGE_MAX", "5003"))

APPNAME = os.environ.get("VNC_APPNAME", "firefox-kiosk https://google.com")
WIDTH = os.environ.get("VNC_WIDTH", "390")
HEIGHT = os.environ.get("VNC_HEIGHT", "900")

client = docker.from_env()


def log_config():
    """Log all configuration on startup."""
    logger.info("========== DOCKER CONFIG ==========")
    logger.info("  IMAGE           = %s", IMAGE)
    logger.info("  CONTAINER_PORT  = %s", CONTAINER_PORT)
    logger.info("  PORT_RANGE      = %s - %s (%d slots)", PORT_MIN, PORT_MAX, PORT_MAX - PORT_MIN + 1)
    logger.info("  APPNAME         = %s", APPNAME)
    logger.info("  WIDTH           = %s", WIDTH)
    logger.info("  HEIGHT          = %s", HEIGHT)
    logger.info("====================================")


def is_container_healthy(container_id: str) -> bool:
    try:
        container = client.containers.get(container_id)
        healthy = container.status == "running"
        logger.debug("[HEALTH CHECK] container=%s status=%s healthy=%s", container_id[:12], container.status, healthy)
        return healthy
    except docker.errors.NotFound:
        logger.warning("[HEALTH CHECK] container=%s NOT FOUND", container_id[:12])
        return False
    except docker.errors.APIError as e:
        logger.error("[HEALTH CHECK] container=%s API ERROR: %s", container_id[:12], e)
        return False


def create_container(client_id: str, port: int) -> dict:
    container_name = f"vnc_{client_id}"

    logger.info("[CREATE] Starting creation: name=%s port=%d image=%s", container_name, port, IMAGE[:50])

    # Remove leftover container with same name if it exists
    try:
        old = client.containers.get(container_name)
        logger.warning("[CREATE] Found leftover container %s (id=%s), removing...", container_name, old.id[:12])
        old.remove(force=True)
        logger.info("[CREATE] Leftover container %s removed", container_name)
    except docker.errors.NotFound:
        logger.debug("[CREATE] No leftover container found for %s", container_name)

    logger.info("[CREATE] Running docker create: %s -> %s:%d env=[APPNAME=%s, WIDTH=%s, HEIGHT=%s]",
                container_name, CONTAINER_PORT, port, APPNAME, WIDTH, HEIGHT)

    container = client.containers.run(
        IMAGE,
        name=container_name,
        ports={f"{CONTAINER_PORT}/tcp": ("0.0.0.0", port)},
        environment={
            "APPNAME": APPNAME,
            "WIDTH": WIDTH,
            "HEIGHT": HEIGHT,
        },
        detach=True,
        restart_policy={"Name": "unless-stopped"},
    )

    logger.info("[CREATE] Container CREATED: name=%s id=%s port=%d", container_name, container.id[:12], port)

    return {
        "container_id": container.id,
        "container_name": container_name,
        "port": port,
    }


def remove_container(container_id: str) -> None:
    try:
        container = client.containers.get(container_id)
        container_name = container.name
        logger.info("[REMOVE] Killing container: name=%s id=%s status=%s", container_name, container_id[:12], container.status)
        container.remove(force=True)
        logger.info("[REMOVE] Container REMOVED: name=%s id=%s", container_name, container_id[:12])
    except docker.errors.NotFound:
        logger.warning("[REMOVE] Container %s not found (already removed?)", container_id[:12])
    except docker.errors.APIError as e:
        logger.error("[REMOVE] Failed to remove container %s: %s", container_id[:12], e)


def allocate_port(used: set[int]) -> int | None:
    logger.debug("[PORT] Used ports: %s", sorted(used))
    for port in range(PORT_MIN, PORT_MAX + 1):
        if port not in used:
            logger.info("[PORT] Allocated port %d (used: %d/%d)", port, len(used), PORT_MAX - PORT_MIN + 1)
            return port
    logger.warning("[PORT] No free ports available! All %d slots in use", PORT_MAX - PORT_MIN + 1)
    return None


def list_running_orchestrated_containers() -> dict[str, dict]:
    """Return a map of container_name -> {id, port} for all running vnc_* containers."""
    result = {}
    try:
        for container in client.containers.list(filters={"name": "vnc_"}):
            if container.status != "running":
                logger.debug("[SCAN] Skipping container %s (status=%s)", container.name, container.status)
                continue
            name = container.name
            ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            host_port = None
            for binding in (ports.get(f"{CONTAINER_PORT}/tcp") or []):
                host_port = int(binding["HostPort"])
                break
            if host_port is not None:
                result[name] = {
                    "container_id": container.id,
                    "port": host_port,
                }
                logger.debug("[SCAN] Found running container: name=%s id=%s port=%d", name, container.id[:12], host_port)
    except docker.errors.APIError as e:
        logger.error("[SCAN] Error listing containers: %s", e)

    logger.info("[SCAN] Found %d running vnc_* containers", len(result))
    return result
