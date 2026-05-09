from __future__ import annotations

from collections import defaultdict

from app.models import MarketEvent, EventType, Order, OrderBookLevel, OrderBookSnapshot, OrderStatus, Side, Trade


class MatchingEngine:
    def __init__(self, symbol: str = "TGD-USD", initial_mid: float = 100.0, emit_snapshots: bool = True) -> None:
        self.symbol = symbol
        self.mid_price = initial_mid
        self.emit_snapshots = emit_snapshots
        self.orders: dict[str, Order] = {}
        self.bids: list[Order] = []
        self.asks: list[Order] = []
        self.trades: list[Trade] = []

    def place_order(self, trader_id: str, side: Side, price: float, quantity: int) -> list[MarketEvent]:
        order = Order(
            trader_id=trader_id,
            side=side,
            price=round(price, 2),
            quantity=quantity,
            remaining=quantity,
        )
        self.orders[order.order_id] = order
        book = self.bids if side == Side.BUY else self.asks
        book.append(order)
        events = [MarketEvent(event_type=EventType.ORDER_PLACED, payload=order.model_dump(mode="json"))]
        events.extend(self._match())
        if self.emit_snapshots:
            events.append(self.snapshot_event())
        return events

    def cancel_order(self, order_id: str) -> list[MarketEvent]:
        order = self.orders.get(order_id)
        if not order or order.status != OrderStatus.OPEN:
            return []

        cancelled_remaining = order.remaining
        order.status = OrderStatus.CANCELLED
        order.remaining = 0
        payload = order.model_dump(mode="json")
        payload["cancelled_remaining"] = cancelled_remaining
        self._remove_closed_orders()
        events = [MarketEvent(event_type=EventType.ORDER_CANCELLED, payload=payload)]
        if self.emit_snapshots:
            events.append(self.snapshot_event())
        return events

    def open_orders_for(self, trader_id: str) -> list[Order]:
        return [order for order in self.orders.values() if order.trader_id == trader_id and order.status == OrderStatus.OPEN]

    def snapshot(self, depth: int = 12) -> OrderBookSnapshot:
        bid_levels = self._levels(self.bids, reverse=True)[:depth]
        ask_levels = self._levels(self.asks, reverse=False)[:depth]
        best_bid = bid_levels[0].price if bid_levels else self.mid_price - 0.05
        best_ask = ask_levels[0].price if ask_levels else self.mid_price + 0.05
        mid = round((best_bid + best_ask) / 2, 2)
        return OrderBookSnapshot(symbol=self.symbol, bids=bid_levels, asks=ask_levels, mid_price=mid)

    def snapshot_event(self) -> MarketEvent:
        return MarketEvent(event_type=EventType.ORDERBOOK_SNAPSHOT, payload=self.snapshot().model_dump(mode="json"))

    def _match(self) -> list[MarketEvent]:
        events: list[MarketEvent] = []
        self.bids.sort(key=lambda order: (-order.price, order.timestamp_ms))
        self.asks.sort(key=lambda order: (order.price, order.timestamp_ms))

        while self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            buy = self.bids[0]
            sell = self.asks[0]
            quantity = min(buy.remaining, sell.remaining)
            price = sell.price if sell.timestamp_ms <= buy.timestamp_ms else buy.price
            buy.remaining -= quantity
            sell.remaining -= quantity
            if buy.remaining == 0:
                buy.status = OrderStatus.FILLED
            if sell.remaining == 0:
                sell.status = OrderStatus.FILLED
            trade = Trade(
                buy_order_id=buy.order_id,
                sell_order_id=sell.order_id,
                buyer_id=buy.trader_id,
                seller_id=sell.trader_id,
                price=price,
                quantity=quantity,
            )
            self.mid_price = price
            self.trades.append(trade)
            events.append(MarketEvent(event_type=EventType.TRADE_EXECUTED, payload=trade.model_dump(mode="json")))
            self._remove_closed_orders()
        return events

    def _remove_closed_orders(self) -> None:
        self.bids = [order for order in self.bids if order.status == OrderStatus.OPEN and order.remaining > 0]
        self.asks = [order for order in self.asks if order.status == OrderStatus.OPEN and order.remaining > 0]

    @staticmethod
    def _levels(orders: list[Order], reverse: bool) -> list[OrderBookLevel]:
        grouped: dict[float, list[Order]] = defaultdict(list)
        for order in orders:
            grouped[order.price].append(order)
        prices = sorted(grouped, reverse=reverse)
        return [
            OrderBookLevel(
                price=price,
                quantity=sum(order.remaining for order in grouped[price]),
                orders=len(grouped[price]),
            )
            for price in prices
        ]
