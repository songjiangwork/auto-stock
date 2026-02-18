from __future__ import annotations

from dataclasses import dataclass

from autostock.config import RiskConfig


@dataclass(slots=True)
class RiskDecision:
    allow_new_position: bool
    reason: str = ""


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config

    def max_shares_for_symbol(self, equity: float, price: float) -> int:
        if equity <= 0 or price <= 0:
            return 0
        budget = equity * self.config.max_position_pct
        return int(budget // price)

    def stop_loss_triggered(self, avg_cost: float, last_price: float) -> bool:
        if avg_cost <= 0:
            return False
        stop_price = avg_cost * (1 - self.config.stop_loss_pct)
        return last_price <= stop_price

    def evaluate_entry_guards(
        self,
        current_equity: float,
        day_start_equity: float,
        symbol_realized_pnl: float,
        open_positions: int = 0,
        consecutive_losses: int = 0,
    ) -> RiskDecision:
        if day_start_equity > 0:
            drawdown = (day_start_equity - current_equity) / day_start_equity
            if drawdown >= self.config.account_daily_drawdown_pct:
                return RiskDecision(
                    allow_new_position=False,
                    reason=f"account drawdown limit reached ({drawdown:.2%})",
                )

        symbol_loss_limit = current_equity * self.config.symbol_daily_loss_pct
        if symbol_realized_pnl <= -symbol_loss_limit:
            return RiskDecision(
                allow_new_position=False,
                reason=f"symbol daily loss limit reached ({symbol_realized_pnl:.2f})",
            )

        if open_positions >= self.config.max_open_positions:
            return RiskDecision(
                allow_new_position=False,
                reason=f"max open positions reached ({open_positions}/{self.config.max_open_positions})",
            )

        if consecutive_losses >= self.config.max_consecutive_losses:
            return RiskDecision(
                allow_new_position=False,
                reason=(
                    f"consecutive loss circuit breaker active "
                    f"({consecutive_losses}/{self.config.max_consecutive_losses})"
                ),
            )

        return RiskDecision(allow_new_position=True)
