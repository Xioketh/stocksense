import pytest

from app.agent.thread_lock import thread_lock
from app.errors import ThreadBusy


def test_second_run_on_the_same_thread_is_refused(pool):
    with thread_lock(pool, "thread-a"):
        with pytest.raises(ThreadBusy):
            with thread_lock(pool, "thread-a"):
                pass


def test_other_threads_are_not_blocked(pool):
    with thread_lock(pool, "thread-a"):
        with thread_lock(pool, "thread-b"):
            pass


def test_lock_is_released_after_the_run_even_on_error(pool):
    with pytest.raises(RuntimeError):
        with thread_lock(pool, "thread-a"):
            raise RuntimeError("run failed")

    with thread_lock(pool, "thread-a"):  # free again
        pass
