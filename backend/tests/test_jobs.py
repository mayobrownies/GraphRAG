import asyncio

from app.services.jobs import Job, JobManager


async def let_tasks_run():
    # One yield lets each started task run up to its first await; this is not a timing wait
    await asyncio.sleep(0)


async def test_job_runs_and_is_cleaned_up():
    jobs = JobManager()
    ran = []

    async def work(job: Job):
        ran.append(job.doc_id)

    job = jobs.start("doc-a", work)
    await job.task
    assert ran == ["doc-a"]
    assert jobs._jobs == {} and jobs._tasks == set()


async def test_new_job_waits_for_old_job():
    jobs = JobManager()
    log = []
    gate = asyncio.Event()

    async def old(job: Job):
        log.append("old start")
        await gate.wait()
        job.check()
        log.append("old wrote")

    async def new(job: Job):
        log.append("new start")

    first = jobs.start("doc-a", old)
    await let_tasks_run()
    second = jobs.start("doc-a", new)
    await let_tasks_run()

    assert first.cancelled
    # The new job is still waiting for the old one to stop
    assert log == ["old start"]

    gate.set()
    await second.task
    assert log == ["old start", "new start"]
    assert jobs._jobs == {}


async def test_old_job_finishing_keeps_new_job_registered():
    jobs = JobManager()
    old_gate, new_gate = asyncio.Event(), asyncio.Event()

    async def old(job: Job):
        await old_gate.wait()

    async def new(job: Job):
        await new_gate.wait()

    first = jobs.start("doc-a", old)
    await let_tasks_run()
    second = jobs.start("doc-a", new)

    old_gate.set()
    await first.task
    await let_tasks_run()
    # The old job's cleanup must not remove the job that replaced it, or cancel() could no longer find it
    assert jobs._jobs["doc-a"] is second

    new_gate.set()
    await second.task
    assert jobs._jobs == {}


async def test_cancel_returns_after_job_stops():
    jobs = JobManager()
    gate = asyncio.Event()

    async def work(job: Job):
        await gate.wait()
        job.check()

    jobs.start("doc-a", work)
    await let_tasks_run()
    cancelling = asyncio.create_task(jobs.cancel("doc-a"))
    await let_tasks_run()
    assert not cancelling.done()

    gate.set()
    await cancelling
    assert jobs._jobs == {} and jobs._tasks == set()


async def test_cancel_unknown_doc_does_nothing():
    await JobManager().cancel("missing")


async def test_failed_work_is_logged_and_next_job_runs(caplog):
    jobs = JobManager()
    ran = []

    async def broken(job: Job):
        raise RuntimeError("boom")

    async def work(job: Job):
        ran.append(job.doc_id)

    await jobs.start("doc-a", broken).task
    assert "Job for document doc-a failed" in caplog.text

    await jobs.start("doc-a", work).task
    assert ran == ["doc-a"]


async def test_only_latest_of_three_jobs_runs():
    jobs = JobManager()
    ran = []
    gate = asyncio.Event()

    async def first(job: Job):
        await gate.wait()

    def work(name: str):
        async def run(job: Job):
            ran.append(name)
        return run

    jobs.start("doc-a", first)
    await let_tasks_run()
    jobs.start("doc-a", work("second"))
    third = jobs.start("doc-a", work("third"))

    gate.set()
    await third.task
    assert ran == ["third"]


async def test_shutdown_stops_polite_and_stuck_jobs():
    jobs = JobManager(shutdown_timeout=0.01)
    never = asyncio.Event()

    async def polite(job: Job):
        while True:
            job.check()
            await asyncio.sleep(0)

    async def stuck(job: Job):
        await never.wait()

    polite_job = jobs.start("doc-a", polite)
    stuck_job = jobs.start("doc-b", stuck)
    await let_tasks_run()

    await jobs.shutdown()
    assert polite_job.task.done() and not polite_job.task.cancelled()
    assert stuck_job.task.cancelled()
    assert jobs._jobs == {} and jobs._tasks == set()
