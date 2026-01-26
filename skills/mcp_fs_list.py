# MCP 文件系统: 列目录
import json
import os
import subprocess

TRIGGERS = ["列目录", "查看目录", "目录内容", "列出目录"]

SKILL_INFO = {
    "name": "mcp_fs_list",
    "description": "通过 MCP 列出目录内容",
    "triggers": TRIGGERS,
    "action": "mcp_fs_list",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录路径"}
        }
    }
}


def execute(params: str) -> str:
    payload = _parse_payload(params)
    if payload is None:
        return "参数解析失败"

    path = payload.get("path") or _extract_path(params)
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = path or root_dir

    command = _load_mcp_command()
    if not command:
        return "未配置 MCP Server 命令"

    try:
        result = _call_mcp_tool(command, "list_directory", {"path": path})
    except Exception as e:
        return f"MCP 调用失败: {e}"

    return result


def _extract_path(text: str) -> str:
    if not text:
        return ""
    for trigger in TRIGGERS:
        text = text.replace(trigger, "")
    return text.strip(" :：\n\t")


def _parse_payload(params: str):
    if params is None:
        return {}
    if isinstance(params, dict):
        return params
    text = params.strip() if isinstance(params, str) else ""
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


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
