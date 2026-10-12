"""Tests for the shared JSONL event stream."""

import json

import pytest

from satchel_core.events import emit


def test_emit_writes_jsonl_in_order(tmp_path):
    log = tmp_path / "events.jsonl"
    records = [
        emit("vault", "key_release", f"released key {i}", {"i": i}, log_path=log)
        for i in range(3)
    ]
    lines = log.read_text().splitlines()
    assert len(lines) == 3
    for i, (line, record) in enumerate(zip(lines, records)):
        parsed = json.loads(line)
        assert parsed["id"] == record["id"]
        assert parsed["component"] == "vault"
        assert parsed["type"] == "key_release"
        assert parsed["message"] == f"released key {i}"
        assert parsed["payload"] == {"i": i}
        assert parsed["ts"].endswith("+00:00")


def test_emit_prints_console_line(tmp_path, capsys):
    record = emit("signer", "signed_tx", "signed 2 inputs", log_path=tmp_path / "e.jsonl")
    err = capsys.readouterr().err.strip()
    assert err == f"{record['ts']} [signer] signed_tx: signed 2 inputs"


def test_payload_optional(tmp_path):
    record = emit("agent", "note", "hello", log_path=tmp_path / "e.jsonl")
    assert record["payload"] is None


def test_env_var_path(tmp_path, monkeypatch):
    log = tmp_path / "custom" / "events.jsonl"
    monkeypatch.setenv("SATCHEL_EVENT_LOG", str(log))
    emit("marketplace", "order", "order placed")
    assert len(log.read_text().splitlines()) == 1


def test_default_path(tmp_path, monkeypatch):
    monkeypatch.delenv("SATCHEL_EVENT_LOG", raising=False)
    monkeypatch.chdir(tmp_path)
    emit("core", "boot", "started")
    assert (tmp_path / ".satchel" / "events.jsonl").exists()


@pytest.mark.parametrize(
    "component,event_type,message",
    [("", "t", "m"), ("c", "", "m"), ("c", "t", ""), (None, "t", "m")],
)
def test_empty_fields_rejected(component, event_type, message, tmp_path):
    with pytest.raises(ValueError):
        emit(component, event_type, message, log_path=tmp_path / "e.jsonl")
