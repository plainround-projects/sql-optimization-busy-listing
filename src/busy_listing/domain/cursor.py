"""Opaque keyset cursors: the (created_at, id) of the last row a client received.

The client treats the token as a string and passes it back. Base64 hides the shape, it does not protect it:
a real service would sign the token so a client cannot forge one.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime

from .errors import InvalidCursorError


@dataclass(frozen=True, slots=True)
class Cursor:
    """A position in the newest-first ordering: rows strictly after this one come next."""

    created_at: datetime
    order_id: int

    def encode(self) -> str:
        """The opaque token handed to the client."""
        payload = json.dumps({"t": self.created_at.isoformat(), "i": self.order_id}, separators=(",", ":"))
        return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> Cursor:
        """Read a token back; raises `InvalidCursorError` for anything this service did not issue."""
        try:
            padded = token + "=" * (-len(token) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            return cls(datetime.fromisoformat(payload["t"]), int(payload["i"]))
        except (binascii.Error, ValueError, KeyError, TypeError) as error:
            raise InvalidCursorError("the cursor is not one this service issued") from error
