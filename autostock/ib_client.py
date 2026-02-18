from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from ib_insync import IB, ExecutionFilter, MarketOrder, Stock

from autostock.config import IBConfig


@dataclass(slots=True)
class PositionInfo:
    symbol: str
    quantity: float
    avg_cost: float


@dataclass(slots=True)
class ExecutionInfo:
    exec_id: str
    ts_utc: str
    account: str
    symbol: str
    side: str
    quantity: float
    price: float
    order_id: int | None
    perm_id: int | None


def choose_account(preferred: str, managed_accounts: list[str]) -> str:
    pref = (preferred or "").strip()
    if pref and "XXXX" not in pref:
        if pref not in managed_accounts:
            raise RuntimeError(
                f"Configured IB account '{pref}' was not found in available accounts: {managed_accounts}"
            )
        return pref
    return managed_accounts[0]


class IBClient:
    def __init__(self, config: IBConfig) -> None:
        self.config = config
        self.ib = IB()
        self.account: str | None = None

    def connect(self) -> None:
        self.ib.connect(self.config.host, self.config.port, clientId=self.config.client_id, timeout=10)
        self.account = self._select_account()

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()

    def is_connected(self) -> bool:
        return self.ib.isConnected()

    def _select_account(self) -> str:
        preferred = (self.config.account or "").strip()
        managed_accounts: list[str] = []

        try:
            managed_accounts = list(self.ib.managedAccounts())
        except Exception:  # noqa: BLE001
            managed_accounts = []

        if not managed_accounts:
            managed_accounts = list(getattr(self.ib.wrapper, "accounts", []))

        if not managed_accounts:
            summary = self.ib.accountSummary()
            managed_accounts = sorted({str(item.account) for item in summary if getattr(item, "account", "")})

        if not managed_accounts:
            raise RuntimeError("Unable to detect any available IB accounts after connection")
        return choose_account(preferred, managed_accounts)

    def get_active_account(self) -> str:
        if not self.account:
            raise RuntimeError("IB account not selected; connect first")
        return self.account

    def get_equity(self) -> float:
        account = self.get_active_account()
        summary = self.ib.accountSummary(account=account)
        for item in summary:
            if item.tag == "NetLiquidation" and item.account == account:
                return float(item.value)
        for item in summary:
            if item.tag == "NetLiquidation":
                return float(item.value)
        raise RuntimeError("Unable to read NetLiquidation from account summary")

    def get_positions(self) -> dict[str, PositionInfo]:
        account = self.get_active_account()
        out: dict[str, PositionInfo] = {}
        for pos in self.ib.positions():
            if getattr(pos, "account", "") != account:
                continue
            symbol = pos.contract.symbol
            out[symbol] = PositionInfo(symbol=symbol, quantity=float(pos.position), avg_cost=float(pos.avgCost))
        return out

    def get_last_price(self, symbol: str) -> float:
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        ticker = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(1.0)
        price = ticker.marketPrice()
        if price is None or price <= 0:
            if ticker.last and ticker.last > 0:
                price = ticker.last
            elif ticker.close and ticker.close > 0:
                price = ticker.close
        self.ib.cancelMktData(contract)
        if price is None or price <= 0:
            raise RuntimeError(f"Unable to determine last price for {symbol}")
        return float(price)

    def get_recent_closes(self, symbol: str, duration: str, bar_size: str) -> list[float]:
        return [row.close for row in self.get_historical_bars(symbol, duration, bar_size)]

    def get_historical_bars(self, symbol: str, duration: str, bar_size: str) -> list["HistoricalBar"]:
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
            keepUpToDate=False,
        )
        out: list[HistoricalBar] = []
        for bar in bars:
            out.append(
                HistoricalBar(
                    date=str(bar.date),
                    open=float(bar.open),
                    high=float(bar.high),
                    low=float(bar.low),
                    close=float(bar.close),
                    volume=float(bar.volume),
                )
            )
        return out

    def submit_market_order(self, symbol: str, side: str, quantity: int) -> str:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        order = MarketOrder(side.upper(), quantity)
        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(1.0)
        return str(trade.orderStatus.status)

    def ensure_symbols(self, symbols: Iterable[str]) -> None:
        contracts = [Stock(sym, "SMART", "USD") for sym in symbols]
        self.ib.qualifyContracts(*contracts)

    def get_executions_since(self, since_utc_iso: str | None = None) -> list[ExecutionInfo]:
        account = self.get_active_account()
        filter_ = ExecutionFilter(acctCode=account)
        if since_utc_iso:
            since_dt = datetime.fromisoformat(since_utc_iso)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=UTC)
            since_dt = since_dt.astimezone()
            filter_.time = since_dt.strftime("%Y%m%d %H:%M:%S")
        fills = self.ib.reqExecutions(filter_)

        out: list[ExecutionInfo] = []
        for fill in fills:
            exec_ = fill.execution
            contract = fill.contract
            exec_time = exec_.time
            if exec_time.tzinfo is None:
                exec_time = exec_time.replace(tzinfo=UTC)
            ts_utc = exec_time.astimezone(UTC).isoformat()
            out.append(
                ExecutionInfo(
                    exec_id=str(exec_.execId),
                    ts_utc=ts_utc,
                    account=str(exec_.acctNumber),
                    symbol=str(contract.symbol),
                    side=str(exec_.side).upper(),
                    quantity=float(exec_.shares),
                    price=float(exec_.price),
                    order_id=int(exec_.orderId) if exec_.orderId is not None else None,
                    perm_id=int(exec_.permId) if exec_.permId is not None else None,
                )
            )
        return out


@dataclass(slots=True)
class HistoricalBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
