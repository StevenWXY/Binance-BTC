import json
from pathlib import Path

import numpy as np
import pandas as pd

from btc_regime.v413 import V413Params, generate_v413_signals


ROOT = Path(__file__).resolve().parents[1]


def _market(n: int = 700) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = 100 + 4 * np.sin(np.linspace(0, 18 * np.pi, n))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000.0,
            "quote_volume": 100_000.0,
            "funding_rate": 0.0,
        },
        index=index,
    )


def test_v413_config_round_trip_and_version() -> None:
    payload = json.loads((ROOT / "configs/v4_1_3_params.json").read_text())
    params = V413Params.from_dict(payload)
    assert params.to_dict()["version"] == "V4.1.3"
    assert params.range.target_vol == 0.9
    assert params.range.max_leverage == 3.0
    assert params.direction.max_leverage == 6.5


def test_v413_is_causal_and_has_one_net_target() -> None:
    params = V413Params.from_dict(
        json.loads((ROOT / "configs/v4_1_3_params.json").read_text())
    )
    data = _market()
    original = generate_v413_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[400]:, ["open", "high", "low", "close"]] *= 2
    modified = generate_v413_signals(changed, params)
    pd.testing.assert_series_equal(original["signal"].iloc[:400], modified["signal"].iloc[:400])
    assert original["signal"].abs().max() <= params.max_leverage + 1e-12
    assert {"stop_price", "take_profit_price", "strategy_source", "cycle_id"}.issubset(original)
    assert set(original.loc[original.signal.ne(0), "strategy_source"].unique()) <= {"direction", "V8"}

