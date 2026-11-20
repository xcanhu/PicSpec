"""Image backends. ``make_backend`` builds one from a short name and options."""

from __future__ import annotations

import os
from typing import Any

from .base import Backend, Capabilities, Rendered, Result

DEFAULT_BACKEND = "gpt-image-2"


def _env(*names: str) -> str | None:
    return next((os.environ[n] for n in names if os.environ.get(n)), None)


def make_backend(name: str = DEFAULT_BACKEND, **options: Any) -> Backend:
    """Build a backend.

    ``name`` is ``mock``, ``comfyui`` (needs ``workflow=``, or write ``comfyui:path/to/workflow.json``),
    or the model id of an OpenAI-style images API such as ``gpt-image-2``.
    Options left as ``None`` fall back to environment variables.
    """
    options = {k: v for k, v in options.items() if v is not None}
    if name == "mock":
        from .mock import MockBackend
        return MockBackend()
    if name == "comfyui" or name.startswith("comfyui:"):
        from .comfyui import ComfyUIBackend
        workflow = options.get("workflow") or name.partition(":")[2] or _env("PICSPEC_COMFYUI_WORKFLOW")
        if not workflow:
            raise ValueError("The comfyui backend needs a workflow: pass --workflow FILE "
                             "(a workflow saved with \"Save (API Format)\").")
        url = options.get("base_url") or _env("PICSPEC_COMFYUI_URL") or "http://127.0.0.1:8188"
        return ComfyUIBackend(workflow, url=url)
    from .openai_image import OpenAIImageBackend
    return OpenAIImageBackend(
        model=name,
        api_key=options.get("api_key") or _env("PICSPEC_OPENAI_API_KEY", "OPENAI_API_KEY"),
        base_url=options.get("base_url") or _env("PICSPEC_OPENAI_BASE_URL", "OPENAI_BASE_URL")
        or "https://api.openai.com/v1",
        quality=options.get("quality"),
    )


__all__ = ["Backend", "Capabilities", "Rendered", "Result", "DEFAULT_BACKEND", "make_backend"]
