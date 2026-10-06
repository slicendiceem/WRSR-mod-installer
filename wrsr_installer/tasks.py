"""Running blocking work on background threads, with results delivered to the GUI thread."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Set

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from .cancel import Cancelled, CancelToken

log = logging.getLogger(__name__)


class _Signals(QObject):
    progress = pyqtSignal(object)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)
    cancelled = pyqtSignal()
    finished = pyqtSignal()


class TaskContext:
    """Handed to every task function: report progress and check for cancellation."""

    def __init__(self, signals: _Signals, cancel: CancelToken):
        self._signals = signals
        self.cancel = cancel

    def progress(self, value: Any) -> None:
        self._signals.progress.emit(value)


class Task(QRunnable):
    def __init__(self, fn: Callable[[TaskContext], Any]):
        super().__init__()
        self.setAutoDelete(False)  # kept alive by _running instead, see below
        self.signals = _Signals()  # created on the GUI thread, so callbacks run there
        self.token = CancelToken()
        self._fn = fn

    def cancel(self) -> None:
        self.token.cancel()

    def run(self) -> None:
        try:
            self.token.check()
            result = self._fn(TaskContext(self.signals, self.token))
        except Cancelled:
            self.signals.cancelled.emit()
        except Exception as e:  # reported to on_error; nothing may escape a worker thread
            log.exception('Background task failed')
            self.signals.failed.emit(e)
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()


# A task stays referenced until its "finished" signal reaches the GUI thread, so neither
# Python nor Qt can delete it (or its signals) while results are still on their way.
_running: Set[Task] = set()


def run_task(fn: Callable[[TaskContext], Any], *,
             on_result: Optional[Callable[[Any], None]] = None,
             on_error: Optional[Callable[[Exception], None]] = None,
             on_progress: Optional[Callable[[Any], None]] = None,
             on_cancelled: Optional[Callable[[], None]] = None,
             on_finished: Optional[Callable[[], None]] = None) -> Task:
    """Run fn(ctx) on the shared thread pool; callbacks run on the GUI thread."""
    task = Task(fn)
    signals = task.signals
    for signal, callback in ((signals.progress, on_progress), (signals.succeeded, on_result),
                             (signals.failed, on_error), (signals.cancelled, on_cancelled),
                             (signals.finished, on_finished)):
        if callback is not None:
            signal.connect(callback)
    signals.finished.connect(lambda: _running.discard(task))
    _running.add(task)
    QThreadPool.globalInstance().start(task)
    return task
