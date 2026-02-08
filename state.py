import json
import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

STATE_FILE = os.environ.get("STATE_FILE", "state.json")

_lock = threading.Lock()


def _read_state() -> list[dict]:
    if not os.path.exists(STATE_FILE):
        logger.debug("[STATE] File %s does not exist, returning empty list", STATE_FILE)
        return []
    with open(STATE_FILE, "r") as f:
        try:
            data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            logger.warning("[STATE] Failed to parse %s, returning empty list", STATE_FILE)
            return []
    if not isinstance(data, list):
        logger.warning("[STATE] %s content is not a list, returning empty list", STATE_FILE)
        return []
    return data


def _write_state(records: list[dict]) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(records, f, indent=2, default=str)
    os.replace(tmp, STATE_FILE)
    logger.debug("[STATE] Wrote %d records to %s", len(records), STATE_FILE)


def load_records() -> list[dict]:
    with _lock:
        return _read_state()


def save_records(records: list[dict]) -> None:
    with _lock:
        _write_state(records)
    logger.info("[STATE] Saved %d records to %s", len(records), STATE_FILE)


def find_by_client(client_id: str) -> dict | None:
    for rec in load_records():
        if rec["client_id"] == client_id:
            logger.debug("[STATE] Found record for CPF=%s port=%d", client_id, rec["port"])
            return rec
    logger.debug("[STATE] No record found for CPF=%s", client_id)
    return None


def add_record(client_id: str, container_id: str, container_name: str, port: int) -> dict:
    now = datetime.now().isoformat()
    record = {
        "client_id": client_id,
        "container_id": container_id,
        "container_name": container_name,
        "port": port,
        "created_at": now,
        "last_accessed_at": now,
    }
    with _lock:
        records = _read_state()
        records = [r for r in records if r["client_id"] != client_id]
        records.append(record)
        _write_state(records)
    logger.info("[STATE] ADD record: CPF=%s container=%s port=%d", client_id, container_id[:12], port)
    return record


def touch_client(client_id: str) -> None:
    """Update last_accessed_at for a client."""
    now = datetime.now().isoformat()
    with _lock:
        records = _read_state()
        for rec in records:
            if rec["client_id"] == client_id:
                rec["last_accessed_at"] = now
                break
        _write_state(records)
    logger.info("[STATE] TOUCH: CPF=%s last_accessed_at=%s", client_id, now)


def find_oldest_accessed() -> dict | None:
    """Return the record with the oldest last_accessed_at."""
    records = load_records()
    if not records:
        logger.info("[STATE] No records to find oldest")
        return None
    oldest = min(records, key=lambda r: r.get("last_accessed_at", r.get("created_at", "")))
    logger.info("[STATE] Oldest accessed: CPF=%s last_accessed=%s port=%d",
                oldest["client_id"], oldest.get("last_accessed_at", "unknown"), oldest["port"])
    return oldest


def remove_by_client(client_id: str) -> None:
    with _lock:
        records = _read_state()
        before = len(records)
        records = [r for r in records if r["client_id"] != client_id]
        _write_state(records)
    logger.info("[STATE] REMOVE record: CPF=%s (records: %d -> %d)", client_id, before, len(records))


def used_ports() -> set[int]:
    ports = {r["port"] for r in load_records()}
    logger.debug("[STATE] Used ports: %s", sorted(ports))
    return ports
