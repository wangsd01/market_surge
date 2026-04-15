from patterns import detect_all


def test_detect_all_excludes_disabled_detectors(make_ohlcv):
    """Active detector registry should not include disabled detectors."""
    df = make_ohlcv([100 + i * 0.5 for i in range(90)])

    results = detect_all(df, "TEST")

    pattern_names = {result.pattern for result in results}
    assert "channel" not in pattern_names
    assert "support_resistance" not in pattern_names
