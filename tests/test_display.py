import pandas as pd

from display import show_results


def test_show_results_plain_prints_benchmark_reference(capsys):
    df = pd.DataFrame(
        {
            "Ticker": ["AAA"],
            "low_date": ["2026-03-20"],
            "low_price": [10.0],
            "current_price": [15.0],
            "bounce_pct": [50.0],
            "dollar_vol": [60_000_000.0],
            "sector": ["Technology"],
            "industry": ["Semiconductors"],
        }
    )

    show_results(df, top=1, plain=True, benchmark_bounces={"QLD": 40.0, "TQQQ": 75.0})
    out = capsys.readouterr().out

    assert "Reference bounce" in out
    assert "QLD=40.00%" in out
    assert "TQQQ=75.00%" in out
