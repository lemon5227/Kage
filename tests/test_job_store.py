from core.job_store import InMemoryJobStore


def test_create_and_get_job():
    store = InMemoryJobStore()

    created = store.create("j1", {"status": "queued", "kind": "download"})
    fetched = store.get("j1")

    assert created["job_id"] == "j1"
    assert fetched == {"job_id": "j1", "status": "queued", "kind": "download"}


def test_update_returns_copied_record():
    store = InMemoryJobStore()
    store.create("j1", {"status": "queued"})

    updated = store.update("j1", {"status": "running", "progress": 10})

    assert updated == {"job_id": "j1", "status": "running", "progress": 10}
    updated["status"] = "corrupted"
    assert store.get("j1")["status"] == "running"


def test_find_first_skips_bad_predicates():
    store = InMemoryJobStore()
    store.create("j1", {"status": "queued"})
    store.create("j2", {"status": "running"})

    found = store.find_first(
        lambda record: (_ for _ in ()).throw(ValueError("boom")) if record["job_id"] == "j1" else record["status"] == "running"
    )

    assert found["job_id"] == "j2"


def test_list_returns_copies():
    store = InMemoryJobStore()
    store.create("j1", {"status": "queued"})

    listed = store.list()
    listed[0]["status"] = "mutated"

    assert store.get("j1")["status"] == "queued"
