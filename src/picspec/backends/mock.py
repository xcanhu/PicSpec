"""A backend that draws a flat colour. For tests and for trying the CLI without a key or a GPU."""

from __future__ import annotations

import hashlib
from typing import Any

from PIL import Image

from ..request import Request
from .base import Backend, Capabilities, Rendered


class MockBackend(Backend):
    name = "mock"
    caps = Capabilities(max_references=4, negative_prompt=True, seed=True)

    def _run(self, request: Request, rendered: Rendered) -> tuple[Image.Image, dict[str, Any]]:
        digest = hashlib.sha256(f"{rendered.prompt}|{request.seed}".encode("utf-8")).digest()
        size = request.size or (256, 256)
        return Image.new("RGB", size, tuple(digest[:3])), {"seed": request.seed}
