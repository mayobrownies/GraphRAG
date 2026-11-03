"""
A per-document lock and cancel token
One ingestion job runs per document, and a job for a document that was deleted or replaced must not write to Neo4j or Qdrant
start() cancels the document's current job and runs the new one only after the old one has fully stopped,
so the new job's cleanup can't race the old job's last writes
Cancelling is cooperative: the job calls job.check() before each write step and stops with JobCancelled
Jobs live in memory, so this only works with one server process (uvicorn without --workers)
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.core.errors import JobCancelled

logger = logging.getLogger(__name__)


@dataclass
class Job:
    doc_id: str
    task: asyncio.Task | None = None
    _cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    def check(self) -> None:
        # Call before every write step
        if self.cancelled:
            raise JobCancelled(self.doc_id)


Work = Callable[[Job], Awaitable[None]]


@dataclass
class JobManager:
    shutdown_timeout: float = 30.0
    # The current job per document
    _jobs: dict[str, Job] = field(default_factory=dict)
    # Every unfinished task, including replaced jobs that are still stopping
    # asyncio only keeps weak references to tasks, so this also stops them being garbage-collected mid-run
    _tasks: set[asyncio.Task] = field(default_factory=set)

    def start(self, doc_id: str, work: Work) -> Job:
        # Not async on purpose: nothing else can run between reading the current job and registering the new one
        previous = self._jobs.get(doc_id)
        if previous:
            previous.cancel()
        job = Job(doc_id)
        job.task = asyncio.create_task(self._run(job, previous, work))
        self._tasks.add(job.task)
        job.task.add_done_callback(self._tasks.discard)
        self._jobs[doc_id] = job
        return job

    async def cancel(self, doc_id: str) -> None:
        # Returns only after the job has stopped, so the caller can then delete the document's data safely
        job = self._jobs.get(doc_id)
        if job:
            job.cancel()
            await asyncio.wait({job.task})

    async def shutdown(self) -> None:
        # Ask every job to stop, then force any that are still running after the timeout
        tasks = set(self._tasks)
        if not tasks:
            return
        for job in self._jobs.values():
            job.cancel()
        _, pending = await asyncio.wait(tasks, timeout=self.shutdown_timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending)

    async def _run(self, job: Job, previous: Job | None, work: Work) -> None:
        try:
            if previous:
                # The lock: wait until the old job has stopped; wait() doesn't re-raise its errors (its own _run logged them)
                await asyncio.wait({previous.task})
            job.check()
            await work(job)
        except JobCancelled:
            logger.info("Job for document %s was cancelled", job.doc_id)
        except Exception:
            # Ingestion marks the document 'failed' itself; this only logs what escaped it
            logger.exception("Job for document %s failed", job.doc_id)
        finally:
            # A newer job may have replaced this one; leave that entry alone
            if self._jobs.get(job.doc_id) is job:
                del self._jobs[job.doc_id]
