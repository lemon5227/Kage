from core.background_lane import BackgroundLane
from core.job_types import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
)


def test_submit_creates_queued_job():
    lane = BackgroundLane()

    job = lane.submit(task_type="desktop_cleanup", input_text="整理桌面")

    assert job["task_type"] == "desktop_cleanup"
    assert job["input_text"] == "整理桌面"
    assert job["status"] == JOB_STATUS_QUEUED


def test_claim_next_marks_job_running():
    lane = BackgroundLane()
    queued = lane.submit(task_type="search", input_text="找资料")

    claimed = lane.claim_next()

    assert claimed["job_id"] == queued["job_id"]
    assert claimed["status"] == JOB_STATUS_RUNNING


def test_complete_marks_result():
    lane = BackgroundLane()
    queued = lane.submit(task_type="search", input_text="找资料")
    lane.claim_next()

    finished = lane.complete(queued["job_id"], {"summary": "done"})

    assert finished["status"] == JOB_STATUS_COMPLETED
    assert finished["result"] == {"summary": "done"}


def test_cancel_removes_queued_job():
    lane = BackgroundLane()
    queued = lane.submit(task_type="cleanup", input_text="整理下载目录")

    cancelled = lane.cancel(queued["job_id"])
    next_job = lane.claim_next()

    assert cancelled["status"] == JOB_STATUS_CANCELLED
    assert next_job is None
