import math

import pandas as pd

from fetcher import get_sp500_tickers, get_tickers
from screener import _compute_summary


def test_regression_sec_payload_without_sic():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [1, "NVIDIA CORP", "NVDA", "Nasdaq"],
                    [2, "Warrant Co", "ABCDW", "NYSE"],
                ],
            }

    import fetcher

    original_get = fetcher.requests.get
    fetcher.requests.get = lambda *_args, **_kwargs: _Resp()
    try:
        assert get_tickers() == ["NVDA"]
    finally:
        fetcher.requests.get = original_get


def test_regression_all_nan_low_window_no_crash():
    raw_df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-03-20", "2026-03-21", "2026-04-10"]),
            "Ticker": ["AAA", "AAA", "AAA"],
            "Low": [math.nan, math.nan, 10.0],
            "Close": [10.5, 10.6, 10.8],
            "Volume": [1_000_000, 1_100_000, 1_200_000],
        }
    )

    summary = _compute_summary(raw_df, low_start="2026-03-15", low_end="2026-04-05")

    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["Ticker"] == "AAA"
    assert row["low_date"] is None
    assert pd.isna(row["low_price"])
    assert pd.isna(row["bounce_pct"])


def test_regression_sp500_fetch_uses_headers_and_parses_html():
    html = """
    <html>
      <body>
        <table>
          <thead><tr><th>Symbol</th></tr></thead>
          <tbody>
            <tr><td>MSFT</td></tr>
            <tr><td>BRK.B</td></tr>
          </tbody>
        </table>
      </body>
    </html>
    """
    captured = {"headers": None}

    class _Resp:
        text = html

        def raise_for_status(self):
            return None

    import fetcher

    def _fake_get(*_args, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return _Resp()

    original_get = fetcher.requests.get
    fetcher.requests.get = _fake_get
    try:
        tickers = get_sp500_tickers()
    finally:
        fetcher.requests.get = original_get

    assert isinstance(captured["headers"], dict)
    assert "User-Agent" in captured["headers"]
    assert tickers == ["MSFT"]
