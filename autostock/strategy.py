from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from autostock.config import RSIConfig, StrategyComboConfig, StrategyConfig


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(slots=True)
class StrategyVote:
    name: str
    signal: Signal
    weight: float
    reason: str


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


def rsi_signal(closes: list[float], config: RSIConfig) -> Signal:
    if config.window <= 0:
        raise ValueError("rsi window must be positive")
    if len(closes) < config.window + 1:
        return Signal.HOLD

    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - config.window, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains += change
        else:
            losses += -change

    avg_gain = gains / config.window
    avg_loss = losses / config.window
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    if rsi <= config.oversold:
        return Signal.BUY
    if rsi >= config.overbought:
        return Signal.SELL
    return Signal.HOLD


def _weight(combo: StrategyComboConfig, strategy_name: str) -> float:
    return float(combo.weights.get(strategy_name, 1.0))


def generate_votes(closes: list[float], strategy_cfg: StrategyConfig, combo_cfg: StrategyComboConfig) -> list[StrategyVote]:
    votes: list[StrategyVote] = []
    for name in combo_cfg.enabled_strategies:
        if name == "ma":
            sig = moving_average_crossover_signal(closes, strategy_cfg.short_window, strategy_cfg.long_window)
            votes.append(StrategyVote(name="ma", signal=sig, weight=_weight(combo_cfg, "ma"), reason="ma_crossover"))
        elif name == "rsi":
            sig = rsi_signal(closes, combo_cfg.rsi)
            votes.append(StrategyVote(name="rsi", signal=sig, weight=_weight(combo_cfg, "rsi"), reason="rsi_threshold"))
    return votes


def combine_votes(votes: list[StrategyVote], combo_cfg: StrategyComboConfig) -> tuple[Signal, str]:
    if not votes:
        return Signal.HOLD, "no_enabled_strategy"

    mode = combo_cfg.combination_mode
    threshold = combo_cfg.decision_threshold

    if mode == "priority":
        for vote in votes:
            if vote.signal != Signal.HOLD:
                return vote.signal, f"priority:{vote.name}"
        return Signal.HOLD, "priority:all_hold"

    if mode == "unanimous":
        non_hold = [v.signal for v in votes if v.signal != Signal.HOLD]
        if not non_hold:
            return Signal.HOLD, "unanimous:all_hold"
        if all(s == Signal.BUY for s in non_hold) and len(non_hold) == len(votes):
            return Signal.BUY, "unanimous:buy"
        if all(s == Signal.SELL for s in non_hold) and len(non_hold) == len(votes):
            return Signal.SELL, "unanimous:sell"
        return Signal.HOLD, "unanimous:conflict"

    if mode == "vote":
        buy_count = sum(1 for v in votes if v.signal == Signal.BUY)
        sell_count = sum(1 for v in votes if v.signal == Signal.SELL)
        if buy_count > sell_count:
            return Signal.BUY, f"vote:{buy_count}-{sell_count}"
        if sell_count > buy_count:
            return Signal.SELL, f"vote:{buy_count}-{sell_count}"
        return Signal.HOLD, f"vote:tied:{buy_count}-{sell_count}"

    weighted_score = 0.0
    for vote in votes:
        if vote.signal == Signal.BUY:
            weighted_score += vote.weight
        elif vote.signal == Signal.SELL:
            weighted_score -= vote.weight

    if weighted_score > threshold:
        return Signal.BUY, f"weighted:{weighted_score:.3f}"
    if weighted_score < -threshold:
        return Signal.SELL, f"weighted:{weighted_score:.3f}"
    return Signal.HOLD, f"weighted:{weighted_score:.3f}"


def evaluate_combined_signal(
    closes: list[float], strategy_cfg: StrategyConfig, combo_cfg: StrategyComboConfig
) -> tuple[Signal, str]:
    votes = generate_votes(closes, strategy_cfg, combo_cfg)
    signal, decision_reason = combine_votes(votes, combo_cfg)
    detail = ",".join(f"{v.name}:{v.signal.value}:{v.weight}" for v in votes) or "none"
    return signal, f"{decision_reason}|{detail}"
