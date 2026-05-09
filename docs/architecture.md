# TradeGuard Architecture

## MVP Goal

The first version is designed to prove the core surveillance loop end to end:

```text
simulate market activity -> process order book events -> detect manipulation -> stream alerts to UI
```

## Components

### Synthetic Traders

The simulator includes normal traders, market makers, and adversarial strategies:

- `SyntheticTrader`: small randomized orders.
- `MarketMaker`: two-sided activity near the mid price.
- `Spoofer`: large visible orders cancelled quickly.
- `QuoteStuffer`: many small order/cancel events.
- `WashTrader`: linked accounts trading with each other.

### Matching Engine

The Python matching engine keeps separate bid and ask books:

- Bids sort by highest price first.
- Asks sort by lowest price first.
- Matching occurs when best bid is greater than or equal to best ask.
- Each placement, cancellation, trade, and snapshot becomes a structured event.

### Detection Engine

The detector is intentionally rule-based in the MVP so every alert is explainable. Each alert includes:

- Alert type.
- Trader id.
- Severity.
- Score.
- Human-readable reason.
- Evidence dictionary.

### API Layer

FastAPI exposes both pull and push interfaces:

- REST endpoints for snapshots and controls.
- WebSocket channels for live order book, trades, metrics, and alerts.

### Dashboard

The React dashboard subscribes to WebSocket channels and renders a surveillance terminal:

- Live order book.
- Price flow chart.
- Alert feed.
- Trade feed.
- Trader risk table.

## Upgrade Path

The next backend upgrade should be SQLite persistence. After that, historical replay can read stored events and send them through the same detection and WebSocket pipeline.

The next systems upgrade should be a C++ matching engine exposed to Python with pybind11. That gives the project a credible low-latency systems component while preserving Python for API, analytics, and experimentation.
