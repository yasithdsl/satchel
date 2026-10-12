"""Per-flow hop recorder: every payload hop lands in an auditable file."""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from satchel_core.events import emit
from satchel_core.payloads import MessageType, Payload, to_http


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _redact(value):
    if isinstance(value, dict):
        return {
            k: "<redacted>" if k == "wif" else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class FlowRecorder:
    """Records hops of one grant/spend/setup flow to a JSON file + events."""

    def __init__(self, kind: str, directory: str | Path | None = None):
        if kind not in ("grant", "spend", "setup"):
            raise ValueError(f"flow kind must be grant|spend|setup, got {kind!r}")
        base = (
            Path(directory)
            if directory is not None
            else Path(os.environ.get("SATCHEL_LAPTOP_DIR", ".satchel/laptop"))
        )
        self.directory = base / "flows"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.flow_id = uuid.uuid4().hex
        self.path = self.directory / f"{self.flow_id}.json"
        self.doc = {
            "flow_id": self.flow_id,
            "kind": kind,
            "started_at": _now(),
            "status": "running",
            "hops": [],
            "result": None,
        }
        self._save()

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(
            dir=self.directory, prefix=f".{self.path.name}-"
        )
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(self.doc, handle, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            os.unlink(tmp)
            raise

    def hop(
        self,
        name: str,
        source: str,
        target: str,
        payload: Payload | None,
        detail: dict | None = None,
    ) -> None:
        redacted = False
        stored = None
        if payload is not None:
            body = payload.body
            if payload.type == MessageType.KEY_RELEASE:
                body = _redact(body)
                redacted = True
            stored = to_http(Payload(payload.type, body))
        hop = {
            "index": len(self.doc["hops"]),
            "name": name,
            "from": source,
            "to": target,
            "ts": _now(),
            "payload": stored,
            "redacted": redacted,
            "detail": detail,
        }
        self.doc["hops"].append(hop)
        self._save()
        emit(
            "laptop",
            name,
            f"flow {self.flow_id[:8]} hop {hop['index']}: "
            f"{source} -> {target} ({name})",
            {
                "flow_id": self.flow_id,
                "flow": self.doc["kind"],
                "hop": hop["index"],
                "from": source,
                "to": target,
                "payload_type": payload.type.value if payload else None,
            },
        )

    def finish(self, status: str, result: dict) -> None:
        self.doc["status"] = status
        self.doc["result"] = result
        self._save()
        kind = self.doc["kind"]
        emit(
            "laptop",
            f"{kind}_{'completed' if status == 'completed' else 'failed'}",
            f"flow {self.flow_id[:8]} {status}",
            {"flow_id": self.flow_id, "status": status},
        )
