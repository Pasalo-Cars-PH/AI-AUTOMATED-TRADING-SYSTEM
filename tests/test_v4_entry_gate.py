import ast
from pathlib import Path


MAIN_PATH = Path(__file__).resolve().parents[1] / "app" / "main.py"


def _main_ast():
    return ast.parse(MAIN_PATH.read_text(encoding="utf-8"))


def _function_nodes(tree, name):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]


def test_all_paper_trade_logging_routes_through_shared_risk_gate():
    tree = _main_ast()
    callers = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "log_new_trade":
                    callers.append(fn.name)
    assert callers == ["risk_gate_and_log"]


def test_smc_setup_is_not_reserved_before_risk_gate_passes():
    tree = _main_ast()
    smc = _function_nodes(tree, "smc_scan")[0]
    gate_lines = [
        n.lineno for n in ast.walk(smc)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "risk_gate_and_log"
    ]
    reserve_lines = [
        n.lineno for n in ast.walk(smc)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "add" and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "_smc_used_live"
    ]
    assert len(gate_lines) == 1
    assert len(reserve_lines) == 1
    assert reserve_lines[0] > gate_lines[0]


def test_synthetic_testtrade_cannot_create_ungated_ledger_entries():
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert 'elif txt_base == "/testtrade":\n                send_telegram_msg("🛑 /testtrade disabled' in source
