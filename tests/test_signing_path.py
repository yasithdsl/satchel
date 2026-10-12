"""Signing primitives must only be invoked from satchel_core.signing."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIGNING_PY = REPO / "core" / "src" / "satchel_core" / "signing.py"
SIGNER_PY = REPO / "signer" / "src" / "satchel_signer" / "signer.py"
DEMO_RANDOM_NONCE_PY = (
    REPO / "signer" / "src" / "satchel_signer" / "random_nonce.py"
)
ALLOWED = {SIGNING_PY, DEMO_RANDOM_NONCE_PY}
FORBIDDEN = re.compile(r"\.sign\(|sign_with\(|ecdsa_sign|sign_ecdsa|schnorr_sign")


def _source_files():
    return list(REPO.glob("*/src/**/*.py")) + list(REPO.glob("scripts/*.py"))


def test_no_direct_signing_outside_signing_module():
    offenders = [
        path
        for path in _source_files()
        if path not in ALLOWED and FORBIDDEN.search(path.read_text())
    ]
    assert not offenders


def test_signing_module_calls_sign_exactly_once():
    assert len(re.findall(r"\.sign\(", SIGNING_PY.read_text())) == 1


def test_demo_random_nonce_signer_uses_only_sign_ecdsa():
    src = DEMO_RANDOM_NONCE_PY.read_text()
    assert len(re.findall(r"\.sign_ecdsa\(", src)) == 1
    assert "sign_digest" not in src


def test_random_nonce_module_imported_only_by_signer():
    offenders = [
        path
        for path in _source_files()
        if path != SIGNER_PY
        and any(
            "import" in line and "random_nonce" in line
            for line in path.read_text().splitlines()
        )
    ]
    assert not offenders
