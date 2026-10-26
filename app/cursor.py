"""Opaque keyset cursors: the (created_at, id) of the last row a client received.

The client treats the token as a string and passes it back. Base64 hides the shape, it does not protect it:
a real service would sign the token so a client cannot forge one.
"""
import base64
import json
from datetime import datetime


def encode(created_at: datetime, order_id: int) -> str:
    payload = json.dumps({"t": created_at.isoformat(), "i": order_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode(token: str) -> tuple[datetime, int]:
    padded = token + "=" * (-len(token) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    return datetime.fromisoformat(payload["t"]), int(payload["i"])
