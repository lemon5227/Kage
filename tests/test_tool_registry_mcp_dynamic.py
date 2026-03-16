import json
import os


def test_register_mcp_dynamic_aliases_from_config(tmp_path):
    from core.tool_registry import create_default_registry

    cfg = {
        "tool_map": {
            "fetch_content": "ddg-search",
            "lookup": "ddg-search",
        }
    }
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    old = os.environ.get("KAGE_MCP_CFG")
    os.environ["KAGE_MCP_CFG"] = str(p)
    try:
        reg = create_default_registry(memory_system=None)
    finally:
        if old is None:
            os.environ.pop("KAGE_MCP_CFG", None)
        else:
            os.environ["KAGE_MCP_CFG"] = old

    names = set(reg.get_tool_names())
    assert "fetch_content" in names
    assert "lookup" in names

    schemas = reg.get_all_schemas()
    schema_names = {
        str((s.get("function") or {}).get("name") or "")
        for s in schemas
        if isinstance(s, dict)
    }
    assert "fetch_content" in schema_names
    assert "lookup" in schema_names
