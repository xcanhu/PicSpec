"""A small client for OpenAI-style ``/chat/completions`` servers (standard library only).

Works with OpenAI, DashScope, OpenRouter, vLLM, Ollama, LM Studio and API
gateways. Images are sent inline as data URLs.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from PIL import Image


class ChatModel(Protocol):
    def chat(self, system: str, user: str, images: list[Image.Image] | None = None) -> str: ...


def image_to_data_url(image: Image.Image, max_side: int = 1536) -> str:
    img = image.convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


@dataclass
class OpenAIChat:
    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    temperature: float | None = 0.0
    timeout: float = 120.0
    max_retries: int = 3
    retry_wait: float = 2.0
    max_image_side: int = 1536
    extra_body: dict[str, Any] | None = None

    def chat(self, system: str, user: str, images: list[Image.Image] | None = None) -> str:
        content: Any = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": image_to_data_url(im, self.max_image_side)}}
                for im in images
            ]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            **(self.extra_body or {}),
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = self.base_url.rstrip("/") + "/chat/completions"

        last = "no attempt was made"
        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read())
                return payload["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                last = f"HTTP {e.code}: {detail}"
                if e.code == 400 and "temperature" in detail.lower() and "temperature" in body:
                    del body["temperature"]  # some models only accept their default temperature
                    continue
                if e.code < 500 and e.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as e:
                last = f"{type(e).__name__}: {e}"
            if attempt + 1 < self.max_retries:
                time.sleep(self.retry_wait * (attempt + 1))
        raise RuntimeError(f"{self.model} chat request failed. {last}")


def make_judge(model: str | None = None, base_url: str | None = None, api_key: str | None = None) -> OpenAIChat:
    """Build the vision model that checks images. Missing values come from the environment."""

    def env(key: str) -> str | None:
        return next((os.environ[n] for n in (f"PICSPEC_JUDGE_{key}", f"PICSPEC_OPENAI_{key}", f"OPENAI_{key}")
                     if os.environ.get(n)), None)

    model = model or os.environ.get("PICSPEC_JUDGE_MODEL")
    if not model:
        raise ValueError("Checking needs a vision model. Pass --judge MODEL, set PICSPEC_JUDGE_MODEL, "
                         "or add `judge: MODEL` to the settings at the top of the spec.")
    return OpenAIChat(model=model, base_url=base_url or env("BASE_URL") or "https://api.openai.com/v1",
                      api_key=api_key or env("API_KEY"))


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Parse the first JSON object in a model reply, which may be fenced or wrapped in prose."""
    text = text.strip()
    candidates = [text] + [m.group(1).strip() for m in _FENCE.finditer(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for cand in candidates:
        try:
            return json.loads(cand)
        except ValueError:
            continue
    raise ValueError(f"no JSON in the model reply: {text[:200]!r}")
