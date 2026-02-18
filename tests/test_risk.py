from autostock.config import RiskConfig
from autostock.risk import RiskManager


def _risk_manager() -> RiskManager:
    cfg = RiskConfig(
        max_position_pct=0.2,
        stop_loss_pct=0.08,
        symbol_daily_loss_pct=0.02,
        account_daily_drawdown_pct=0.05,
    )
    return RiskManager(cfg)


def test_max_shares_for_symbol_uses_position_cap() -> None:
    risk = _risk_manager()
    # 20% of 100,000 is 20,000; at $250/share -> 80 shares
    assert risk.max_shares_for_symbol(100_000.0, 250.0) == 80


def test_stop_loss_triggered() -> None:
    risk = _risk_manager()
    assert risk.stop_loss_triggered(avg_cost=100.0, last_price=92.0)
    assert not risk.stop_loss_triggered(avg_cost=100.0, last_price=93.0)


def test_evaluate_entry_guards_blocks_account_drawdown() -> None:
    risk = _risk_manager()
    decision = risk.evaluate_entry_guards(
        current_equity=94_900.0,
        day_start_equity=100_000.0,
        symbol_realized_pnl=0.0,
    )
    assert not decision.allow_new_position
    assert "drawdown" in decision.reason


def test_evaluate_entry_guards_blocks_symbol_daily_loss() -> None:
    risk = _risk_manager()
    decision = risk.evaluate_entry_guards(
        current_equity=100_000.0,
        day_start_equity=100_000.0,
        symbol_realized_pnl=-2_500.0,
    )
    assert not decision.allow_new_position
    assert "symbol daily loss" in decision.reason


def test_evaluate_entry_guards_allows_when_within_limits() -> None:
    risk = _risk_manager()
    decision = risk.evaluate_entry_guards(
        current_equity=99_500.0,
        day_start_equity=100_000.0,
        symbol_realized_pnl=-500.0,
    )
    assert decision.allow_new_position
