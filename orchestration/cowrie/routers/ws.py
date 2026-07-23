"""WebSocket endpoints - SRS §3.4.

"The communication between CowriePay and the backend will happen via HTTPS REST
for command and control purposes and WebSocket for the status of the transaction
push."

Three channels, matching the three audiences that need live updates:

    /ws/transfers?token=...   a sender watching their own transfers
    /ws/admin?token=...       the admin console's live feed (FR 5.1)
    /ws/public                the transparency page's live figures

The token is a query parameter rather than a header because the browser
WebSocket API cannot set headers on the handshake. That is a real weakness -
query strings end up in logs - and the mitigation is that these tokens are
short-lived and read-only over the socket: nothing can be changed through it.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..security import decode_token
from ..services.notifications import hub

router = APIRouter(tags=["websocket"])

#: Sent every 25 seconds. Many hosting layers close an idle socket at 30-60s,
#: and a settlement that takes 30 seconds must not lose its socket mid-transfer.
HEARTBEAT_SECONDS = 25


async def _pump(websocket: WebSocket, channel: str) -> None:
    """Hold the socket open, heartbeat, and drain anything the client sends.

    Draining matters: an un-read incoming buffer eventually stalls the
    connection even though this endpoint has no use for client messages.
    """
    await hub.connect(websocket, channel)
    heartbeat = asyncio.create_task(_heartbeat(websocket))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        heartbeat.cancel()
        with contextlib.suppress(Exception):
            await heartbeat
        await hub.disconnect(websocket, channel)


async def _heartbeat(websocket: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await websocket.send_json({"event": "heartbeat"})
    except asyncio.CancelledError:
        raise
    except Exception:
        return


@router.websocket("/ws/transfers")
async def transfers_socket(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Per-user transfer status push."""
    payload = decode_token(token, audience="cowriepay")
    if payload is None:
        await websocket.close(code=4401, reason="Invalid or expired session")
        return
    await _pump(websocket, f"user:{payload['sub']}")


@router.websocket("/ws/admin")
async def admin_socket(websocket: WebSocket, token: str = Query(default="")) -> None:
    """The admin console's live transaction feed (FR 5.1)."""
    payload = decode_token(token, audience="admin")
    if payload is None:
        await websocket.close(code=4401, reason="Invalid or expired admin session")
        return
    await _pump(websocket, "admin")


@router.websocket("/ws/public")
async def public_socket(websocket: WebSocket) -> None:
    """Unauthenticated feed for the transparency page.

    Carries aggregate figures only - it is published to anyone who connects, so
    nothing user-identifying is ever sent on this channel.
    """
    await _pump(websocket, "public")
