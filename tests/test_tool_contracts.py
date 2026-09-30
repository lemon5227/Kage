"""Meta-tests over the whole tool registry: the schema the model sees must match the
implementation that will receive the call.

Rationale: a tool schema *is* the agent's action space. If a schema advertises a
parameter the handler does not accept, the model's call raises ``TypeError`` and the
capability silently disappears (the executor only records a failed ToolResult). Two
real bugs of exactly this kind shipped:

  * ``search`` advertised ``source``/``filters`` while the handler took
    ``(query, max_results, strategy, sort)`` → ``source="youtube"`` raised TypeError;
  * ``skills_save_local`` advertised ``name/description/body/target_dir/overwrite``
    while the handler took ``(skill_name, content, workspace_dir)`` → every
    model-issued call raised TypeError, breaking the agent's skill-autosave path.

Each test below checks one invariant across *all* tools (including tools added later)
and reports every offending tool name, so there is no per-tool test file to maintain
and no parametrization padding.
"""

from __future__ import annotations

import inspect
import json
import re
import tempfile
from pathlib import Path

from core.tool_registry import create_default_registry

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # function-calling name charset
MAX_DESCRIPTION_CHARS = 200  # descriptions are injected into every request

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = create_default_registry()
    return _REGISTRY


def _entries() -> list[tuple[str, dict, object, str]]:
    """(name, parameters_schema, handler, description) for every registered tool."""
    registry = _registry()
    entries = []
    for schema in registry.get_all_schemas():
        function = schema["function"]
        name = function["name"]
        entries.append((name, function.get("parameters") or {},
                        registry.get_handler(name), function.get("description", "")))
    return entries


def _params_by_name() -> dict[str, dict]:
    return {name: params for name, params, _, _ in _entries()}


def test_registry_has_a_sane_number_of_tools():
    names = [name for name, _, _, _ in _entries()]
    assert len(names) >= 20, "registry unexpectedly small; did registration break?"
    assert len(names) == len(set(names)), f"duplicate tool names: {names}"


def test_tool_names_are_valid_function_names():
    bad = [name for name, _, _, _ in _entries() if not NAME_RE.match(name)]
    assert bad == [], f"names unusable for function calling: {bad}"


def test_parameter_schemas_are_well_formed():
    problems = []
    for name, params, _, _ in _entries():
        if params.get("type") != "object":
            problems.append(f"{name}: parameters.type={params.get('type')!r}")
        properties = params.get("properties")
        if not isinstance(properties, dict):
            problems.append(f"{name}: 缺少 properties")
            continue
        undeclared = set(params.get("required") or []) - set(properties)
        if undeclared:
            problems.append(f"{name}: required 未在 properties 中声明 {sorted(undeclared)}")
    assert problems == [], "; ".join(problems)


def test_descriptions_are_present_and_bounded():
    problems = []
    for name, _, _, description in _entries():
        text = str(description or "").strip()
        if not text:
            problems.append(f"{name}: 空 description")
        elif len(text) > MAX_DESCRIPTION_CHARS:
            problems.append(f"{name}: description {len(text)} 字符 > {MAX_DESCRIPTION_CHARS}")
    assert problems == [], "description 会进入每次请求，必须简短: " + "; ".join(problems)


def test_handler_accepts_every_declared_parameter():
    """Core guarantee: schema properties ⊆ handler parameters."""
    problems = []
    for name, params, handler, _ in _entries():
        if not callable(handler):
            problems.append(f"{name}: handler 不可调用")
            continue
        try:
            signature = inspect.signature(handler)
        except (TypeError, ValueError):
            continue  # not introspectable (C builtins)
        arguments = signature.parameters
        if any(p.kind is p.VAR_KEYWORD for p in arguments.values()):
            continue
        accepted = {n for n, p in arguments.items()
                    if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
        unaccepted = set(params.get("properties") or {}) - accepted
        if unaccepted:
            problems.append(f"{name}: 声明了实现收不到的参数 {sorted(unaccepted)} "
                            f"(签名 {signature}) → 模型调用必 TypeError")
    assert problems == [], "; ".join(problems)


def test_handler_required_params_are_advertised_as_required():
    """A handler parameter without a default must be `required` in the schema, otherwise
    the model may legally omit it and the call raises TypeError."""
    problems = []
    for name, params, handler, _ in _entries():
        try:
            signature = inspect.signature(handler)
        except (TypeError, ValueError):
            continue
        arguments = signature.parameters
        if any(p.kind is p.VAR_KEYWORD for p in arguments.values()):
            continue
        handler_required = {
            n for n, p in arguments.items()
            if p.default is p.empty and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        }
        missing = handler_required - set(params.get("required") or [])
        if missing:
            problems.append(f"{name}: 实现必填但 schema 未声明 {sorted(missing)} "
                            f"(schema required={sorted(params.get('required') or [])})")
    assert problems == [], "; ".join(problems)


# ---------------------------------------------------------------------------
# Explicit regression pins for the two bugs this file was written for
# ---------------------------------------------------------------------------
def test_search_source_is_wired_and_filters_removed():
    import core.tools.web_ops as web_ops

    registry = _registry()
    params = _params_by_name()["search"]
    assert "filters" not in params["properties"], "schema 仍宣传不存在的 filters"
    assert set(params["properties"]) >= {"query", "source", "sort", "max_results"}
    assert params["properties"]["source"].get("enum"), "source 应有 enum 约束取值"

    seen: list[tuple] = []
    original = web_ops._search_provider_youtube
    web_ops._search_provider_youtube = lambda q, sort, limit: (
        seen.append((q, sort, limit)) or '{"success": true, "results": []}')
    try:
        out = json.loads(registry.get_handler("search")(
            query="小猫", source="youtube", max_results=3))
    finally:
        web_ops._search_provider_youtube = original

    assert seen == [("小猫", "relevance", 3)], out
    assert out["success"] is True

    # the legacy internal alias used by smart_search must keep working
    assert "strategy" in inspect.signature(registry.get_handler("search")).parameters

    invalid = json.loads(registry.get_handler("search")(query="x", source="douyin"))
    assert invalid["success"] is False
    assert invalid["error"] == "InvalidArgument"


def test_skills_save_local_accepts_model_facing_arguments():
    registry = _registry()
    with tempfile.TemporaryDirectory() as tmp:
        out = json.loads(registry.get_handler("skills_save_local")(
            name="my-skill", description="演示技能", body="step 1", target_dir=tmp))
        assert out["success"] is True, out
        written = Path(out["path"])
        assert written.name == "my-skill.md"
        assert written.parent == Path(tmp).resolve()
        assert "演示技能" in written.read_text(encoding="utf-8")

        # a second write without overwrite must be refused, not silently replaced
        again = json.loads(registry.get_handler("skills_save_local")(
            name="my-skill", description="演示技能", body="step 2", target_dir=tmp))
        assert again["success"] is False and again["error"] == "AlreadyExists"

        # path traversal must not escape target_dir
        evil = json.loads(registry.get_handler("skills_save_local")(
            name="../../evil", description="x", target_dir=tmp))
        assert evil["success"] is False and evil["error"] == "InvalidArgument"
