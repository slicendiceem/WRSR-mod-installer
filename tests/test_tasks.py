import gc
import threading
import time

from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QApplication

from wrsr_installer.tasks import run_task


def test_result_is_delivered_on_the_gui_thread(qtbot):
    seen = []

    def work(ctx):
        return threading.current_thread().name

    run_task(work, on_result=lambda value: seen.append((value, QThread.currentThread())))
    qtbot.waitUntil(lambda: bool(seen), timeout=5000)

    worker_thread_name, callback_thread = seen[0]
    assert worker_thread_name != threading.main_thread().name
    assert callback_thread is QApplication.instance().thread()


def test_errors_are_delivered_to_on_error(qtbot):
    errors = []

    def work(ctx):
        raise ValueError('boom')

    run_task(work, on_error=errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=5000)

    assert isinstance(errors[0], ValueError) and str(errors[0]) == 'boom'


def test_progress_arrives_in_order_before_the_result(qtbot):
    events = []

    def work(ctx):
        ctx.progress(1)
        ctx.progress(2)
        return 'done'

    run_task(work, on_progress=events.append, on_result=events.append)
    qtbot.waitUntil(lambda: 'done' in events, timeout=5000)

    assert events == [1, 2, 'done']


def test_cancel_stops_work_and_reports_cancelled(qtbot):
    outcome = []

    def work(ctx):
        for _ in range(500):
            ctx.cancel.check()
            time.sleep(0.01)
        return 'finished'

    task = run_task(work, on_result=outcome.append, on_cancelled=lambda: outcome.append('cancelled'))
    task.cancel()
    qtbot.waitUntil(lambda: bool(outcome), timeout=5000)

    assert outcome == ['cancelled']


def test_tasks_finish_even_when_the_caller_keeps_no_reference(qtbot):
    # Bug 4: worker threads were garbage collected while still running.
    results = []
    for i in range(20):
        run_task(lambda ctx, i=i: (time.sleep(0.05), i)[1], on_result=results.append)
    gc.collect()

    qtbot.waitUntil(lambda: len(results) == 20, timeout=10000)

    assert sorted(results) == list(range(20))
