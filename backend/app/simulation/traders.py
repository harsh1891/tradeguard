from __future__ import annotations

import random
from dataclasses import dataclass

from app.models import Side
from app.simulation.exchange import MatchingEngine


@dataclass
class TraderAction:
    action: str
    trader_id: str
    side: Side | None = None
    price: float | None = None
    quantity: int | None = None
    order_id: str | None = None


class SyntheticTrader:
    def __init__(self, trader_id: str) -> None:
        self.trader_id = trader_id

    def next_action(self, engine: MatchingEngine) -> TraderAction:
        side = random.choice([Side.BUY, Side.SELL])
        price_offset = random.uniform(0.02, 0.35)
        price = engine.mid_price - price_offset if side == Side.BUY else engine.mid_price + price_offset
        return TraderAction(
            action="place",
            trader_id=self.trader_id,
            side=side,
            price=price,
            quantity=random.randint(10, 180),
        )


class MarketMaker(SyntheticTrader):
    def next_action(self, engine: MatchingEngine) -> TraderAction:
        side = random.choice([Side.BUY, Side.SELL])
        spread = random.uniform(0.03, 0.12)
        price = engine.mid_price - spread if side == Side.BUY else engine.mid_price + spread
        return TraderAction("place", self.trader_id, side, price, random.randint(40, 260))


class Spoofer(SyntheticTrader):
    def next_action(self, engine: MatchingEngine) -> TraderAction:
        open_orders = engine.open_orders_for(self.trader_id)
        if open_orders and random.random() < 0.7:
            return TraderAction("cancel", self.trader_id, order_id=random.choice(open_orders).order_id)
        side = random.choice([Side.BUY, Side.SELL])
        offset = random.uniform(0.3, 0.7)
        price = engine.mid_price - offset if side == Side.BUY else engine.mid_price + offset
        return TraderAction("place", self.trader_id, side, price, random.randint(900, 2200))


class QuoteStuffer(SyntheticTrader):
    def next_action(self, engine: MatchingEngine) -> TraderAction:
        open_orders = engine.open_orders_for(self.trader_id)
        if open_orders and random.random() < 0.55:
            return TraderAction("cancel", self.trader_id, order_id=random.choice(open_orders).order_id)
        side = random.choice([Side.BUY, Side.SELL])
        price = engine.mid_price + random.uniform(-0.2, 0.2)
        return TraderAction("place", self.trader_id, side, price, random.randint(1, 25))


class WashTrader(SyntheticTrader):
    def __init__(self, trader_id: str, counterparty_id: str) -> None:
        super().__init__(trader_id)
        self.counterparty_id = counterparty_id

    def next_pair(self, engine: MatchingEngine) -> list[TraderAction]:
        quantity = random.randint(80, 220)
        price = engine.mid_price + random.uniform(-0.02, 0.02)
        return [
            TraderAction("place", self.trader_id, Side.BUY, price, quantity),
            TraderAction("place", self.counterparty_id, Side.SELL, price, quantity),
        ]
