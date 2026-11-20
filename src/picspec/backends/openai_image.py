"""gpt-image-2 and other models behind an OpenAI-style images API.

Without reference images the request goes to ``/images/generations`` as JSON.
With reference images it goes to ``/images/edits`` as multipart form data, one
``image[]`` part per reference (the API accepts up to 16).
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from PIL import Image

from ..request import Request
from .base import Backend, Capabilities, Rendered

QUALITIES = ("low", "medium", "high", "auto")
_SENDABLE = {"image/png", "image/jpeg", "image/webp"}


def check_size(width: int, height: int) -> None:
    """Raise ``ValueError`` when gpt-image-2 would reject this size."""
    if width % 16 or height % 16:
        raise ValueError(f"size {width}x{height}: width and height must both be divisible by 16")
    if not 1 / 3 <= width / height <= 3:
        raise ValueError(f"size {width}x{height}: the aspect ratio must be between 1:3 and 3:1")
    if max(width, height) > 3840 or min(width, height) > 2160:
        raise ValueError(f"size {width}x{height}: the largest size is 3840x2160")


class OpenAIImageBackend(Backend):
    caps = Capabilities(max_references=16, edit=True)

    def __init__(
        self,
        model: str = "gpt-image-2",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        quality: str | None = None,
        image_field: str = "image[]",
        extra_body: dict[str, Any] | None = None,
        timeout: float = 300.0,
        max_retries: int = 3,
        retry_wait: float = 2.0,
    ) -> None:
        self.model = self.name = model
        self.api_key, self.base_url = api_key, base_url.rstrip("/")
        self.quality, self.image_field = quality, image_field
        self.extra_body = extra_body or {}
        self.timeout, self.max_retries, self.retry_wait = timeout, max_retries, retry_wait

    # -- request building ---------------------------------------------------
    def fields(self, request: Request, rendered: Rendered) -> dict[str, Any]:
        """The API parameters, without the images."""
        body: dict[str, Any] = {"model": self.model, "prompt": rendered.prompt, "n": 1}
        if request.size:
            check_size(*request.size)
            body["size"] = f"{request.size[0]}x{request.size[1]}"
        quality = request.quality or self.quality
        if quality:
            if quality not in QUALITIES:
                raise ValueError(f"quality must be one of {', '.join(QUALITIES)}, not {quality!r}")
            body["quality"] = quality
        body.update(self.extra_body)
        return body

    def _run(self, request: Request, rendered: Rendered) -> tuple[Image.Image, dict[str, Any]]:
        return self._send(request, rendered, [_file_part(r.path) for r in rendered.references])

    def _edit(self, image: Image.Image, request: Request,
              rendered: Rendered) -> tuple[Image.Image, dict[str, Any]]:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        first = ("image.png", "image/png", buf.getvalue())
        return self._send(request, rendered, [first, *(_file_part(r.path) for r in rendered.references)])

    def _send(self, request: Request, rendered: Rendered,
              files: list[tuple[str, str, bytes]]) -> tuple[Image.Image, dict[str, Any]]:
        if not self.api_key and "api.openai.com" in self.base_url:
            raise RuntimeError("No API key. Set OPENAI_API_KEY (or PICSPEC_OPENAI_API_KEY), or pass --api-key.")
        fields = self.fields(request, rendered)
        if files:
            body, content_type = encode_multipart(fields, [(self.image_field, *f) for f in files])
            path = "/images/edits"
        else:
            body, content_type, path = json.dumps(fields).encode("utf-8"), "application/json", "/images/generations"
        data = self._post(path, body, content_type)
        try:
            image = decode_image(data, self._download)
        except (ValueError, OSError) as e:
            raise RuntimeError(f"{self.model}: {e}") from e
        meta = {"endpoint": path, "model": self.model}
        if isinstance(data.get("usage"), dict):
            meta["usage"] = data["usage"]
        return image, meta

    # -- HTTP ---------------------------------------------------------------
    def _open(self, req: urllib.request.Request) -> bytes:
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    def _post(self, path: str, body: bytes, content_type: str) -> dict[str, Any]:
        headers = {"Content-Type": content_type}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        last = "no attempt was made"
        for attempt in range(self.max_retries):
            req = urllib.request.Request(self.base_url + path, data=body, headers=headers, method="POST")
            try:
                return json.loads(self._open(req))
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {_error_text(e.read())}"
                if e.code < 500 and e.code != 429:
                    break  # our request is wrong; sending it again will not help
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                last = f"{type(e).__name__}: {e}"
            if attempt + 1 < self.max_retries:
                time.sleep(self.retry_wait * (attempt + 1))
        raise RuntimeError(f"{self.model} request to {path} failed. {last}")

    def _download(self, url: str) -> bytes:
        # Some gateways answer with a URL on third-party storage: never send the API key there.
        return self._open(urllib.request.Request(url, method="GET"))


def _error_text(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")
    try:
        err = json.loads(text).get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:500]
    except (ValueError, AttributeError):
        pass
    return text[:500]


def _file_part(path) -> tuple[str, str, bytes]:
    """Return (filename, mime type, bytes) for a reference image, converting odd formats to PNG."""
    mime = mimetypes.guess_type(path.name)[0]
    if mime in _SENDABLE:
        return path.name, mime, path.read_bytes()
    buf = io.BytesIO()
    with Image.open(path) as im:
        im.convert("RGBA" if "A" in im.getbands() else "RGB").save(buf, format="PNG")
    return path.stem + ".png", "image/png", buf.getvalue()


def encode_multipart(fields: dict[str, Any], files: list[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    """Encode form fields and ``(field, filename, mime, data)`` files. Returns (body, content type)."""
    boundary = f"picspec{uuid.uuid4().hex}"
    out = io.BytesIO()
    for key, value in fields.items():
        text = value if isinstance(value, str) else json.dumps(value)
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        out.write(text.encode("utf-8") + b"\r\n")
    for name, filename, mime, data in files:
        safe = filename.encode("ascii", "replace").decode().replace('"', "_")
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{safe}"\r\n'
                  f"Content-Type: {mime}\r\n\r\n".encode())
        out.write(data + b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def decode_image(data: dict[str, Any], fetch=None) -> Image.Image:
    items = data.get("data") or []
    item = items[0] if items and isinstance(items[0], dict) else {}
    if item.get("b64_json"):
        raw = base64.b64decode(item["b64_json"])
    elif str(item.get("url", "")).startswith("data:"):
        raw = base64.b64decode(item["url"].split(",", 1)[1])
    elif item.get("url") and fetch is not None:
        raw = fetch(item["url"])
    else:
        raise ValueError(f"the API answered without an image: {json.dumps(data)[:300]}")
    image = Image.open(io.BytesIO(raw))
    image.load()
    return image
