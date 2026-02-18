from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ib_insync import IB, MarketOrder, Stock

from autostock.config import IBConfig


@dataclass(slots=True)
class PositionInfo:
    symbol: str
    quantity: float
    avg_cost: float


class IBClient:
    def __init__(self, config: IBConfig) -> None:
        self.config = config
        self.ib = IB()

    def connect(self) -> None:
        self.ib.connect(self.config.host, self.config.port, clientId=self.config.client_id, timeout=10)

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()

    def is_connected(self) -> bool:
        return self.ib.isConnected()

    def get_equity(self) -> float:
        summary = self.ib.accountSummary(account=self.config.account)
        for item in summary:
            if item.tag == "NetLiquidation" and item.account == self.config.account:
                return float(item.value)
        for item in summary:
            if item.tag == "NetLiquidation":
                return float(item.value)
        raise RuntimeError("Unable to read NetLiquidation from account summary")

    def get_positions(self) -> dict[str, PositionInfo]:
        out: dict[str, PositionInfo] = {}
        for pos in self.ib.positions():
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


@dataclass(slots=True)
class HistoricalBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
