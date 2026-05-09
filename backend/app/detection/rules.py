from __future__ import annotations

from collections import defaultdict, deque
from statistics import mean

from app.models import Alert, AlertType, EventType, MarketEvent, Side, now_ms


class DetectionEngine:
    def __init__(self) -> None:
        self.trader_events: dict[str, deque[MarketEvent]] = defaultdict(lambda: deque(maxlen=250))
        self.order_state: dict[str, dict] = {}
        self.trader_orders: dict[str, list[dict]] = defaultdict(list)
        self.trader_cancels: dict[str, int] = defaultdict(int)
        self.trader_trades: dict[str, int] = defaultdict(int)
        self.recent_order_sizes: deque[int] = deque(maxlen=500)
        self.recent_alert_keys: deque[str] = deque(maxlen=500)

    def process(self, event: MarketEvent) -> list[Alert]:
        alerts: list[Alert] = []
        payload = event.payload
        current_ms = event.timestamp_ms

        if event.event_type == EventType.ORDER_PLACED:
            trader_id = payload["trader_id"]
            baseline_avg_size = mean(self.recent_order_sizes) if self.recent_order_sizes else 100
            payload = {**payload, "baseline_avg_size": baseline_avg_size}
            self.order_state[payload["order_id"]] = payload
            self.trader_events[trader_id].append(event)
            self.trader_orders[trader_id].append(payload)
            alerts.extend(self._detect_liquidity_wall(payload))
            self.recent_order_sizes.append(payload["quantity"])
            alerts.extend(self._detect_quote_stuffing(trader_id, current_ms))

        if event.event_type == EventType.ORDER_CANCELLED:
            payload = {**self.order_state.get(payload["order_id"], {}), **payload}
            trader_id = payload["trader_id"]
            self.trader_events[trader_id].append(event)
            self.trader_cancels[trader_id] += 1
            alerts.extend(self._detect_spoofing(payload, current_ms))
            alerts.extend(self._detect_cancel_ratio(trader_id))
            alerts.extend(self._detect_quote_stuffing(trader_id, current_ms))

        if event.event_type == EventType.TRADE_EXECUTED:
            buyer_id = payload["buyer_id"]
            seller_id = payload["seller_id"]
            self.trader_trades[buyer_id] += 1
            self.trader_trades[seller_id] += 1
            self.trader_events[buyer_id].append(event)
            self.trader_events[seller_id].append(event)
            alerts.extend(self._detect_wash_trade(payload))

        return [alert for alert in alerts if self._dedupe(alert)]

    def metrics(self) -> dict:
        total_orders = sum(len(items) for items in self.trader_orders.values())
        total_cancels = sum(self.trader_cancels.values())
        total_trades = sum(self.trader_trades.values()) // 2
        suspicious = sorted(
            (
                {
                    "trader_id": trader_id,
                    "orders": len(orders),
                    "cancels": self.trader_cancels[trader_id],
                    "trades": self.trader_trades[trader_id],
                    "cancel_ratio": round(self.trader_cancels[trader_id] / max(len(orders), 1), 2),
                }
                for trader_id, orders in self.trader_orders.items()
            ),
            key=lambda row: row["cancel_ratio"],
            reverse=True,
        )[:8]
        return {
            "total_orders": total_orders,
            "total_cancels": total_cancels,
            "total_trades": total_trades,
            "event_time_ms": now_ms(),
            "traders": suspicious,
        }

    def _detect_spoofing(self, order: dict, current_ms: int) -> list[Alert]:
        age_ms = current_ms - order["timestamp_ms"]
        avg_size = order.get("baseline_avg_size")
        if not avg_size:
            avg_size = mean(self.recent_order_sizes) if self.recent_order_sizes else 100
        is_large = order["quantity"] >= max(avg_size * 4, 600)
        is_fast_cancel = age_ms <= 2500
        no_fill = order.get("cancelled_remaining", order["remaining"]) == order["quantity"]
        if not (is_large and is_fast_cancel and no_fill):
            return []
        score = min(100.0, 45 + (order["quantity"] / max(avg_size, 1)) * 8 + max(0, 2500 - age_ms) / 50)
        return [
            Alert(
                alert_type=AlertType.SPOOFING,
                trader_id=order["trader_id"],
                severity="HIGH" if score > 80 else "MEDIUM",
                score=round(score, 2),
                reason="Large order cancelled quickly before execution.",
                evidence={"order_id": order["order_id"], "age_ms": age_ms, "quantity": order["quantity"], "avg_size": round(avg_size, 2)},
            )
        ]

    def _detect_cancel_ratio(self, trader_id: str) -> list[Alert]:
        orders = len(self.trader_orders[trader_id])
        cancels = self.trader_cancels[trader_id]
        ratio = cancels / max(orders, 1)
        if orders >= 12 and ratio >= 0.75:
            return [
                Alert(
                    alert_type=AlertType.ABNORMAL_CANCEL_RATE,
                    trader_id=trader_id,
                    severity="MEDIUM",
                    score=round(ratio * 100, 2),
                    reason="Trader cancellation rate is unusually high.",
                    evidence={"orders": orders, "cancels": cancels, "cancel_ratio": round(ratio, 2)},
                )
            ]
        return []

    def _detect_quote_stuffing(self, trader_id: str, current_ms: int) -> list[Alert]:
        window_ms = 3000
        events = [event for event in self.trader_events[trader_id] if current_ms - event.timestamp_ms <= window_ms]
        order_events = [event for event in events if event.event_type in {EventType.ORDER_PLACED, EventType.ORDER_CANCELLED}]
        if len(order_events) >= 24:
            return [
                Alert(
                    alert_type=AlertType.QUOTE_STUFFING,
                    trader_id=trader_id,
                    severity="HIGH",
                    score=min(100, len(order_events) * 4),
                    reason="Trader submitted excessive order traffic in a short window.",
                    evidence={"events_in_3s": len(order_events)},
                )
            ]
        return []

    def _detect_liquidity_wall(self, order: dict) -> list[Alert]:
        if not self.recent_order_sizes:
            return []
        avg_size = mean(self.recent_order_sizes)
        side = Side(order["side"])
        far_from_mid = abs(order["price"] - 100.0) >= 0.45
        if order["quantity"] >= max(avg_size * 6, 1200) and far_from_mid:
            return [
                Alert(
                    alert_type=AlertType.LIQUIDITY_WALL,
                    trader_id=order["trader_id"],
                    severity="MEDIUM",
                    score=75.0,
                    reason=f"Large {side.value.lower()} wall may be creating fake visible liquidity.",
                    evidence={"order_id": order["order_id"], "price": order["price"], "quantity": order["quantity"], "avg_size": round(avg_size, 2)},
                )
            ]
        return []

    def _detect_wash_trade(self, trade: dict) -> list[Alert]:
        buyer = trade["buyer_id"]
        seller = trade["seller_id"]
        linked_accounts = {("wash_alpha", "wash_beta"), ("wash_beta", "wash_alpha")}
        if buyer == seller or (buyer, seller) in linked_accounts:
            return [
                Alert(
                    alert_type=AlertType.WASH_TRADE,
                    trader_id=buyer,
                    severity="HIGH",
                    score=95.0,
                    reason="Trade executed between the same or linked entities.",
                    evidence={"buyer_id": buyer, "seller_id": seller, "price": trade["price"], "quantity": trade["quantity"]},
                )
            ]
        return []

    def _dedupe(self, alert: Alert) -> bool:
        key = f"{alert.alert_type}:{alert.trader_id}:{alert.reason}"
        if key in self.recent_alert_keys:
            return False
        self.recent_alert_keys.append(key)
        return True
