"""AST check that the laptop never touches agent internals or key material."""

import ast
from pathlib import Path

LAPTOP_SRC = Path(__file__).resolve().parents[1] / "src" / "satchel_laptop"
FORBIDDEN_MODULES = {"satchel_agent", "satchel_core.signing"}
FORBIDDEN_NAMES = {"PrivateKey", "private_key_from_wif", "MasterKey"}
WIF_LITERAL_FILES = {"flows.py"}


def _is_forbidden_module(name: str) -> bool:
    return any(
        name == m or name.startswith(m + ".") for m in FORBIDDEN_MODULES
    )


def check_source(source: str, filename: str) -> list[str]:
    issues = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    issues.append(f"{filename}: imports {alias.name}")
                if alias.name.split(".")[-1] in FORBIDDEN_NAMES:
                    issues.append(f"{filename}: imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_forbidden_module(module):
                issues.append(f"{filename}: from {module} import ...")
            for alias in node.names:
                if alias.name in FORBIDDEN_NAMES:
                    issues.append(
                        f"{filename}: imports {alias.name} from {module}"
                    )
        elif isinstance(node, ast.Attribute) and node.attr == "wif":
            issues.append(f"{filename}: accesses .wif")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            issues.append(f"{filename}: uses .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            issues.append(f"{filename}: references {node.id}")
        elif (
            isinstance(node, ast.Constant)
            and node.value == "wif"
            and Path(filename).name not in WIF_LITERAL_FILES
        ):
            issues.append(f'{filename}: uses the string "wif"')
    return issues


def test_laptop_source_has_no_agent_or_key_material():
    issues = []
    for path in LAPTOP_SRC.rglob("*.py"):
        issues.extend(check_source(path.read_text(), path.name))
    assert not issues, "\n".join(issues)


def test_checker_flags_synthetic_source():
    assert check_source("import satchel_agent", "x.py")
    assert check_source(
        "from satchel_agent.wallet import EnvelopeWallet", "x.py"
    )
    assert check_source("from satchel_core.signing import sign_digest", "x.py")
    assert check_source("import satchel_core.signing", "x.py")
    assert check_source("from embit.ec import PrivateKey", "x.py")
    assert check_source("ec.PrivateKey.from_wif(x)", "x.py")
    assert check_source("from satchel_core.keys import MasterKey", "x.py")
    assert check_source("keys.MasterKey.from_seed(seed)", "x.py")
    assert not check_source("from embit import ec", "x.py")
    assert not check_source("from embit.ec import PublicKey", "x.py")
    assert check_source(
        "from satchel_core.keys import private_key_from_wif", "x.py"
    )
    assert check_source("key.wif", "x.py")
    assert check_source('body["wif"]', "x.py")
    assert check_source('body["wif"]', "grant.py")
    assert not check_source('body["wif"]', "flows.py")
    assert not check_source("from embit import script", "x.py")
    assert not check_source(
        "from embit.transaction import Transaction", "x.py"
    )
    assert not check_source("from embit.hashes import hash160", "x.py")
