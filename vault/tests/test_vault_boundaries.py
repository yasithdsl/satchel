"""AST check that vault code cannot sign or touch the network (air gap)."""

import ast
from pathlib import Path

VAULT_SRC = Path(__file__).resolve().parents[2] / "src" / "satchel_vault"
SIGNING_NAMES = {
    "sign_digest",
    "sign_psbt",
    "finalize_psbt",
    "sign",
    "sign_with",
    "ecdsa_sign",
    "schnorr_sign",
}
NETWORK_MODULES = {
    "satchel_core.regtest",
    "httpx",
    "requests",
    "urllib.request",
    "socket",
    "http.client",
}
FORBIDDEN_IMPORTS = NETWORK_MODULES | {"satchel_signer"}


def _allowed_signing(filename: str) -> set[str]:
    return {"sign_digest"} if Path(filename).name == "verification.py" else set()


WIF_FILES = {"verification.py", "release.py"}


def _is_network(name: str) -> bool:
    return any(
        name == m or name.startswith(m + ".") for m in FORBIDDEN_IMPORTS
    )


def check_source(source: str, filename: str) -> list[str]:
    allowed = _allowed_signing(filename)
    forbidden = SIGNING_NAMES - allowed
    issues = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_network(alias.name):
                    issues.append(f"{filename}: imports {alias.name}")
                if alias.name.split(".")[-1] in forbidden:
                    issues.append(f"{filename}: imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for name in [module, *(f"{module}.{a.name}" for a in node.names)]:
                if name and _is_network(name):
                    issues.append(f"{filename}: imports {name}")
                    break
            for alias in node.names:
                if alias.name in forbidden:
                    issues.append(f"{filename}: imports {alias.name} from {module}")
        elif isinstance(node, ast.Name) and node.id in forbidden:
            issues.append(f"{filename}: references {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr == "wif":
                if Path(filename).name not in WIF_FILES:
                    issues.append(f"{filename}: accesses .wif")
            elif node.attr in forbidden:
                issues.append(f"{filename}: accesses .{node.attr}")
    return issues


def test_vault_source_has_no_signing_or_network():
    issues = []
    for path in VAULT_SRC.rglob("*.py"):
        issues.extend(check_source(path.read_text(), path.name))
    assert not issues, "\n".join(issues)


def test_checker_flags_synthetic_source():
    issues = check_source(
        "from satchel_core.signing import sign_digest\nkey.wif\n", "synthetic.py"
    )
    assert any("sign_digest" in i for i in issues)
    assert any("wif" in i for i in issues)
    assert check_source("import httpx", "synthetic.py")
    assert check_source("obj.sign(x)", "verification.py")
    assert check_source("from satchel_core import regtest", "synthetic.py")
    assert not check_source("from satchel_core import keys", "synthetic.py")
    assert check_source("from urllib import request", "synthetic.py")
    assert not check_source("import urllib.parse", "synthetic.py")
    assert check_source("import satchel_signer", "synthetic.py")
    assert check_source(
        "from satchel_signer import signer", "synthetic.py"
    )
    assert not check_source(
        "from satchel_core.signing import sign_digest", "verification.py"
    )
    assert not check_source("key.wif", "verification.py")
    assert not check_source("key.wif", "release.py")
    assert check_source("key.wif", "vault.py")
    assert check_source(
        "from satchel_core.transactions import sign_psbt", "verification.py"
    )
