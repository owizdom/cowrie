"""Notification Service - the WebSocket participant in the sequence diagram.

SRS 3.4: "The communication between CowriePay and the backend will happen via
HTTPS REST for command and control purposes and WebSocket for the status of the
transaction push."

The sequence diagram gives the Notification Service two messages, both pushed
rather than polled: step 20 "Transfer complete" and step 24 "Transfer refunded".
Everything in between - each state transition and each new confirmation count -
is pushed on the same socket, which is what lets the CowriePay status screen
count 1/12 ... 12/12 without hammering the API.

Three channels exist:
    user:<user_id>    a sender watching their own transfer
    admin             the live transaction feed in the admin console (FR 5.1)
    public            transparency page figures

Delivery is best-effort.  A dropped socket must never hold up settlement, so
every send is wrapped and failures only prune the connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket


class NotificationHub:
    """In-process pub/sub over WebSocket connections.

    In-process is the right scope for a single-container demo.  SRS 3.3 lists
    Redis as the queue for a multi-container deployment; the publish() signature
    is what a Redis pub/sub backend would implement, so the swap is contained.
    """

    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._history: dict[str, list[dict]] = defaultdict(list)

    async def connect(self, websocket: WebSocket, channel: str) -> None:
        await websocket.accept()
        async with self._lock:
            self._channels[channel].add(websocket)
        # Replay recent events so a client that connects mid-transfer is not
        # blind to the states it missed.
        for event in self._history.get(channel, [])[-20:]:
            with contextlib.suppress(Exception):
                await websocket.send_text(json.dumps(event))

    async def disconnect(self, websocket: WebSocket, channel: str) -> None:
        async with self._lock:
            self._channels[channel].discard(websocket)

    async def publish(self, channel: str, event: str, payload: dict[str, Any]) -> None:
        message = {
            "channel": channel,
            "event": event,
            "ts": datetime.now(UTC).isoformat(),
            "data": payload,
        }

        history = self._history[channel]
        history.append(message)
        if len(history) > 200:
            del history[:-200]

        async with self._lock:
            targets = list(self._channels.get(channel, ()))

        if not targets:
            return

        encoded = json.dumps(message, default=str)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(encoded)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._channels[channel].discard(ws)

    async def push_transaction(self, transaction, event: str, extra: dict | None = None) -> None:
        """Fan one transaction update out to the sender and to the admin feed."""
        payload = {
            "transactionId": transaction.id,
            "reference": transaction.reference,
            "state": str(transaction.state),
            "sourceAmount": str(transaction.sourceAmount),
            "sourceCurrency": transaction.sourceCurrency,
            "destinationAmount": str(transaction.destinationAmount),
            "destinationCurrency": transaction.destinationCurrency,
            "recipientName": transaction.recipientName,
            "failureReason": transaction.failureReason,
            **(extra or {}),
        }
        if transaction.senderId:
            await self.publish(f"user:{transaction.senderId}", event, payload)
        await self.publish("admin", event, payload)

    def connection_count(self) -> dict[str, int]:
        return {channel: len(sockets) for channel, sockets in self._channels.items() if sockets}


hub = NotificationHub()
