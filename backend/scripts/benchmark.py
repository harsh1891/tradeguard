from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.detection.rules import DetectionEngine
from app.models import Alert, EventType, MarketEvent, Side, now_ms
from app.simulation.exchange import MatchingEngine
from app.simulation.traders import MarketMaker, QuoteStuffer, Spoofer, SyntheticTrader, TraderAction, WashTrader


MANIPULATIVE_TRADERS = {"spoof_zen", "quote_flash", "wash_alpha", "wash_beta"}


def build_actions(engine: MatchingEngine, traders: list[SyntheticTrader], wash_trader: WashTrader, step: int) -> list[TraderAction]:
    actions = [trader.next_action(engine) for trader in traders]
    if step % 7 == 0:
        actions.extend(wash_trader.next_pair(engine))
    return actions


def apply_action(engine: MatchingEngine, action: TraderAction) -> list[MarketEvent]:
    if action.action == "cancel" and action.order_id:
        return engine.cancel_order(action.order_id)
    if action.action == "place" and action.side and action.price and action.quantity:
        return engine.place_order(action.trader_id, action.side, action.price, action.quantity)
    return []


def evaluate_alert(alert: Alert) -> tuple[int, int, int]:
    is_true_positive = alert.trader_id in MANIPULATIVE_TRADERS
    if alert.alert_type.value == "WASH_TRADE":
        buyer = alert.evidence.get("buyer_id")
        seller = alert.evidence.get("seller_id")
        is_true_positive = buyer in MANIPULATIVE_TRADERS or seller in MANIPULATIVE_TRADERS
    if is_true_positive:
        return 1, 0, 0
    return 0, 1, 0


def run_benchmark(target_events: int, seed: int) -> dict:
    random.seed(seed)
    return run_stream_benchmark(target_events)


def make_order(trader_id: str, side: Side, price: float, quantity: int, timestamp_ms: int) -> dict:
    return {
        "order_id": str(uuid4()),
        "trader_id": trader_id,
        "side": side.value,
        "price": round(price, 2),
        "quantity": quantity,
        "remaining": quantity,
        "timestamp_ms": timestamp_ms,
        "status": "OPEN",
    }


def make_cancel(order: dict) -> dict:
    return {
        **order,
        "status": "CANCELLED",
        "remaining": 0,
        "cancelled_remaining": order["remaining"],
    }


def make_trade(buyer_id: str, seller_id: str, price: float, quantity: int, timestamp_ms: int) -> dict:
    return {
        "trade_id": str(uuid4()),
        "buy_order_id": str(uuid4()),
        "sell_order_id": str(uuid4()),
        "buyer_id": buyer_id,
        "seller_id": seller_id,
        "price": round(price, 2),
        "quantity": quantity,
        "timestamp_ms": timestamp_ms,
    }


def generate_stream_events(open_orders: dict[str, list[dict]], step: int) -> list[MarketEvent]:
    events: list[MarketEvent] = []
    mid = 100 + random.uniform(-0.15, 0.15)
    timestamp_ms = 1_700_000_000_000 + step * 250

    for trader_id in ["retail_001", "retail_002", "mm_delta", "mm_sigma"]:
        side = random.choice([Side.BUY, Side.SELL])
        order = make_order(trader_id, side, mid + random.uniform(-0.2, 0.2), random.randint(20, 220), timestamp_ms)
        open_orders.setdefault(trader_id, []).append(order)
        events.append(MarketEvent(event_type=EventType.ORDER_PLACED, timestamp_ms=timestamp_ms, payload=order))

    if step % 3 == 0:
        order = make_order("spoof_zen", random.choice([Side.BUY, Side.SELL]), mid + random.choice([-0.65, 0.65]), random.randint(900, 2400), timestamp_ms)
        events.append(MarketEvent(event_type=EventType.ORDER_PLACED, timestamp_ms=timestamp_ms, payload=order))
        events.append(MarketEvent(event_type=EventType.ORDER_CANCELLED, timestamp_ms=timestamp_ms + 80, payload=make_cancel(order)))

    if step % 2 == 0:
        for _ in range(8):
            order = make_order("quote_flash", random.choice([Side.BUY, Side.SELL]), mid + random.uniform(-0.05, 0.05), random.randint(1, 25), timestamp_ms)
            events.append(MarketEvent(event_type=EventType.ORDER_PLACED, timestamp_ms=timestamp_ms, payload=order))
            if random.random() < 0.75:
                events.append(MarketEvent(event_type=EventType.ORDER_CANCELLED, timestamp_ms=timestamp_ms + 20, payload=make_cancel(order)))

    if step % 7 == 0:
        events.append(MarketEvent(event_type=EventType.TRADE_EXECUTED, timestamp_ms=timestamp_ms, payload=make_trade("wash_alpha", "wash_beta", mid, random.randint(80, 240), timestamp_ms)))

    if step % 5 == 0:
        events.append(MarketEvent(event_type=EventType.TRADE_EXECUTED, timestamp_ms=timestamp_ms, payload=make_trade("retail_001", "mm_delta", mid, random.randint(10, 120), timestamp_ms)))

    for trader_id, orders in list(open_orders.items()):
        if orders and random.random() < 0.08:
            events.append(MarketEvent(event_type=EventType.ORDER_CANCELLED, timestamp_ms=timestamp_ms, payload=make_cancel(orders.pop())))

    return events


def run_stream_benchmark(target_events: int) -> dict:
    detector = DetectionEngine()
    open_orders: dict[str, list[dict]] = {}
    event_count = 0
    order_count = 0
    trade_count = 0
    cancel_count = 0
    alert_count = 0
    true_positive = 0
    false_positive = 0
    detection_latency_ms: list[float] = []
    alert_types: Counter[str] = Counter()
    start = perf_counter()
    step = 0

    while event_count < target_events:
        step += 1
        for event in generate_stream_events(open_orders, step):
            event_count += 1
            if event.event_type == EventType.ORDER_PLACED:
                order_count += 1
            elif event.event_type == EventType.ORDER_CANCELLED:
                cancel_count += 1
            elif event.event_type == EventType.TRADE_EXECUTED:
                trade_count += 1

            detect_start = perf_counter()
            alerts = detector.process(event)
            detection_latency_ms.append((perf_counter() - detect_start) * 1000)

            for alert in alerts:
                alert_count += 1
                alert_types[alert.alert_type.value] += 1
                tp, fp, _ = evaluate_alert(alert)
                true_positive += tp
                false_positive += fp

            if event_count >= target_events:
                break

    return summarize_results(
        event_count,
        order_count,
        trade_count,
        cancel_count,
        alert_count,
        true_positive,
        false_positive,
        detection_latency_ms,
        alert_types,
        start,
        detector,
    )


def run_exchange_benchmark(target_events: int, seed: int) -> dict:
    random.seed(seed)
    engine = MatchingEngine(emit_snapshots=False)
    detector = DetectionEngine()
    traders = [
        SyntheticTrader("retail_001"),
        SyntheticTrader("retail_002"),
        MarketMaker("mm_delta"),
        MarketMaker("mm_sigma"),
        Spoofer("spoof_zen"),
        QuoteStuffer("quote_flash"),
    ]
    wash_trader = WashTrader("wash_alpha", "wash_beta")
    event_count = 0
    order_count = 0
    trade_count = 0
    cancel_count = 0
    alert_count = 0
    true_positive = 0
    false_positive = 0
    detection_latency_ms: list[float] = []
    alert_types: Counter[str] = Counter()
    start = perf_counter()
    step = 0

    while event_count < target_events:
        step += 1
        for action in build_actions(engine, traders, wash_trader, step):
            for event in apply_action(engine, action):
                event_count += 1
                if event.event_type == EventType.ORDER_PLACED:
                    order_count += 1
                elif event.event_type == EventType.ORDER_CANCELLED:
                    cancel_count += 1
                elif event.event_type == EventType.TRADE_EXECUTED:
                    trade_count += 1

                detect_start = perf_counter()
                alerts = detector.process(event)
                detection_latency_ms.append((perf_counter() - detect_start) * 1000)

                for alert in alerts:
                    alert_count += 1
                    alert_types[alert.alert_type.value] += 1
                    tp, fp, _ = evaluate_alert(alert)
                    true_positive += tp
                    false_positive += fp

                if event_count >= target_events:
                    break
            if event_count >= target_events:
                break

    return summarize_results(
        event_count,
        order_count,
        trade_count,
        cancel_count,
        alert_count,
        true_positive,
        false_positive,
        detection_latency_ms,
        alert_types,
        start,
        detector,
    )


def summarize_results(
    event_count: int,
    order_count: int,
    trade_count: int,
    cancel_count: int,
    alert_count: int,
    true_positive: int,
    false_positive: int,
    detection_latency_ms: list[float],
    alert_types: Counter[str],
    start: float,
    detector: DetectionEngine,
) -> dict:
    runtime_seconds = perf_counter() - start
    precision = true_positive / max(true_positive + false_positive, 1)
    labelled_recall_proxy = len({name for name in MANIPULATIVE_TRADERS if name in detector.trader_events}) / len(MANIPULATIVE_TRADERS)
    avg_latency = sum(detection_latency_ms) / max(len(detection_latency_ms), 1)
    max_latency = max(detection_latency_ms) if detection_latency_ms else 0.0

    return {
        "events_processed": event_count,
        "orders": order_count,
        "trades": trade_count,
        "cancellations": cancel_count,
        "alerts": alert_count,
        "alert_breakdown": dict(alert_types),
        "runtime_seconds": round(runtime_seconds, 4),
        "events_per_second": round(event_count / max(runtime_seconds, 0.0001), 2),
        "avg_detection_latency_ms": round(avg_latency, 6),
        "max_detection_latency_ms": round(max_latency, 6),
        "labelled_precision": round(precision, 4),
        "labelled_recall_proxy": round(labelled_recall_proxy, 4),
        "true_positive_alerts": true_positive,
        "false_positive_alerts": false_positive,
    }


def print_report(results: dict) -> None:
    print("TradeGuard Benchmark")
    print("====================")
    print(f"Events processed: {results['events_processed']:,}")
    print(f"Runtime: {results['runtime_seconds']} seconds")
    print(f"Throughput: {results['events_per_second']:,} events/sec")
    print(f"Average detection latency: {results['avg_detection_latency_ms']} ms/event")
    print(f"Max detection latency: {results['max_detection_latency_ms']} ms/event")
    print(f"Orders: {results['orders']:,}")
    print(f"Trades: {results['trades']:,}")
    print(f"Cancellations: {results['cancellations']:,}")
    print(f"Alerts generated: {results['alerts']:,}")
    print(f"Labelled precision: {results['labelled_precision']:.2%}")
    print(f"Labelled recall proxy: {results['labelled_recall_proxy']:.2%}")
    print("Alert breakdown:")
    for alert_type, count in sorted(results["alert_breakdown"].items()):
        print(f"  {alert_type}: {count:,}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a high-volume TradeGuard simulation benchmark.")
    parser.add_argument("--events", type=int, default=100_000, help="Number of market events to process.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible simulation.")
    parser.add_argument("--mode", choices=["stream", "exchange"], default="stream", help="Use fast labelled stream mode or full exchange mode.")
    parser.add_argument("--json-out", type=Path, help="Optional path to save benchmark results as JSON.")
    args = parser.parse_args()

    if args.mode == "exchange":
        results = run_exchange_benchmark(target_events=args.events, seed=args.seed)
    else:
        random.seed(args.seed)
        results = run_stream_benchmark(target_events=args.events)
    print_report(results)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Saved JSON report: {args.json_out}")


if __name__ == "__main__":
    main()
