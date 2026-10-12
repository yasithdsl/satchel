"""AST check that signer code cannot network, store, or echo keys."""

import ast
from pathlib import Path

SIGNER_SRC = Path(__file__).resolve().parents[2] / "src" / "satchel_signer"
NETWORK_MODULES = {
    "satchel_core.regtest",
    "httpx",
    "requests",
    "urllib.request",
    "socket",
    "http.client",
}
STORAGE_MODULES = {"logging", "pickle", "shelve", "sqlite3", "tempfile"}
CACHE_NAMES = {"cache", "lru_cache"}
FORBIDDEN_CALLS = {"open", "print"}
FORBIDDEN_METHOD_CALLS = {"write_text", "write_bytes"}


def _matches(name: str, modules: set[str]) -> bool:
    return any(name == m or name.startswith(m + ".") for m in modules)


def check_source(source: str, filename: str) -> list[str]:
    issues = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _matches(alias.name, NETWORK_MODULES) or _matches(
                    alias.name, STORAGE_MODULES
                ):
                    issues.append(f"{filename}: imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for name in [
                module,
                *(f"{module}.{a.name}" for a in node.names),
            ]:
                if name and (
                    _matches(name, NETWORK_MODULES)
                    or _matches(name, STORAGE_MODULES)
                ):
                    issues.append(f"{filename}: imports {name}")
                    break
            if module == "functools":
                for alias in node.names:
                    if alias.name in CACHE_NAMES:
                        issues.append(
                            f"{filename}: imports {alias.name} from functools"
                        )
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                issues.append(f"{filename}: calls {func.id}()")
            elif isinstance(func, ast.Attribute) and (
                func.attr in FORBIDDEN_METHOD_CALLS
                or func.attr in CACHE_NAMES
            ):
                issues.append(f"{filename}: calls .{func.attr}()")
        elif isinstance(node, ast.Attribute) and node.attr in CACHE_NAMES:
            issues.append(f"{filename}: accesses .{node.attr}")
    return issues


def test_signer_source_has_no_network_or_storage():
    issues = []
    for path in SIGNER_SRC.rglob("*.py"):
        issues.extend(check_source(path.read_text(), path.name))
    assert not issues, "\n".join(issues)


def test_checker_flags_synthetic_source():
    assert check_source("import socket", "synthetic.py")
    assert check_source("from satchel_core import regtest", "synthetic.py")
    assert check_source("from urllib import request", "synthetic.py")
    assert check_source("import logging", "synthetic.py")
    assert check_source("import pickle", "synthetic.py")
    assert check_source("import tempfile", "synthetic.py")
    assert check_source("import sqlite3", "synthetic.py")
    assert check_source("open('x')", "synthetic.py")
    assert check_source("print('x')", "synthetic.py")
    assert check_source("path.write_text('x')", "synthetic.py")
    assert check_source("path.write_bytes(b'x')", "synthetic.py")
    assert check_source("from functools import lru_cache", "synthetic.py")
    assert check_source("import functools\nfunctools.cache", "synthetic.py")
    assert not check_source("from satchel_core import keys", "synthetic.py")
    assert not check_source("import urllib.parse", "synthetic.py")
    assert not check_source(
        "from satchel_core.transactions import sign_psbt", "synthetic.py"
    )
    assert not check_source("path.read_text()", "synthetic.py")
