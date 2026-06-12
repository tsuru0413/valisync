"""Tests for Observable base class (Task 1.1).

Tests verify:
- subscribe receives notifications
- the returned unsubscribe stops further notifications
- multiple subscribers all notified
- notify with zero subscribers is a no-op
"""

from __future__ import annotations

from valisync.gui.viewmodels.observable import Observable


class _Recorder(Observable):
    """Minimal concrete Observable for testing."""

    def fire(self, tag: str) -> None:
        self._notify(tag)


def test_subscriber_receives_notification() -> None:
    """A subscribed callback receives the change tag from _notify."""
    obj = _Recorder()
    received: list[str] = []
    obj.subscribe(received.append)

    obj.fire("changed")

    assert received == ["changed"]


def test_unsubscribe_stops_notifications() -> None:
    """The callable returned by subscribe, when called, stops further notifications."""
    obj = _Recorder()
    received: list[str] = []
    unsubscribe = obj.subscribe(received.append)

    obj.fire("first")
    unsubscribe()
    obj.fire("second")

    assert received == ["first"]


def test_multiple_subscribers_all_notified() -> None:
    """Every subscriber receives the notification."""
    obj = _Recorder()
    log_a: list[str] = []
    log_b: list[str] = []
    obj.subscribe(log_a.append)
    obj.subscribe(log_b.append)

    obj.fire("event")

    assert log_a == ["event"]
    assert log_b == ["event"]


def test_notify_with_no_subscribers_is_noop() -> None:
    """Calling _notify with zero subscribers does not raise."""
    obj = _Recorder()
    obj.fire("no-one-listening")  # must not raise
