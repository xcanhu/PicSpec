import importlib.util
import io
import json
import sys
from pathlib import Path

from picspec import mcp
from picspec.cli import main


def _talk(*messages):
    out = io.StringIO()
    mcp.serve(io.StringIO("\n".join(json.dumps(m) for m in messages) + "\nnot json\n"), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_mcp_lists_and_calls_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--lang", "zh"]) == 0
    replies = _talk(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "picspec_compile", "arguments": {"prompt": "雨后的小巷", "skip": "t3"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "picspec_rules", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "picspec_compile", "arguments": {"prompt": "x", "skip": "nope"}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "picspec_compile", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 7, "method": "nope"},
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
         "params": {"name": "picspec_generate", "arguments": {"prompt": "x", "out": "o", "size": "64x96"}}},
    )
    by_id = {r["id"]: r for r in replies}
    assert by_id[1]["result"]["protocolVersion"] == "2025-03-26" and by_id[1]["result"]["serverInfo"]["name"] == "picspec"
    tools = by_id[2]["result"]["tools"]
    assert {t["name"] for t in tools} >= {"picspec_compile", "picspec_generate", "picspec_check", "picspec_learn"}
    assert all("argv" not in t and t["inputSchema"]["type"] == "object" for t in tools)
    compiled = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert compiled["prompt"].startswith("雨后的小巷") and not by_id[3]["result"]["isError"]
    assert "7 rules" in by_id[4]["result"]["content"][0]["text"]
    assert by_id[5]["result"]["isError"] and "no such rule: nope" in by_id[5]["result"]["content"][0]["text"]
    assert by_id[6]["result"]["isError"] and "prompt" in by_id[6]["result"]["content"][0]["text"]
    assert by_id[7]["error"]["code"] == -32601 and by_id[None]["error"]["code"] == -32700
    assert by_id[8]["result"]["isError"]  # no API key here: the error comes back as text, the server keeps running
    assert len(replies) == 9


def test_comfyui_prompt_node(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--lang", "en"]) == 0
    path = Path(__file__).resolve().parents[1] / "comfyui" / "__init__.py"
    spec = importlib.util.spec_from_file_location("picspec_comfyui", path)
    nodes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nodes)
    node = nodes.NODE_CLASS_MAPPINGS["PicSpecPrompt"]()
    assert set(node.INPUT_TYPES()["required"]) == {"prompt", "spec_path"}
    positive, negative = node.build("an alley after rain", str(tmp_path / "PICSPEC.md"), skip="t3")
    assert positive.startswith("an alley after rain") and "grain" in positive and "behind and to the side" not in positive
    assert isinstance(negative, str) and node.build("x", "")[0].startswith("x")  # finds PICSPEC.md by itself
