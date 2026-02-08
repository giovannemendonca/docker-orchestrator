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
PORT_MAX = int(os.environ.get("PORT_RANGE_MAX", "5020"))

APPNAME = os.environ.get("VNC_APPNAME", "firefox-kiosk https://google.com")
WIDTH = os.environ.get("VNC_WIDTH", "390")
HEIGHT = os.environ.get("VNC_HEIGHT", "900")

client = docker.from_env()


def is_container_healthy(container_id: str) -> bool:
    try:
        container = client.containers.get(container_id)
        return container.status == "running"
    except docker.errors.NotFound:
        return False
    except docker.errors.APIError as e:
        logger.error("Docker API error checking container %s: %s", container_id, e)
        return False


def create_container(client_id: str, port: int) -> dict:
    container_name = f"vnc_{client_id}"

    # Remove leftover container with same name if it exists
    try:
        old = client.containers.get(container_name)
        logger.info("Removing leftover container %s", container_name)
        old.remove(force=True)
    except docker.errors.NotFound:
        pass

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

    logger.info("Created container %s (id=%s) on port %d", container_name, container.id, port)

    return {
        "container_id": container.id,
        "container_name": container_name,
        "port": port,
    }


def remove_container(container_id: str) -> None:
    try:
        container = client.containers.get(container_id)
        container.remove(force=True)
        logger.info("Removed container %s", container_id)
    except docker.errors.NotFound:
        logger.warning("Container %s not found for removal", container_id)
    except docker.errors.APIError as e:
        logger.error("Error removing container %s: %s", container_id, e)


def allocate_port(used: set[int]) -> int | None:
    for port in range(PORT_MIN, PORT_MAX + 1):
        if port not in used:
            return port
    return None


def list_running_orchestrated_containers() -> dict[str, dict]:
    """Return a map of container_name -> {id, port} for all running vnc_* containers."""
    result = {}
    try:
        for container in client.containers.list(filters={"name": "vnc_"}):
            if container.status != "running":
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
    except docker.errors.APIError as e:
        logger.error("Error listing containers: %s", e)
    return result
