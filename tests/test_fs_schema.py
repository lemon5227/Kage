from core.tool_registry import create_default_registry


def _get_tool_schema(reg, tool_name: str) -> dict:
    for s in reg.get_all_schemas():
        fn = s.get("function") or {}
        if fn.get("name") == tool_name:
            return s
    return {}


def test_fs_apply_schema_is_strict():
    reg = create_default_registry(memory_system=None)
    schema = _get_tool_schema(reg, "fs_apply")
    params = (schema.get("function") or {}).get("parameters") or {}
    ops = (params.get("properties") or {}).get("ops") or {}
    items = ops.get("items") or {}
    assert "oneOf" in items
    variants = items.get("oneOf")
    assert isinstance(variants, list) and len(variants) >= 3
    # Ensure move op requires src/dest_dir
    move = [v for v in variants if (v.get("properties") or {}).get("op", {}).get("const") == "move"]
    assert move
    assert set(move[0].get("required") or []) == {"op", "src", "dest_dir"}


def test_fs_preview_schema_is_strict():
    reg = create_default_registry(memory_system=None)
    schema = _get_tool_schema(reg, "fs_preview")
    params = (schema.get("function") or {}).get("parameters") or {}
    ops = (params.get("properties") or {}).get("ops") or {}
    items = ops.get("items") or {}
    assert "oneOf" in items
