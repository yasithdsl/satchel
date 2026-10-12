"""LaptopState funding record persistence."""

from satchel_laptop.state import LaptopState


def test_record_and_reload(tmp_path):
    state = LaptopState(tmp_path / "state.json")
    state.record_funding("bcrt1qa", "aa" * 32, 0, 50_000)
    state.record_funding("bcrt1qa", "bb" * 32, 1, 60_000)
    state.record_funding("bcrt1qb", "cc" * 32, 2, 70_000)
    reloaded = LaptopState(tmp_path / "state.json")
    assert reloaded.funding_for("bcrt1qa") == [
        {"txid": "aa" * 32, "vout": 0, "amount_sats": 50_000},
        {"txid": "bb" * 32, "vout": 1, "amount_sats": 60_000},
    ]
    assert reloaded.funding_for("bcrt1qb")[0]["txid"] == "cc" * 32
    assert reloaded.funding_for("bcrt1qz") == []
    assert "bcrt1qa" in reloaded.funding
