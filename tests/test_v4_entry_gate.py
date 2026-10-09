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


def test_smc_setup_dedupe_reservation_occurs_inside_risk_gated_logger():
    tree = _main_ast()
    smc = _function_nodes(tree, "smc_scan")[0]
    helper = _function_nodes(tree, "risk_gate_and_log")[0]
    calls = [
        n for n in ast.walk(smc)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "risk_gate_and_log"
    ]
    assert len(calls) == 1
    assert any(k.arg == "dedupe_key" for k in calls[0].keywords)
    failed_gate_lines = [
        n.lineno for n in ast.walk(helper)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not)
        and isinstance(n.operand, ast.Call) and isinstance(n.operand.func, ast.Attribute)
        and n.operand.func.attr == "get"
    ]
    reserve_lines = [
        n.lineno for n in ast.walk(helper)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "add" and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "_smc_used_live"
    ]
    assert failed_gate_lines and reserve_lines
    assert reserve_lines[0] > min(failed_gate_lines)


def test_synthetic_testtrade_cannot_create_ungated_ledger_entries():
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert 'elif txt_base == "/testtrade":\n                send_telegram_msg("🛑 /testtrade disabled' in source


def test_reset_cannot_clear_risk_history():
    source = MAIN_PATH.read_text(encoding="utf-8")
    reset_start = source.index('elif txt_base == "/reset":')
    reset_end = source.index('elif txt_base in ["/help", "/start"]:', reset_start)
    reset_block = source[reset_start:reset_end]
    assert "os.remove" not in reset_block
    assert "daily-loss" in reset_block


def test_paper_ledger_prefers_durable_storage_and_never_swallows_write_failure():
    source = MAIN_PATH.read_text(encoding="utf-8")
    load_block = source[source.index("def load_trades():"):source.index("def save_trades(trades):")]
    save_start = source.index("def save_trades(trades):")
    save_end = source.index("def log_new_trade(sig):", save_start)
    save_block = source[save_start:save_end]
    assert "TRADES_FILE_PERSIST" in load_block
    assert "TRADES_FILE_LEGACY" in load_block
    assert "except: pass" not in load_block
    assert "os.replace(temp_path, TRADES_FILE_PERSIST)" in save_block
    assert "raise RuntimeError" in save_block
    assert "os.path.ismount(mount_root)" in source


def test_risk_gate_rejects_ledger_mount_or_io_failures():
    tree = _main_ast()
    helper = _function_nodes(tree, "risk_gate_and_log")[0]
    assert any(
        isinstance(n, ast.ExceptHandler)
        and isinstance(n.type, ast.Tuple)
        and any(isinstance(x, ast.Name) and x.id == "RuntimeError" for x in n.type.elts)
        for n in ast.walk(helper)
    )
