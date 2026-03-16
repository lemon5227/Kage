from __future__ import annotations

from core.local_model_runtime import LocalModelRuntime


class DummyProc:
    def __init__(self, cmd, stdout=None, stderr=None, start_new_session=None):
        self.cmd = list(cmd)
        self.stdout = stdout
        self.stderr = stderr
        self.start_new_session = start_new_session
        self.pid = 4242
        self._poll = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._poll

    def terminate(self):
        self.terminated = True
        self._poll = 0

    def wait(self, timeout=None):
        self._poll = 0
        return 0

    def kill(self):
        self.killed = True
        self._poll = -9


def test_resolve_model_from_managed_metadata(tmp_path):
    model_path = tmp_path / "model.gguf"
    model_path.write_text("x", encoding="utf-8")
    runtime = LocalModelRuntime(
        user_dir=str(tmp_path),
        managed_model_getter=lambda model_id: {"path": str(model_path)} if model_id == "m1" else None,
    )

    model_id, resolved_path, err = runtime.resolve_model({"model_id": "m1"})

    assert err is None
    assert model_id == "m1"
    assert resolved_path == str(model_path)


def test_start_builds_runtime_state_and_command(tmp_path):
    model_path = tmp_path / "model.gguf"
    model_path.write_text("x", encoding="utf-8")
    created: dict[str, DummyProc] = {}

    def fake_popen(cmd, stdout=None, stderr=None, start_new_session=None):
        proc = DummyProc(cmd, stdout=stdout, stderr=stderr, start_new_session=start_new_session)
        created["proc"] = proc
        return proc

    runtime = LocalModelRuntime(
        user_dir=str(tmp_path),
        managed_model_getter=lambda model_id: {"path": str(model_path)} if model_id == "m1" else None,
        which=lambda name: "/usr/local/bin/llama-server",
        popen_factory=fake_popen,
    )

    result = runtime.start({"model_id": "m1", "port": 9001, "ctx": 4096, "ngl": 33})

    assert result.ok is True
    assert result.payload["status"] == "running"
    assert result.payload["pid"] == 4242
    assert result.payload["port"] == 9001
    assert result.payload["model_id"] == "m1"
    assert result.payload["cmd"][0] == "/usr/local/bin/llama-server"
    assert "-m" in result.payload["cmd"]
    assert str(model_path) in result.payload["cmd"]
    assert "--reasoning" in result.payload["cmd"]
    assert "off" in result.payload["cmd"]
    assert created["proc"].start_new_session is True


def test_start_requires_force_restart_when_runtime_busy(tmp_path):
    model_a = tmp_path / "a.gguf"
    model_b = tmp_path / "b.gguf"
    model_a.write_text("a", encoding="utf-8")
    model_b.write_text("b", encoding="utf-8")

    created: list[DummyProc] = []

    def fake_popen(cmd, stdout=None, stderr=None, start_new_session=None):
        proc = DummyProc(cmd, stdout=stdout, stderr=stderr, start_new_session=start_new_session)
        created.append(proc)
        return proc

    runtime = LocalModelRuntime(
        user_dir=str(tmp_path),
        managed_model_getter=lambda model_id: {"path": str(model_a)} if model_id == "m1" else {"path": str(model_b)},
        which=lambda name: "/usr/local/bin/llama-server",
        popen_factory=fake_popen,
    )

    first = runtime.start({"model_id": "m1"})
    second = runtime.start({"model_id": "m2"})

    assert first.ok is True
    assert second.ok is False
    assert "force_restart" in second.payload["error"]
    assert len(created) == 1


def test_stop_terminates_running_process(tmp_path):
    model_path = tmp_path / "model.gguf"
    model_path.write_text("x", encoding="utf-8")
    holder: dict[str, DummyProc] = {}

    def fake_popen(cmd, stdout=None, stderr=None, start_new_session=None):
        proc = DummyProc(cmd, stdout=stdout, stderr=stderr, start_new_session=start_new_session)
        holder["proc"] = proc
        return proc

    runtime = LocalModelRuntime(
        user_dir=str(tmp_path),
        managed_model_getter=lambda model_id: {"path": str(model_path)},
        which=lambda name: "/usr/local/bin/llama-server",
        popen_factory=fake_popen,
    )

    runtime.start({"model_id": "m1"})
    stopped = runtime.stop()

    assert stopped["status"] == "stopped"
    assert stopped["pid"] is None
    assert holder["proc"].terminated is True
