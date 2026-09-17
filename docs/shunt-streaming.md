# Shunt300 subscriptions

`ShuntBleClient` supports intermittent `read_device()` calls and sustained
subscriptions. Both use `ShuntNotificationDecoder` to reassemble notification
fragments, skip noise/history or implausible frames, and return normalized live
readings. An observed `61d2` prefix is skipped while locating the live header.
Coalesced notifications deliver each complete frame in order. Retained partial
data is bounded by the configured frame length and discarded on reconnect.

Readings include the existing `shunt_*`, temperature, starter voltage,
`reading_verified`, `decode_confidence`, `raw_payload` (normalized frame hex),
`raw_words` (big-endian 16-bit words), and cumulative energy fields. There is no
known frame checksum; decoding retains the existing header and plausibility
checks. Energy is integrated in kWh using the current sample's power and a
monotonic timestamp. Non-positive intervals and intervals of ten hours or more
are ignored. Each device has independent totals, retained across connections and
subscriptions on the same client. Persistence/restoration belongs to the caller.

```python
import asyncio

from renogy_ble.shunt import ShuntBleClient

# device is a discovered RenogyBLEDevice.
client = ShuntBleClient()
subscription = client.subscribe(
    resolve_device=lambda: device,
    on_update=lambda reading: print(reading),
    on_error=lambda error: print(f"Shunt session error: {error}"),
)
task = asyncio.create_task(subscription.run())
try:
    await application_shutdown_event.wait()
finally:
    await subscription.close()
```

The application owns the task. `run()` may only be called once per subscription.
`close()` is idempotent, cancels retries, and waits for bounded notification and
connection cleanup. Cancelling `run()` also initiates cleanup and propagates
`CancelledError`; await `close()` when shutting down. Callbacks execute
synchronously on the event loop and must not block. Callback exceptions are sent
to `on_error` without breaking subsequent notification handling. Exceptions in
`on_error` are logged.

Stopping notifications and disconnecting each have a five-second timeout by
default (`ShuntBleClient(disconnect_timeout=...)` changes each bound). If the
application cancels `close()` itself, cancellation propagates and the retained
cleanup task continues; a later `close()` can await it. Cleanup errors still reach
`on_error` even after cancellation. Normal close waits for cleanup to finish.

`resolve_device` runs before every attempt and may return `None` to defer
connection for discovery or an application cooldown. It should resolve one
subscription's device. The library clears the BlueZ cache before each sustained
attempt and disables the service cache. After a successful clear, the optional
`rediscover_device(address)` callback must return a fresh `BLEDevice` or `None` to
defer connection. Without that callback, the library uses BleakScanner. Cache
clearing failures fall back to the existing handle, as needed on other backends.
Retries wait ten seconds by default. Unexpected disconnects, connection failures,
notification failures, and cleanup failures reach `on_error`. Non-live data is
ignored; sustained sessions impose no new notification inactivity deadline.

Do not run simultaneous reads or subscriptions for the same device on one client.
Create a new subscription after closing the old one, reusing the client to retain
energy state. For direct decoder use, keep one decoder per device, feed bytes in
arrival order, and call `reset_buffer()` at every connection boundary.
