"""Incremental JSONL tailing."""

import json
import os
from pathlib import Path

import pytest

from satchel_xray.tail import EventTailer, paths_from_env


def event(ts, etype="thing", component="laptop"):
    return {
        "id": ts,
        "ts": ts,
        "component": component,
        "type": etype,
        "message": f"m {ts}",
        "payload": None,
    }


def write(path: Path, events) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in events))


def append_raw(path: Path, text: str) -> None:
    with path.open("a") as handle:
        handle.write(text)


def test_reads_appended_events(tmp_path):
    log = tmp_path / "events.jsonl"
    write(log, [event("2026-10-12T20:00:00.000+00:00")])
    tailer = EventTailer([log])
    first = tailer.poll()
    assert [e["id"] for e in first] == ["2026-10-12T20:00:00.000+00:00"]
    assert tailer.poll() == []
    append_raw(log, json.dumps(event("2026-10-12T20:00:01.000+00:00")) + "\n")
    second = tailer.poll()
    assert len(second) == 1
    assert second[0]["id"] == "2026-10-12T20:00:01.000+00:00"


def test_partial_line_buffered_until_complete(tmp_path):
    log = tmp_path / "events.jsonl"
    line = json.dumps(event("2026-10-12T20:00:00.000+00:00"))
    cut = len(line) // 2
    log.write_text(line[:cut])
    tailer = EventTailer([log])
    assert tailer.poll() == []
    append_raw(log, line[cut:] + "\n")
    events = tailer.poll()
    assert len(events) == 1
    assert events[0]["id"] == "2026-10-12T20:00:00.000+00:00"


def test_truncated_file_restarts_at_zero(tmp_path):
    log = tmp_path / "events.jsonl"
    write(log, [event(f"2026-10-12T20:00:0{i}.000+00:00") for i in range(5)])
    tailer = EventTailer([log])
    assert len(tailer.poll()) == 5
    fresh = event("2026-10-12T20:01:00.000+00:00")
    log.write_text(json.dumps(fresh) + "\n")
    events = tailer.poll()
    assert [e["id"] for e in events] == [fresh["id"]]


def test_replaced_larger_file_restarts_via_inode(tmp_path):
    log = tmp_path / "events.jsonl"
    write(log, [event("2026-10-12T20:00:00.000+00:00")])
    tailer = EventTailer([log])
    tailer.poll()
    os.remove(log)
    write(
        log,
        [
            event(f"2026-10-12T20:05:0{i}.000+00:00")
            for i in range(6)
        ],
    )
    events = tailer.poll()
    assert len(events) == 6
    assert events[0]["id"] == "2026-10-12T20:05:00.000+00:00"


def test_multi_file_merge_by_timestamp(tmp_path):
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    write(
        a,
        [
            event("2026-10-12T20:00:01.000+00:00", "a1"),
            event("2026-10-12T20:00:03.000+00:00", "a3"),
        ],
    )
    write(
        b,
        [
            event("2026-10-12T20:00:02.000+00:00", "b2"),
            event("2026-10-12T20:00:04.000+00:00", "b4"),
        ],
    )
    tailer = EventTailer([a, b])
    types = [e["type"] for e in tailer.poll()]
    assert types == ["a1", "b2", "a3", "b4"]


def test_missing_file_tolerated(tmp_path):
    log = tmp_path / "never-there.jsonl"
    tailer = EventTailer([log])
    assert tailer.poll() == []
    write(log, [event("2026-10-12T20:00:00.000+00:00")])
    assert len(tailer.poll()) == 1


def test_paths_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SATCHEL_XRAY_EVENT_LOGS", f"{tmp_path}/a,{tmp_path}/b")
    monkeypatch.setenv("SATCHEL_EVENT_LOG", str(tmp_path / "ignored"))
    assert paths_from_env() == [tmp_path / "a", tmp_path / "b"]
    monkeypatch.delenv("SATCHEL_XRAY_EVENT_LOGS")
    assert paths_from_env() == [tmp_path / "ignored"]
    monkeypatch.delenv("SATCHEL_EVENT_LOG")
    assert paths_from_env() == [Path(".satchel/events.jsonl")]
