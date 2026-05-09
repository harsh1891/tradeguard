from __future__ import annotations

from enum import Enum
from time import time
from uuid import uuid4

from pydantic import BaseModel, Field


def now_ms() -> int:
    return int(time() * 1000)


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class EventType(str, Enum):
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    TRADE_EXECUTED = "TRADE_EXECUTED"
    ORDERBOOK_SNAPSHOT = "ORDERBOOK_SNAPSHOT"
    METRICS = "METRICS"


class AlertType(str, Enum):
    SPOOFING = "SPOOFING"
    WASH_TRADE = "WASH_TRADE"
    QUOTE_STUFFING = "QUOTE_STUFFING"
    LIQUIDITY_WALL = "LIQUIDITY_WALL"
    ABNORMAL_CANCEL_RATE = "ABNORMAL_CANCEL_RATE"


class Order(BaseModel):
    order_id: str = Field(default_factory=lambda: str(uuid4()))
    trader_id: str
    side: Side
    price: float
    quantity: int
    remaining: int
    timestamp_ms: int = Field(default_factory=now_ms)
    status: OrderStatus = OrderStatus.OPEN


class Trade(BaseModel):
    trade_id: str = Field(default_factory=lambda: str(uuid4()))
    buy_order_id: str
    sell_order_id: str
    buyer_id: str
    seller_id: str
    price: float
    quantity: int
    timestamp_ms: int = Field(default_factory=now_ms)


class MarketEvent(BaseModel):
    event_type: EventType
    timestamp_ms: int = Field(default_factory=now_ms)
    payload: dict


class Alert(BaseModel):
    alert_id: str = Field(default_factory=lambda: str(uuid4()))
    alert_type: AlertType
    trader_id: str
    severity: str
    score: float
    reason: str
    evidence: dict
    timestamp_ms: int = Field(default_factory=now_ms)


class OrderBookLevel(BaseModel):
    price: float
    quantity: int
    orders: int


class OrderBookSnapshot(BaseModel):
    symbol: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    mid_price: float
    timestamp_ms: int = Field(default_factory=now_ms)
