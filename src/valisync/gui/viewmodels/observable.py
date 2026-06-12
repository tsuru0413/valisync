"""Observable base class — Qt-independent publish/subscribe foundation.

Subclasses call ``_notify(change)`` to broadcast a string change tag to all
registered callbacks.  ``subscribe`` returns an unsubscribe callable so callers
can cleanly deregister without holding a reference to the Observable.
"""

from __future__ import annotations

from collections.abc import Callable


class Observable:
    """Minimal observable base: subscribe/unsubscribe + broadcast via _notify."""

    def __init__(self) -> None:
        # Use a dict keyed by an integer token so removal is O(1) without
        # requiring the caller to hold the original callable reference.
        self._callbacks: dict[int, Callable[[str], None]] = {}
        self._next_token: int = 0

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        """Register *callback* and return a zero-argument unsubscribe function."""
        token = self._next_token
        self._next_token += 1
        self._callbacks[token] = callback

        def unsubscribe() -> None:
            self._callbacks.pop(token, None)

        return unsubscribe

    def _notify(self, change: str) -> None:
        """Broadcast *change* to every currently registered callback."""
        for cb in list(self._callbacks.values()):
            cb(change)
