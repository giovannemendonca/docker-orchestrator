import json
import os
import threading
from datetime import datetime

STATE_FILE = os.environ.get("STATE_FILE", "state.json")

_lock = threading.Lock()


def _read_state() -> list[dict]:
    if not os.path.exists(STATE_FILE):
        return []
    with open(STATE_FILE, "r") as f:
        try:
            data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            return []
    if not isinstance(data, list):
        return []
    return data


def _write_state(records: list[dict]) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(records, f, indent=2, default=str)
    os.replace(tmp, STATE_FILE)


def load_records() -> list[dict]:
    with _lock:
        return _read_state()


def save_records(records: list[dict]) -> None:
    with _lock:
        _write_state(records)


def find_by_client(client_id: str) -> dict | None:
    for rec in load_records():
        if rec["client_id"] == client_id:
            return rec
    return None


def add_record(client_id: str, container_id: str, container_name: str, port: int) -> dict:
    record = {
        "client_id": client_id,
        "container_id": container_id,
        "container_name": container_name,
        "port": port,
        "created_at": datetime.now().isoformat(),
    }
    with _lock:
        records = _read_state()
        # Guarantee: never duplicate a client_id
        records = [r for r in records if r["client_id"] != client_id]
        records.append(record)
        _write_state(records)
    return record


def remove_by_client(client_id: str) -> None:
    with _lock:
        records = _read_state()
        records = [r for r in records if r["client_id"] != client_id]
        _write_state(records)


def used_ports() -> set[int]:
    return {r["port"] for r in load_records()}
