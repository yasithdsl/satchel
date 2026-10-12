"""The agent process must never touch vault/signer/laptop internals or keys."""

import ast
from pathlib import Path

AGENT_SRC = Path(__file__).resolve().parents[1] / "src" / "satchel_agent"
FORBIDDEN_MODULES = {"satchel_vault", "satchel_signer", "satchel_laptop"}
FORBIDDEN_NAMES = {"MasterKey"}


def offenders(tree: ast.AST, source_name: str) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    found.append(f"{source_name}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in FORBIDDEN_MODULES:
                found.append(f"{source_name}: from {node.module} import ...")
            for alias in node.names:
                if alias.name in FORBIDDEN_NAMES:
                    found.append(
                        f"{source_name}: imports {alias.name}"
                    )
    return found


def test_agent_source_has_no_forbidden_imports():
    bad = []
    for path in AGENT_SRC.rglob("*.py"):
        bad.extend(offenders(ast.parse(path.read_text()), path.name))
    assert bad == []


def test_checker_catches_violations():
    snippet = "import satchel_vault\nfrom satchel_core.keys import MasterKey\n"
    found = offenders(ast.parse(snippet), "snippet.py")
    assert len(found) == 2
    assert offenders(ast.parse("import satchel_core\n"), "ok.py") == []
