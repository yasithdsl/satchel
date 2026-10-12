"""Signing primitives must only be invoked from satchel_core.signing."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIGNING_PY = REPO / "core" / "src" / "satchel_core" / "signing.py"
FORBIDDEN = re.compile(r"\.sign\(|sign_with\(|ecdsa_sign|sign_ecdsa|schnorr_sign")


def test_no_direct_signing_outside_signing_module():
    offenders = [
        path
        for path in list(REPO.glob("*/src/**/*.py")) + list(REPO.glob("scripts/*.py"))
        if path != SIGNING_PY and FORBIDDEN.search(path.read_text())
    ]
    assert not offenders


def test_signing_module_calls_sign_exactly_once():
    assert len(re.findall(r"\.sign\(", SIGNING_PY.read_text())) == 1
