from __future__ import annotations

from pathlib import Path

from autostock.backtest import fetch_historical_bars_with_auto_split
from autostock.ib_client import HistoricalBar


class _FakeBroker:
    def __init__(self, direct: list[HistoricalBar], chunk_batches: list[list[HistoricalBar]], fail_direct: bool = False) -> None:
        self.direct = direct
        self.chunk_batches = list(chunk_batches)
        self.fail_direct = fail_direct
        self.calls: list[tuple[str, str, str, str]] = []
        self.chunk_idx = 0

    def get_historical_bars(
        self,
        symbol: str,
        duration: str,
        bar_size: str,
        end_datetime: str = "",
    ) -> list[HistoricalBar]:
        self.calls.append((symbol, duration, bar_size, end_datetime))
        if end_datetime == "":
            if self.fail_direct:
                raise RuntimeError("simulated direct failure")
            return list(self.direct)
        if self.chunk_idx >= len(self.chunk_batches):
            return []
        out = self.chunk_batches[self.chunk_idx]
        self.chunk_idx += 1
        return list(out)


def _bar(date: str, close: float) -> HistoricalBar:
    return HistoricalBar(date=date, open=close, high=close, low=close, close=close, volume=100.0)


def test_auto_split_uses_direct_when_estimate_within_threshold() -> None:
    broker = _FakeBroker(direct=[_bar("2026-01-01 09:30:00", 100.0)], chunk_batches=[])
    out = fetch_historical_bars_with_auto_split(
        broker=broker,
        symbol="MSFT",
        duration="10 D",
        bar_size="1 day",
        max_bars_per_request=10000,
        refresh_cache=True,
    )
    assert len(out) == 1
    assert len(broker.calls) == 1
    assert broker.calls[0][3] == ""


def test_auto_split_uses_chunk_mode_when_estimate_exceeds_threshold() -> None:
    broker = _FakeBroker(
        direct=[],
        chunk_batches=[
            [_bar("2026-01-02 09:35:00", 101.0), _bar("2026-01-02 09:40:00", 102.0)],
            [_bar("2026-01-01 09:35:00", 99.0), _bar("2026-01-01 09:40:00", 100.0)],
        ],
    )
    out = fetch_historical_bars_with_auto_split(
        broker=broker,
        symbol="MSFT",
        duration="2 Y",
        bar_size="5 mins",
        max_bars_per_request=2000,
        refresh_cache=True,
    )
    assert len(out) >= 2
    assert any(call[3] != "" for call in broker.calls)


def test_auto_split_falls_back_to_chunk_on_direct_failure() -> None:
    broker = _FakeBroker(
        direct=[],
        chunk_batches=[[_bar("2026-01-01 09:35:00", 100.0)]],
        fail_direct=True,
    )
    out = fetch_historical_bars_with_auto_split(
        broker=broker,
        symbol="MSFT",
        duration="10 D",
        bar_size="1 day",
        max_bars_per_request=10000,
        refresh_cache=True,
    )
    assert len(out) == 1
    assert len(broker.calls) >= 2
    assert broker.calls[0][3] == ""
    assert any(call[3] != "" for call in broker.calls[1:])


def test_backtest_history_cache_reuses_recent_data() -> None:
    cache_dir = Path("data") / "test_backtest_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    first_broker = _FakeBroker(direct=[_bar("2026-01-01 09:30:00", 100.0)], chunk_batches=[])
    first = fetch_historical_bars_with_auto_split(
        broker=first_broker,
        symbol="MSFT",
        duration="10 D",
        bar_size="1 day",
        max_bars_per_request=10000,
        cache_ttl_hours=24.0,
        refresh_cache=True,
        cache_dir=cache_dir,
    )
    assert len(first) == 1
    assert len(first_broker.calls) == 1

    second_broker = _FakeBroker(direct=[], chunk_batches=[])
    second = fetch_historical_bars_with_auto_split(
        broker=second_broker,
        symbol="MSFT",
        duration="10 D",
        bar_size="1 day",
        max_bars_per_request=10000,
        cache_ttl_hours=24.0,
        refresh_cache=False,
        cache_dir=cache_dir,
    )
    assert len(second) == 1
    assert len(second_broker.calls) == 0
