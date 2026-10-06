"""Cooperative cancellation for work running on background threads."""

import threading


class Cancelled(Exception):
    """The user cancelled the operation."""


class CancelToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        """Raise Cancelled if cancel() has been called."""
        if self._event.is_set():
            raise Cancelled()
