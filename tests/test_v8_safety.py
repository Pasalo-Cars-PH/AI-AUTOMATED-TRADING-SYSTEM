import ast
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "app" / "main.py"

def test_main_compiles():
    ast.parse(SOURCE.read_text(encoding="utf-8"))

def test_default_confluence_gate_is_at_least_three():
    text = SOURCE.read_text(encoding="utf-8")
    assert 'os.getenv("MIN_LAYERS", "5")' in text
    assert "max(3, min(7" in text

def test_market_cache_is_symbol_scoped():
    text = SOURCE.read_text(encoding="utf-8")
    assert 'cache_key = (symbol.upper(), interval, int(outputsize))' in text
    assert "_twelve_data_cache.get(cache_key)" in text

def test_no_synthetic_fallback_language():
    text = SOURCE.read_text(encoding="utf-8")
    assert "synthetic" in text.lower()
    assert "NO_DATA" in text
