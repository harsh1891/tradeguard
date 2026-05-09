# Detection Rules

## Spoofing

An order is suspicious when:

- Quantity is much larger than recent average order size.
- It is cancelled quickly.
- It receives no fill before cancellation.

Current MVP threshold:

```text
quantity >= max(4 * average_recent_size, 600)
age_ms <= 2500
remaining == original_quantity
```

## Fake Liquidity Wall

An order is suspicious when:

- Quantity is much larger than recent average order size.
- Price is far enough from the assumed mid price to look like visible pressure instead of immediate execution interest.

Current MVP threshold:

```text
quantity >= max(6 * average_recent_size, 1200)
abs(price - 100.0) >= 0.45
```

## Wash Trading

A trade is suspicious when:

- Buyer and seller are the same trader.
- Buyer and seller are in a known linked-account pair.

The MVP uses synthetic linked accounts:

```text
wash_alpha <-> wash_beta
```

## Quote Stuffing

A trader is suspicious when many order placement or cancellation events occur in a very short window.

Current MVP threshold:

```text
order/cancel events in 3 seconds >= 24
```

## Abnormal Cancellation Rate

A trader is suspicious when:

- They have enough total orders to be meaningful.
- Their cancellation ratio is high.

Current MVP threshold:

```text
orders >= 12
cancels / orders >= 0.75
```
