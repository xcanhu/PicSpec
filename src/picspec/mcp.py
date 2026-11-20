"""A small Model Context Protocol server over stdio, so that coding agents can use PicSpec.

Run ``picspec mcp`` and register it with an MCP client. Every tool is a thin wrapper around the
command of the same name and takes the same environment variables for keys and models.
No dependency: the protocol's JSON-RPC subset needed for tools is implemented here.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from typing import Any, Callable, TextIO

from . import __version__

PROTOCOL = "2025-06-18"

_SPEC = {"type": "string", "description": "Path to the spec file or its folder. Default: the nearest PICSPEC.md."}
_IDS = {"type": "string", "description": "Rule ids, comma separated."}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str],
          argv: Callable[[dict[str, Any]], list[str]]) -> dict[str, Any]:
    return {"name": name, "description": description, "argv": argv,
            "inputSchema": {"type": "object", "properties": properties, "required": required}}


def _opt(args: dict[str, Any], *names: str) -> list[str]:
    out: list[str] = []
    for name in names:
        value = args.get(name)
        if value is True:
            out.append(f"--{name.replace('_', '-')}")
        elif value not in (None, False, ""):
            out += [f"--{name.replace('_', '-')}", str(value)]
    return out


TOOLS: list[dict[str, Any]] = [
    _tool("picspec_rules", "List the rules of the user's image spec with their check questions. Call this "
          "first to learn what every image for this user must satisfy.",
          {"spec": _SPEC}, [], lambda a: ["lint", *([a["spec"]] if a.get("spec") else [])]),
    _tool("picspec_compile", "Turn a short image prompt into the full prompt that applies the user's spec, "
          "without generating anything. Use the result as the prompt for any image tool.",
          {"prompt": {"type": "string"}, "spec": _SPEC, "only": _IDS, "skip": _IDS, "backend": {"type": "string"}},
          ["prompt"], lambda a: ["compile", a["prompt"], "--json", *_opt(a, "spec", "only", "skip", "backend")]),
    _tool("picspec_generate", "Generate an image that follows the user's spec. With check, every rule is "
          "verified on the result and failures are repaired. Returns the saved file paths.",
          {"prompt": {"type": "string"}, "spec": _SPEC, "check": {"type": "boolean"},
           "rounds": {"type": "integer"}, "out": {"type": "string", "description": "Output folder."},
           "size": {"type": "string", "description": "WIDTHxHEIGHT"}, "quality": {"type": "string"},
           "only": _IDS, "skip": _IDS},
          ["prompt"], lambda a: ["generate", a["prompt"],
                                 *_opt(a, "spec", "check", "rounds", "out", "size", "quality", "only", "skip")]),
    _tool("picspec_check", "Check existing image files against the user's spec, rule by rule.",
          {"images": {"type": "array", "items": {"type": "string"}}, "spec": _SPEC, "only": _IDS, "skip": _IDS},
          ["images"], lambda a: ["check", *a["images"], "--json", *_opt(a, "spec", "only", "skip")]),
    _tool("picspec_learn", "Turn the user's feedback on an image into a proposed change to their spec. "
          "Shows a diff; pass apply only after the user has agreed to the change.",
          {"feedback": {"type": "string"}, "image": {"type": "string"}, "spec": _SPEC, "apply": {"type": "boolean"}},
          ["feedback"], lambda a: ["learn", a["feedback"], *_opt(a, "image", "spec", "apply")]),
    _tool("picspec_library", "List ready-made rules that can be added to a spec, by category.",
          {"category": {"type": "string"}, "lang": {"type": "string", "enum": ["en", "zh"]}},
          [], lambda a: ["rules", *_opt(a, "category", "lang")]),
]
_BY_NAME = {t["name"]: t for t in TOOLS}


def call_tool(name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    """Run one tool. Returns (text, is_error)."""
    from .cli import main

    tool = _BY_NAME.get(name)
    if tool is None:
        return f"unknown tool {name}", True
    out, err = io.StringIO(), io.StringIO()
    try:
        argv = tool["argv"](arguments)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
    except SystemExit as e:  # argparse rejected the arguments
        code = e.code if isinstance(e.code, int) else 2
    except KeyError as e:
        return f"missing argument {e}", True
    except Exception as e:  # a tool must answer, not take the server down
        return f"{type(e).__name__}: {e}", True
    text = out.getvalue().strip()
    notes = err.getvalue().strip()
    if code == 2 or (code and not text):
        return notes or text or f"picspec exited with code {code}", True
    if code == 1:
        text += "\n\n(At least one must-level rule is not met.)"
    return (text + ("\n\n" + notes if notes else "")).strip(), False


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """Answer one JSON-RPC message. Notifications get no answer."""
    method, msg_id = message.get("method"), message.get("id")
    if msg_id is None:
        return None
    params = message.get("params") or {}
    if method == "initialize":
        result: Any = {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                       "capabilities": {"tools": {}},
                       "serverInfo": {"name": "picspec", "version": __version__}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{k: v for k, v in t.items() if k != "argv"} for t in TOOLS]}
    elif method == "tools/call":
        text, bad = call_tool(str(params.get("name")), params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": text}], "isError": bad}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for stream in (stdin, stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None,
                                            "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(message) if isinstance(message, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
