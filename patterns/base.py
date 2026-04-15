from dataclasses import dataclass, field
from datetime import date
from abc import ABC, abstractmethod
import pandas as pd


@dataclass
class PatternResult:
    pattern: str            # "cup_handle", "double_bottom", "flat_base", "vcp", "channel", "support_resistance"
    ticker: str
    confidence: float       # 0.0–1.0 = conditions_met / total_conditions
    detected_on: date       # date of last bar in input df
    pivots: dict[str, float]       # named price levels {"left_high": 150.0, "cup_low": 120.0, ...}
    pivot_dates: dict[str, date]   # dates of each pivot
    metadata: dict = field(default_factory=dict)  # pattern-specific extras


class PatternDetector(ABC):
    @abstractmethod
    def detect(self, df: pd.DataFrame, ticker: str) -> PatternResult | None:
        """Return PatternResult if pattern found, None otherwise.
        df: DatetimeIndex, columns [Open, High, Low, Close, Volume], pre-sliced to 90 days.
        """
        ...
