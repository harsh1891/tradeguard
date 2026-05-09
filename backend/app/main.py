from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from app.models import Alert, EventType, MarketEvent
from app.simulation.runner import SimulationRunner
from scripts.benchmark import run_stream_benchmark

app = FastAPI(title="TradeGuard API", version="0.1.0")

runner = SimulationRunner()

clients: dict[str, set[WebSocket]] = defaultdict(set)

STATIC_DIR = Path(__file__).parent / "static"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    runner.on_event = broadcast_event
    runner.on_alert = broadcast_alert


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "running": runner.running}


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(
        (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")
    )


@app.post("/simulation/start")
async def start_simulation() -> dict:
    await runner.start()
    return {"running": runner.running}


@app.post("/simulation/stop")
async def stop_simulation() -> dict:
    await runner.stop()
    return {"running": runner.running}


# NEW RESET API
@app.post("/simulation/reset")
async def reset_simulation() -> dict:

    global runner

    # stop current simulation
    await runner.stop()

    # completely recreate runner
    runner = SimulationRunner()

    # reconnect callbacks
    runner.on_event = broadcast_event
    runner.on_alert = broadcast_alert

    return {
        "status": "reset complete",
        "running": False
    }


@app.get("/orderbook")
async def orderbook() -> dict:
    return runner.engine.snapshot().model_dump(mode="json")


@app.get("/trades")
async def trades() -> list[dict]:
    return [
        trade.model_dump(mode="json")
        for trade in runner.engine.trades[-100:]
    ]


@app.get("/alerts")
async def alerts() -> list[dict]:
    return [
        alert.model_dump(mode="json")
        for alert in list(runner.alerts)
    ]


@app.get("/metrics")
async def metrics() -> dict:
    return runner.detector.metrics()


@app.post("/benchmark")
async def benchmark(events: int = 25_000) -> dict:
    bounded_events = max(1_000, min(events, 100_000))
    return run_stream_benchmark(bounded_events)


@app.websocket("/ws/{channel}")
async def websocket_channel(
    websocket: WebSocket,
    channel: str,
) -> None:

    await websocket.accept()

    clients[channel].add(websocket)

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        clients[channel].discard(websocket)


async def broadcast_event(event: MarketEvent) -> None:

    channels = {
        EventType.ORDERBOOK_SNAPSHOT: "orderbook",
        EventType.TRADE_EXECUTED: "trades",
        EventType.METRICS: "metrics",
    }

    channel = channels.get(event.event_type)

    if channel:
        await _broadcast(channel, event.payload)


async def broadcast_alert(alert: Alert) -> None:
    await _broadcast(
        "alerts",
        alert.model_dump(mode="json"),
    )


async def _broadcast(channel: str, payload: dict) -> None:

    stale: list[WebSocket] = []

    for websocket in clients[channel]:

        try:
            await websocket.send_json(payload)

        except RuntimeError:
            stale.append(websocket)

    for websocket in stale:
        clients[channel].discard(websocket)
