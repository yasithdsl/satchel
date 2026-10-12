"""Incremental JSONL event tailing across one or more log files."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG_PATH = Path(".satchel/events.jsonl")


def paths_from_env() -> list[Path]:
    multi = os.environ.get("SATCHEL_XRAY_EVENT_LOGS")
    if multi:
        paths = [Path(p.strip()) for p in multi.split(",") if p.strip()]
        if paths:
            return paths
    single = os.environ.get("SATCHEL_EVENT_LOG")
    if single:
        return [Path(single)]
    return [DEFAULT_LOG_PATH]


def _ts(event: dict) -> datetime:
    raw = event.get("ts")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


class EventTailer:
    """Reads new complete events from JSONL files, surviving truncation."""

    def __init__(self, paths):
        self.paths = [Path(p) for p in paths]
        self._offset: dict[Path, int] = {}
        self._inode: dict[Path, int] = {}
        self._partial: dict[Path, str] = {}

    @classmethod
    def from_env(cls) -> "EventTailer":
        return cls(paths_from_env())

    def poll(self) -> list[dict]:
        """Return newly complete events, merged across files by ts."""
        events = []
        for path in self.paths:
            events.extend(self._poll_file(path))
        events.sort(key=_ts)
        return events

    def _poll_file(self, path: Path) -> list[dict]:
        try:
            stat = path.stat()
        except OSError:
            return []
        offset = self._offset.get(path, 0)
        inode = self._inode.get(path)
        if inode != stat.st_ino or stat.st_size < offset:
            offset = 0
            self._partial[path] = ""
            self._inode[path] = stat.st_ino
        if stat.st_size == offset:
            return []
        try:
            with path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                data = handle.read()
                self._offset[path] = handle.tell()
        except OSError:
            return []
        buf = self._partial.get(path, "") + data
        lines = buf.split("\n")
        self._partial[path] = lines.pop()
        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events
