"""Bounded research task executor, implemented independently with stdlib.

CFAR uses one worker and one admitted task. Tasks from one workspace serialize;
wall deadlines cover both executor queuing and the per-workspace lock wait.
This is not a reproduction of the platform's multi-workspace fairness service.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic


class RunQueueExpired(RuntimeError):
    pass


class WorkspaceRunScheduler:
    def __init__(self, *, max_workers=2, max_pending_per_workspace=4, queue_timeout=300):
        if min(max_workers, max_pending_per_workspace, queue_timeout) <= 0:
            raise ValueError("Scheduler limits must be positive")
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="wafer-research")
        self.guard = Lock()
        self.counts, self.locks = {}, {}
        self.limit, self.timeout, self.closed = max_pending_per_workspace, queue_timeout, False

    def submit(self, workspace_id, execute):
        with self.guard:
            if self.closed:
                raise RuntimeError("Run scheduler is closed")
            if self.counts.get(workspace_id, 0) >= self.limit:
                raise RuntimeError("Workspace scheduler capacity exceeded")
            self.counts[workspace_id] = self.counts.get(workspace_id, 0) + 1
            serial = self.locks.setdefault(workspace_id, Lock())
            deadline = monotonic() + self.timeout
        def run():
            remaining = deadline - monotonic()
            if remaining <= 0 or not serial.acquire(timeout=remaining):
                raise RunQueueExpired("Run expired before execution")
            try:
                if monotonic() >= deadline:
                    raise RunQueueExpired("Run expired before execution")
                return execute()
            finally:
                serial.release()
        def release(_):
            with self.guard:
                self.counts[workspace_id] -= 1
        try:
            future = self.pool.submit(run)
        except Exception:
            release(None)
            raise
        future.add_done_callback(release)
        return future

    def shutdown(self):
        with self.guard:
            self.closed = True
        self.pool.shutdown(wait=True, cancel_futures=True)
