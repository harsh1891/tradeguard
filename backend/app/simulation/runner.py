from __future__ import annotations

import asyncio
from collections import deque
from typing import Awaitable, Callable

from app.detection.rules import DetectionEngine
from app.models import Alert, EventType, MarketEvent
from app.simulation.exchange import MatchingEngine
from app.simulation.traders import MarketMaker, QuoteStuffer, Spoofer, SyntheticTrader, TraderAction, WashTrader

EventHandler = Callable[[MarketEvent], Awaitable[None]]
AlertHandler = Callable[[Alert], Awaitable[None]]


class SimulationRunner:
    def __init__(self) -> None:
        self.engine = MatchingEngine()
        self.detector = DetectionEngine()
        self.running = False
        self._task: asyncio.Task | None = None
        self.events: deque[MarketEvent] = deque(maxlen=1000)
        self.alerts: deque[Alert] = deque(maxlen=250)
        self.on_event: EventHandler | None = None
        self.on_alert: AlertHandler | None = None
        self.traders = [
            SyntheticTrader("retail_001"),
            SyntheticTrader("retail_002"),
            MarketMaker("mm_delta"),
            MarketMaker("mm_sigma"),
            Spoofer("spoof_zen"),
            QuoteStuffer("quote_flash"),
        ]
        self.wash_trader = WashTrader("wash_alpha", "wash_beta")

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self.running:
            for action in self._next_actions():
                events = self._apply(action)
                for event in events:
                    await self._publish_event(event)
                    for alert in self.detector.process(event):
                        await self._publish_alert(alert)

            metrics = MarketEvent(event_type=EventType.METRICS, payload=self.detector.metrics())
            await self._publish_event(metrics)
            await asyncio.sleep(0.25)

    def _next_actions(self) -> list[TraderAction]:
        actions = [trader.next_action(self.engine) for trader in self.traders]
        if len(self.events) % 7 == 0:
            actions.extend(self.wash_trader.next_pair(self.engine))
        return actions

    def _apply(self, action: TraderAction) -> list[MarketEvent]:
        if action.action == "cancel" and action.order_id:
            return self.engine.cancel_order(action.order_id)
        if action.action == "place" and action.side and action.price and action.quantity:
            return self.engine.place_order(action.trader_id, action.side, action.price, action.quantity)
        return []

    async def _publish_event(self, event: MarketEvent) -> None:
        self.events.appendleft(event)
        if self.on_event:
            await self.on_event(event)

    async def _publish_alert(self, alert: Alert) -> None:
        self.alerts.appendleft(alert)
        if self.on_alert:
            await self.on_alert(alert)
