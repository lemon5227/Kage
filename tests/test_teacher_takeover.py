"""A task-level teacher continues real failed state; hidden answers stay outside prompts."""
import json
from pathlib import Path
from core.evolution.agent_provider import KageChainProvider
from core.evolution.takeover import TeacherTakeoverProvider
from core.model_provider import ModelResponse
from test_agentic_loop_multistep import SequenceModel, call


def test_teacher_reads_student_partial_state_and_corrects_same_workspace(tmp_path):
    task = {"task_id": "repair", "instruction": "Read input.json and double its value into out.json.",
            "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": 14}}
    (tmp_path / "input.json").write_text("7")
    student = KageChainProvider(SequenceModel([call("write_file", path="out.json", content="7"), ModelResponse(text="Done")]))
    model = SequenceModel([call("read_file", path="out.json"), call("write_file", path="out.json", content="14"), ModelResponse(text="Fixed")])
    teacher = KageChainProvider(model, provider_mode="cloud", model_label="teacher-fixture")
    provider = TeacherTakeoverProvider(student, teacher, task)
    result = provider.generate_step({"task_id": "repair", "instruction": task["instruction"]}, 1, [], tmp_path)
    assert (tmp_path / "out.json").read_text() == "14"
    assert result["chain"]["takeover"]["student_check"]["check_passed"] is False
    assert result["chain"]["takeover"]["teacher_check"]["check_passed"] is True
    assert [t["actor"] for t in result["tool_results"]] == ["student", "teacher", "teacher"]
    observed = next(m["content"] for m in model.messages[1] if m["role"] == "tool")
    assert json.loads(observed.split("] ", 1)[1])["content"] == "7"
    assert "scoring_criteria" not in json.dumps(model.messages)
    assert result["usage"]["api_calls"] == 5


def test_verified_student_never_purchases_teacher_calls(tmp_path):
    task = {"task_id": "ok", "instruction": "Save the result.", "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": 14}}
    student = KageChainProvider(SequenceModel([call("write_file", path="out.json", content="14"), ModelResponse(text="Done")]))
    teacher_model = SequenceModel([])
    provider = TeacherTakeoverProvider(student, KageChainProvider(teacher_model), task)
    result = provider.generate_step({"task_id": "ok", "instruction": task["instruction"]}, 1, [], tmp_path)
    assert result["chain"]["takeover"]["triggered"] is False
    assert teacher_model.messages == []
    assert result["usage"]["api_calls"] == 2


def test_failed_teacher_is_not_accepted_as_a_demonstration(tmp_path):
    task = {"task_id": "bad", "instruction": "Save the result.", "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": 14}}
    provider = TeacherTakeoverProvider(
        KageChainProvider(SequenceModel([ModelResponse(text="I cannot.")])),
        KageChainProvider(SequenceModel([ModelResponse(text="Done.")])), task)
    result = provider.generate_step(task, 1, [], tmp_path)
    assert result["chain"]["takeover"]["teacher_check"]["check_passed"] is False
    assert not (tmp_path / "out.json").exists()
