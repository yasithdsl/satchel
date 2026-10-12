import pytest

from satchel_core.regtest import NodeUnavailable, RegtestNode


@pytest.fixture(autouse=True)
def _event_log(tmp_path, monkeypatch):
    monkeypatch.setenv("SATCHEL_EVENT_LOG", str(tmp_path / "events.jsonl"))


@pytest.fixture(scope="module")
def node():
    node = RegtestNode.from_env()
    try:
        node.ensure_faucet()
    except NodeUnavailable:
        pytest.skip("regtest bitcoind not running (uv run scripts/regtest.py up)")
    return node
