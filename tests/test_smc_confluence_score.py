from app.main import score_smc_confluence


def test_smc_score_is_transparent_and_caps_at_100():
    sig = {"layers": ["PDH_SWEEP", "DISP", "FVG", "KZ"]}
    gates = [
        {"name": "H1 alignment", "pass": True},
        {"name": "M15 alignment", "pass": True},
    ]
    score, components = score_smc_confluence(sig, gates)
    assert score == 100
    assert sum(item["points"] for item in components if item["pass"]) == 100


def test_smc_score_drops_when_mtf_gate_is_not_passed():
    sig = {"layers": ["PDL_SWEEP", "DISP", "FVG", "KZ"]}
    gates = [
        {"name": "H1 alignment", "pass": True},
        {"name": "M15 alignment", "pass": False},
    ]
    score, _ = score_smc_confluence(sig, gates)
    assert score == 85
