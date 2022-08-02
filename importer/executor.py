from concurrent.futures import Executor, Future
import logging
import random
import string
import threading
import time

import contextlib
from typing import Iterable, Dict, List, Any, Callable, Tuple, Type
from tqdm import tqdm
import sys

import concurrent.futures as concurrent
from django.conf import settings
import django_q.tasks as djangoq


logger = logging.getLogger(__name__)


def run(
    executor_cls: Type[Executor],
    executor_args: Dict,
    cb: Callable,
    it: Iterable,
    *args: List[Any],
    **kwargs: Dict[str, Any],
) -> Tuple[int, int]:
    if sys.stdout.isatty() and not settings.TESTING:
        pbar = tqdm(total=len(it))
    else:
        pbar = contextlib.nullcontext()

    with pbar as progress:
        with executor_cls(**executor_args) as pool:

            def done(future: Future):
                if future.exception():
                    logger.exception(future.exception())

                progress.update()

            futures: List[concurrent.Future] = []

            for i in it:
                future = pool.submit(cb, i, *args, **kwargs)
                future.add_done_callback(done)
                futures.append(future)

    failed = 0
    succeeded = 0
    for future in futures:
        try:
            future.result()
            succeeded += 1
        except Exception:
            failed += 1

    return failed, succeeded


class SingleThreadExecutor(concurrent.Executor):
    def __init__(self, *args, **kwargs):
        super().__init__()

    def submit(self, fn, /, *args, **kwargs):  # noqa E225
        future = Future()
        future.set_running_or_notify_cancel()

        try:
            result = fn(*args, **kwargs)
            future.set_result(result)
        except Exception as e:
            future.set_exception(e)

        return future


class WorkerPoolExecutor(concurrent.Executor):
    def __init__(self, *args, **kwargs):
        self.group_id = "".join(random.choice(string.ascii_lowercase) for i in range(8))
        self.futures: Dict[str, Future] = {}
        self.poll_interval = 0.2

        self.exit = False

        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)

        self.thread = threading.Thread(target=self._poll)
        self.thread.start()

    def _poll(self):
        while not self.exit:
            tasks = djangoq.fetch_group(self.group_id, wait=self.poll_interval * 1e3)
            if tasks is None or len(tasks) <= 0:
                continue

            for task in tasks:
                with self.condition:
                    if task.id not in self.futures:
                        continue

                    future = self.futures[task.id]

                    if task.success:
                        future.set_result(task.result)
                    else:
                        future.set_exception(Exception(task.result))

                    del self.futures[task.id]
                    self.condition.notify_all()

            time.sleep(self.poll_interval)

    def shutdown(self, wait=True):
        with self.condition:
            while len(self.futures) > 0:
                self.condition.wait()

        self.exit = True
        self.thread.join()

        djangoq.delete_group(self.group_id)

    def submit(self, fn, /, *args, **kwargs):  # noqa E225
        if self.exit:
            raise RuntimeError()

        future = Future()
        future.set_running_or_notify_cancel()

        try:
            task_id = djangoq.async_task(
                fn, group=self.group_id, ack_failure=True, *args, **kwargs
            )

            with self.condition:
                self.futures[task_id] = future
                self.condition.notify_all()

        except Exception as e:
            future.set_exception(e)

        return future
