# MCP 客户端技能 (stdio)
import json
import os
import subprocess

TRIGGERS = ["mcp", "MCP", "用mcp", "调用mcp"]

SKILL_INFO = {
    "name": "mcp_client",
    "description": "通过 MCP Server 调用外部工具",
    "triggers": TRIGGERS,
    "action": "mcp_client",
    "parameters": {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "description": "MCP 工具名"},
            "arguments": {"type": "object", "description": "工具参数"}
        },
        "required": ["tool"]
    }
}


def execute(params: str) -> str:
    payload = _parse_payload(params)
    if payload is None:
        return "参数解析失败"

    command = _load_mcp_command()
    if not command:
        return "未配置 MCP Server 命令"

    tool_name = payload.get("tool")
    arguments = payload.get("arguments") or {}

    if not tool_name:
        return "缺少 tool 参数"

    try:
        return _call_mcp_tool(command, tool_name, arguments)
    except Exception as e:
        return f"MCP 调用失败: {e}"


def _parse_payload(params: str):
    if params is None:
        return {}
    if isinstance(params, dict):
        return params
    text = params.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"tool": text, "arguments": {}}


def _load_mcp_command():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(root_dir, "config", "mcp.json")
    env_cmd = os.environ.get("KAGE_MCP_COMMAND")

    if env_cmd:
        return env_cmd.split()

    if not os.path.exists(config_path):
        return None

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    cmd = config.get("command")
    if isinstance(cmd, str):
        return cmd.split()
    if isinstance(cmd, list):
        return cmd
    return None


def _call_mcp_tool(command, tool_name: str, arguments: dict) -> str:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def send(message):
        process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def read_response(expect_id):
        while True:
            line = process.stdout.readline()
            if not line:
                break
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("id") == expect_id:
                return data
        return None

    send({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "kage", "version": "0.1"},
        },
    })
    _ = read_response(1)

    send({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })
    result = read_response(2)

    if result is None:
        raise RuntimeError("无响应")

    if "error" in result:
        raise RuntimeError(result["error"].get("message", "未知错误"))

    payload = result.get("result")
    if isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False)
    return str(payload)
