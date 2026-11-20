"""Generate on your own machine through a running ComfyUI server.

Export a workflow with "Save (API Format)" and put placeholders where values
go: "%prompt%" (required), and optionally "%negative%", "%seed%", "%width%",
"%height%". A value that is exactly a placeholder is replaced with the right
type (numbers stay numbers); a placeholder inside a longer string is replaced
as text. Any model ComfyUI can run works, including GGUF builds for 8 GB cards.
"""

from __future__ import annotations

import copy
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from ..request import Request
from .base import Backend, Capabilities, Rendered, pick_references, render_compact


def fill_workflow(workflow: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``workflow`` with placeholders replaced by ``values``."""

    def sub(v: Any) -> Any:
        if isinstance(v, str):
            for key, val in values.items():
                token = f"%{key}%"
                if v == token:
                    return val
                if token in v:
                    v = v.replace(token, str(val))
            return v
        if isinstance(v, list):
            return [sub(x) for x in v]
        if isinstance(v, dict):
            return {k: sub(x) for k, x in v.items()}
        return v

    return sub(copy.deepcopy(workflow))


class ComfyUIBackend(Backend):
    def __init__(
        self,
        workflow: str | Path | dict[str, Any],
        url: str = "http://127.0.0.1:8188",
        default_size: tuple[int, int] = (1024, 1024),
        timeout: float = 900.0,
        poll_interval: float = 1.0,
    ) -> None:
        if isinstance(workflow, (str, Path)):
            path = Path(workflow)
            self.workflow = json.loads(path.read_text(encoding="utf-8"))
            self.name = f"comfyui:{path.stem}"
        else:
            self.workflow, self.name = workflow, "comfyui"
        if "nodes" in self.workflow and "links" in self.workflow:
            raise ValueError('This is a UI-format workflow. In ComfyUI use "Save (API Format)" and pass that file.')
        text = json.dumps(self.workflow)
        if "%prompt%" not in text:
            raise ValueError('The workflow needs a "%prompt%" placeholder.')
        self.caps = Capabilities(max_references=0, negative_prompt="%negative%" in text, seed="%seed%" in text)
        self.url = url.rstrip("/")
        self.default_size = default_size
        self.timeout, self.poll_interval = timeout, poll_interval
        self.client_id = uuid.uuid4().hex

    def render(self, request: Request) -> Rendered:
        kept, dropped = pick_references(request, 0)
        rendered = Rendered(prompt=render_compact(request), references=kept, dropped=dropped)
        if self.caps.negative_prompt:
            rendered.negative = ", ".join(request.negatives)
        elif request.negatives:
            rendered.notes.append('the workflow has no "%negative%" placeholder: negative terms are not sent')
        if dropped:
            rendered.notes.append(f"{self.name} does not take reference images yet: left out "
                                  f"{', '.join(r.path.name for r in dropped)}")
        return rendered

    # -- HTTP ---------------------------------------------------------------
    def _get(self, path: str) -> bytes:
        try:
            with urllib.request.urlopen(self.url + path, timeout=60) as resp:
                return resp.read()
        except urllib.error.URLError as e:
            raise RuntimeError(f"Cannot reach ComfyUI at {self.url}. Is it running? ({e})") from e

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self.url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:800]
            raise RuntimeError(f"ComfyUI rejected the workflow ({e.code}): {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Cannot reach ComfyUI at {self.url}. Is it running? ({e.reason})") from e

    # -- generation ---------------------------------------------------------
    def _run(self, request: Request, rendered: Rendered) -> tuple[Image.Image, dict[str, Any]]:
        width, height = request.size or self.default_size
        graph = fill_workflow(self.workflow, {
            "prompt": rendered.prompt, "negative": rendered.negative,
            "seed": request.seed, "width": width, "height": height,
        })
        queued = self._post("/prompt", {"prompt": graph, "client_id": self.client_id})
        if queued.get("node_errors"):
            raise RuntimeError(f"ComfyUI node errors: {json.dumps(queued['node_errors'])[:800]}")
        prompt_id = queued["prompt_id"]

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            entry = json.loads(self._get(f"/history/{prompt_id}")).get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI execution failed: {json.dumps(status.get('messages', []))[:800]}")
                images = [img for out in entry.get("outputs", {}).values() for img in out.get("images", [])]
                saved = [i for i in images if i.get("type") == "output"] or images
                if saved:
                    return self._download(saved[0]), {"seed": request.seed, "size": f"{width}x{height}"}
                if status.get("completed"):
                    raise RuntimeError("ComfyUI finished but the workflow produced no image (add a SaveImage node).")
            time.sleep(self.poll_interval)
        raise TimeoutError(f"ComfyUI did not finish within {self.timeout:.0f}s")

    def _download(self, info: dict[str, Any]) -> Image.Image:
        query = urllib.parse.urlencode(
            {"filename": info["filename"], "subfolder": info.get("subfolder", ""), "type": info.get("type", "output")}
        )
        image = Image.open(io.BytesIO(self._get(f"/view?{query}")))
        image.load()
        return image.convert("RGB")
