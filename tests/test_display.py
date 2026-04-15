import pandas as pd

from decision_tickets import DecisionTicket
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


def _ticket(rank: int, ticker: str) -> DecisionTicket:
    return DecisionTicket(
        rank=rank,
        ticker=ticker,
        pattern="cup_handle",
        entry=10.0,
        stop=9.0,
        target=12.0,
        risk_per_share=1.0,
        shares=100,
        position_value=1000.0,
        score=0.87,
        summary_reason="clean setup",
        invalidation_rule="invalid if price trades below stop",
        sizing_basis={
            "account_size": 10_000.0,
            "risk_pct": 0.01,
            "risk_dollars": 100.0,
            "max_position_dollars": None,
        },
    )


def test_show_decision_tickets_plain_uses_stable_column_order(capsys):
    from display import show_decision_tickets

    show_decision_tickets([_ticket(1, "AAA")], plain=True)
    out = capsys.readouterr().out.strip().splitlines()

    assert out[0] == (
        "rank ticker pattern entry stop target risk_loss_pct target_gain_pct "
        "risk_per_share shares position_value risk_value score summary_reason"
    )
    assert out[1].startswith("1 AAA cup_handle 10.00 9.00 12.00 10.00 20.00 1.00 100 1000.00 100.00 0.8700 clean setup")


def test_show_decision_tickets_empty_prints_no_valid_setups(capsys):
    from display import show_decision_tickets

    show_decision_tickets([], plain=True)
    out = capsys.readouterr().out.strip()

    assert out == "NO_VALID_SETUPS"


def test_show_decision_tickets_rich_prints_stable_headers(capsys, monkeypatch):
    from display import show_decision_tickets

    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    show_decision_tickets([_ticket(1, "AAA")], plain=False)
    out = capsys.readouterr().out

    assert "rank" in out
    assert "ticker" in out
    assert "pattern" in out
    assert "risk_loss_pct" in out
    assert "target_gain_pct" in out
    assert "risk_per_share" in out
    assert "position_value" in out
    assert "risk_value" in out
    assert "summary_reason" in out
