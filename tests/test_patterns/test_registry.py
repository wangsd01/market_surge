from patterns import detect_all
from tests.test_patterns.test_high2 import _df, _prepend_filler, _valid_h2_rows


def test_detect_all_includes_high2_and_excludes_disabled_detectors():
    """Active detector registry should not include disabled detectors."""
    df = _df(_prepend_filler(_valid_h2_rows()))

    results = detect_all(df, "TEST")

    pattern_names = {result.pattern for result in results}
    assert "high2" in pattern_names
    assert "channel" not in pattern_names
    assert "support_resistance" not in pattern_names
