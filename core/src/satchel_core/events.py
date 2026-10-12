"""Shared event stream: every significant action emits one JSONL record."""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
DEFAULT_LOG_PATH = Path(".satchel/events.jsonl")


def emit(
    component: str,
    event_type: str,
    message: str,
    payload: dict | None = None,
    *,
    log_path: str | Path | None = None,
) -> dict:
    """Append an event record to the shared log and echo it to stdout."""
    if not component:
        raise ValueError("component must not be empty")
    if not event_type:
        raise ValueError("event_type must not be empty")
    if not message:
        raise ValueError("message must not be empty")
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    record = {
        "id": uuid.uuid4().hex,
        "ts": ts,
        "component": component,
        "type": event_type,
        "message": message,
        "payload": payload,
    }
    path = Path(
        log_path or os.environ.get("SATCHEL_EVENT_LOG") or DEFAULT_LOG_PATH
    )
    line = json.dumps(record, separators=(",", ":"))
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(line + "\n")
        print(f"{ts} [{component}] {event_type}: {message}")
    return record
