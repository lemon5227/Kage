"""Invariants for which tool schemas reach the model.

Regression context: tool pruning used to be hardcoded name literals inside
``PromptBuilder._select_tool_names``. ``search`` was pruned from every route while the
behaviour rule told the model to use it, and an audit found six registered tools
(including ``memory_search``) unreachable on every route. These tests make that class
of defect impossible: the policy must classify every registered tool, every tool must
be reachable by some (route, intent), and anything unclassified is fail-open.
"""

from __future__ import annotations

from core import tool_visibility as tv
from core.prompt_builder import PromptBuilder
from core.tool_registry import ToolRegistry, create_default_registry

# One representative utterance per capability trigger; used to prove reachability.
PROBE_UTTERANCES = (
    "搜索一下最新新闻",          # web
    "打开这个网页",              # open/browse
    "把这个文件整理一下",         # files
    "调高音量",                  # system
    "截个图",                    # screenshot
    "把刚才的流程存成技能模板",     # skills
    "我们随便聊聊",              # plain chat
    "查一下汇率",                # info
    "帮我整理并把结果写到文件里",   # command that also needs search
)


class _Identity:
    def load_soul(self) -> str:
        return ""

    def load_user(self) -> str:
        return ""


def _builder(registry=None) -> PromptBuilder:
    return PromptBuilder(_Identity(), None, registry or create_default_registry(),
                         memory_cfg={"recall_enabled": False}, prune_tools=True)


def _registered() -> set[str]:
    return set(create_default_registry().get_tool_names())


def _reachable_names() -> set[str]:
    """Names reachable through the *real* router (classify_route), not an invented route."""
    builder = _builder()
    registered = _registered()
    reachable: set[str] = set()
    for text in PROBE_UTTERANCES:
        route = builder.classify_route(text)
        reachable |= set(tv.select(text, route, registered).names)
    return reachable


# ---------------------------------------------------------------------------
# Policy completeness / reachability
# ---------------------------------------------------------------------------
def test_every_registered_tool_is_classified_by_the_policy():
    unclassified = _registered() - set(tv.CLASSIFIED)
    assert unclassified == set(), (
        "these tools are not classified by core.tool_visibility, so their visibility is "
        f"accidental: {sorted(unclassified)}"
    )


def test_every_registered_tool_is_reachable_on_some_route():
    unreachable = _registered() - _reachable_names()
    assert unreachable == set(), (
        "registered tools the model can never see (the exact defect this policy prevents): "
        f"{sorted(unreachable)}"
    )


def test_unclassified_tools_are_fail_open_not_hidden():
    """A registered-but-unclassified tool must still be offered (and reported)."""
    decision = tv.select("随便聊聊", "chat", {"totally_new_tool", "search"})
    assert "totally_new_tool" in decision.names, "unclassified tool was silently hidden"
    assert decision.unclassified == ("totally_new_tool",)


def test_classified_names_are_registered_or_declared_alias_slots():
    """The policy must not classify tools that do not exist (phantom names), except the
    documented MCP alias slots that config/mcp.json may register at runtime."""
    phantom = set(tv.CLASSIFIED) - _registered() - set(tv.ALIAS_SLOTS) - set(tv.EXPERIMENT_SLOTS)
    assert phantom == set(), f"policy references unregistered tools: {sorted(phantom)}"


def test_select_works_without_a_registry():
    decision = tv.select("随便聊聊", "chat", set())
    assert decision.unclassified == ()
    assert "search" in decision.names


def test_unclassified_tool_warns_once_not_every_request(caplog):
    """Fail-open must not spam the log on every single request."""
    import logging
    registry = ToolRegistry()
    from core.tool_registry import ToolDefinition
    registry.register(ToolDefinition(name="brand_new_capability", description="d",
                                     parameters={"type": "object", "properties": {}},
                                     handler=lambda **kw: "{}"))
    builder = _builder(registry)
    with caplog.at_level(logging.WARNING, logger="core.prompt_builder"):
        for _ in range(5):
            builder._select_tool_names("随便聊聊", route="chat")
    warnings = [r for r in caplog.records if "not classified" in r.message]
    assert len(warnings) == 1, f"expected one warning, got {len(warnings)}"


def test_prompt_builder_logs_unclassified_tools(caplog):
    import logging
    registry = ToolRegistry()
    from core.tool_registry import ToolDefinition
    registry.register(ToolDefinition(name="brand_new_capability", description="d",
                                     parameters={"type": "object", "properties": {}},
                                     handler=lambda **kw: "{}"))
    builder = _builder(registry)
    with caplog.at_level(logging.WARNING, logger="core.prompt_builder"):
        names = builder._select_tool_names("随便聊聊", route="chat")
    assert "brand_new_capability" in (names or [])
    assert any("not classified" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Prompt budget: the surface the model pays for on every request
# ---------------------------------------------------------------------------
def test_always_on_surface_stays_under_the_accuracy_cliff():
    # Published guidance: tool-selection accuracy degrades past ~30-50 tools, and a
    # tight surface is cheaper; keep the largest baseline well below the cliff.
    assert len(tv.BASE) <= 20, f"BASE grew to {len(tv.BASE)} tools"
    assert len(tv.CMD_BASE) <= 26, f"CMD_BASE grew to {len(tv.CMD_BASE)} tools"
    assert len(tv.INFO_DEFAULT) <= 8


# ---------------------------------------------------------------------------
# Route x tool matrix (the specific capabilities that were missing)
# ---------------------------------------------------------------------------
def _visible(text: str, route: str | None = None) -> set[str]:
    builder = _builder()
    route = route or builder.classify_route(text)
    return set(builder._select_tool_names(text, route=route) or [])


def test_search_is_visible_on_info_command_and_chat():
    assert "search" in _visible("搜索小猫视频")
    assert "search" in _visible("帮我查一下资料并整理成文件")
    assert "search" in _visible("我们随便聊聊")


def test_pure_info_lookup_stays_minimal_and_never_offers_a_browser():
    names = _visible("搜索小猫视频")
    assert names == set(tv.INFO_DEFAULT), f"info surface drifted: {sorted(names)}"
    assert not ({"open_url", "open_website", "open_app"} & names)


def test_memory_recall_is_visible_to_the_model():
    # the memory tool of a memory-evolution project used to be pruned everywhere
    assert "memory_search" in _visible("我们随便聊聊")
    assert "memory_search" in _visible("我之前说过什么")
    assert "memory_search" in _visible("查一下我之前提过的研究方向")


def test_info_skill_request_can_find_read_and_save_local_skills():
    assert {"find_skills", "skills_read", "skills_save_local"} <= _visible("搜索视频处理技能")


def test_candidate_skill_protocol_is_deliberately_visible_on_info_route():
    decision = tv.select("查找数据归一化方法", "info", {"skill_search", "skill_call"})
    assert {"skill_search", "skill_call"} <= set(decision.names)
    assert not decision.unclassified, "the E1 protocol should not depend on fail-open"


def test_local_skill_reuse_loop_is_visible_on_repeat_flows():
    # BEHAVIOR_RULE tells the model to save repeated workflows as skills; the tools
    # must be visible for exactly those requests.
    for text in ("这个流程再帮我做一次", "把刚才的步骤存成技能", "我们随便聊聊"):
        names = _visible(text)
        assert {"find_skills", "skills_read", "skills_save_local"} <= names, text


def test_remote_skill_install_only_appears_for_skill_intent():
    assert "skills_install" not in _visible("我们随便聊聊")
    assert "skills_install" in _visible("帮我搜索并安装一个技能")


def test_screenshot_only_appears_for_screenshot_intent():
    assert "take_screenshot" not in _visible("我们随便聊聊")
    assert "take_screenshot" in _visible("截个图")


def test_weather_request_never_gets_a_browser():
    names = _visible("明天天气怎么样")
    assert "open_url" not in names and "open_website" not in names
    assert "smart_search" in names


def test_command_route_can_search():
    # "查一下再整理成文件" used to route to command, where no search tool existed
    names = _visible("帮我查一下资料并整理成文件", route="command")
    assert "search" in names
    assert "fs_apply" in names


# ---------------------------------------------------------------------------
# End to end through the real PromptBuilder
# ---------------------------------------------------------------------------
def test_real_prompt_exposes_search_to_the_model():
    builder = _builder()
    _, tool_defs = builder.build("搜索小猫视频", history=[])
    names = {tool["function"]["name"] for tool in tool_defs}
    assert "search" in names


def test_real_prompt_exposes_skill_save_on_a_repeat_request():
    builder = _builder()
    _, tool_defs = builder.build("这个流程再帮我做一次", history=[])
    names = {tool["function"]["name"] for tool in tool_defs}
    assert "skills_save_local" in names


def test_pruning_disabled_when_input_is_empty():
    builder = _builder()
    assert builder._select_tool_names("") is None
