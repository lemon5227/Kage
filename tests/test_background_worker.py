import asyncio

from core.background_lane import BackgroundLane
from core.background_worker import BackgroundWorker


def test_background_worker_processes_completed_job():
    lane = BackgroundLane()
    events = []

    async def processor(job):
        return {"echo": job["input_text"]}

    async def on_event(event, job):
        events.append((event, job["status"]))

    lane.submit(task_type="search", input_text="找资料")
    worker = BackgroundWorker(lane=lane, processor=processor, on_event=on_event)

    processed = asyncio.run(worker.process_next())
    jobs = lane.list()

    assert processed is True
    assert jobs[0]["status"] == "completed"
    assert jobs[0]["result"] == {"echo": "找资料"}
    assert events == [("started", "running"), ("completed", "completed")]


def test_background_worker_processes_failed_job():
    lane = BackgroundLane()
    events = []

    async def processor(job):
        raise RuntimeError("boom")

    async def on_event(event, job):
        events.append((event, job["status"], job.get("error")))

    lane.submit(task_type="cleanup", input_text="整理桌面")
    worker = BackgroundWorker(lane=lane, processor=processor, on_event=on_event)

    processed = asyncio.run(worker.process_next())
    jobs = lane.list()

    assert processed is True
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["error"] == "boom"
    assert events == [("started", "running", None), ("failed", "failed", "boom")]


def test_cancelled_job_cannot_be_overwritten_by_late_processor_return():
    lane = BackgroundLane()
    entered = asyncio.Event()
    release = asyncio.Event()
    events = []

    async def processor(job):
        entered.set()
        await release.wait()
        return {'late': True}

    async def scenario():
        job = lane.submit(task_type='browser_experiment', input_text='test')
        async def on_event(event, _job):
            events.append(event)
        worker = BackgroundWorker(lane=lane, processor=processor, on_event=on_event)
        processing = asyncio.create_task(worker.process_next())
        await entered.wait()
        lane.cancel(job['job_id'])
        release.set()
        await processing
        assert lane.get(job['job_id'])['status'] == 'cancelled'
        assert lane.get(job['job_id'])['result'] is None
        assert events == ['started']
    asyncio.run(scenario())
