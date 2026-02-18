from __future__ import annotations

from enum import Enum


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def simple_moving_average(values: list[float], window: int) -> list[float]:
    if window <= 0:
        raise ValueError("window must be positive")
    if len(values) < window:
        return []
    out: list[float] = []
    running = sum(values[:window])
    out.append(running / window)
    for i in range(window, len(values)):
        running += values[i] - values[i - window]
        out.append(running / window)
    return out


def moving_average_crossover_signal(closes: list[float], short_window: int, long_window: int) -> Signal:
    if short_window >= long_window:
        raise ValueError("short_window must be smaller than long_window")
    if len(closes) < long_window + 2:
        return Signal.HOLD

    short = simple_moving_average(closes, short_window)
    long = simple_moving_average(closes, long_window)
    aligned_short = short[-len(long) :]
    if len(aligned_short) < 2 or len(long) < 2:
        return Signal.HOLD

    prev_short, curr_short = aligned_short[-2], aligned_short[-1]
    prev_long, curr_long = long[-2], long[-1]

    if prev_short <= prev_long and curr_short > curr_long:
        return Signal.BUY
    if prev_short >= prev_long and curr_short < curr_long:
        return Signal.SELL
    return Signal.HOLD
