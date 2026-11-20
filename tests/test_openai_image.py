import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PIL import Image

from picspec import bare_request, build_request, loads
from picspec.backends.openai_image import OpenAIImageBackend, check_size, encode_multipart


def png_bytes(color=(10, 200, 30), size=(48, 32), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def api():
    state = {"requests": [], "replies": []}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["requests"].append({"path": self.path, "type": self.headers["Content-Type"],
                                      "auth": self.headers.get("Authorization"), "body": body})
            code, payload = state["replies"].pop(0) if state["replies"] else (
                200, {"data": [{"b64_json": base64.b64encode(png_bytes()).decode()}],
                      "usage": {"total_tokens": 42}})
            out = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):
            state["requests"].append({"path": self.path, "auth": self.headers.get("Authorization")})
            out = png_bytes((1, 2, 3))
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()


def backend(api, **kw):
    return OpenAIImageBackend(api_key="sk-test", base_url=api["url"] + "/v1", retry_wait=0, **kw)


def test_text_only_request_uses_generations(api):
    spec = loads("---\nsize: 1024x1536\nquality: high\n---\n## Look\n- `t1` Fine grain\n")
    result = backend(api).generate(build_request(spec, "a cat", seed=5))
    sent = api["requests"][0]
    body = json.loads(sent["body"])
    assert sent["path"] == "/v1/images/generations" and sent["auth"] == "Bearer sk-test"
    assert body == {"model": "gpt-image-2", "prompt": result.rendered.prompt, "n": 1,
                    "size": "1024x1536", "quality": "high"}  # no seed, no response_format
    assert "Fine grain" in body["prompt"]
    assert result.image.size == (48, 32)
    assert result.meta["usage"] == {"total_tokens": 42} and result.meta["endpoint"] == "/images/generations"


def test_references_go_to_edits_as_image_array(api, tmp_path):
    (tmp_path / "refs").mkdir()
    (tmp_path / "refs" / "grain.png").write_bytes(png_bytes())
    (tmp_path / "refs" / "pose.jpg").write_bytes(png_bytes(fmt="JPEG"))
    Image.new("RGB", (8, 8)).save(tmp_path / "refs" / "old.bmp")
    path = tmp_path / "PICSPEC.md"
    path.write_text("- `t1` Fine grain\n  - ref: refs/grain.png | grain like this\n"
                    "- `c1` Faces left\n  - ref: refs/pose.jpg\n  - ref: refs/old.bmp\n", encoding="utf-8")
    from picspec import load
    backend(api).generate(build_request(load(path), "a cat"))
    sent = api["requests"][0]
    assert sent["path"] == "/v1/images/edits" and sent["type"].startswith("multipart/form-data; boundary=")
    body = sent["body"]
    assert body.count(b'name="image[]"') == 3
    assert b'filename="grain.png"\r\nContent-Type: image/png' in body
    assert b'filename="pose.jpg"\r\nContent-Type: image/jpeg' in body
    assert b'filename="old.png"\r\nContent-Type: image/png' in body  # bmp is converted
    assert b'name="model"\r\n\r\ngpt-image-2\r\n' in body and b'name="n"\r\n\r\n1\r\n' in body
    assert "- Image 1: grain like this".encode() in body


def test_missing_reference_fails_before_any_request(api, tmp_path):
    spec = loads("- grain\n  - ref: refs/nope.png\n", path=tmp_path / "PICSPEC.md")
    with pytest.raises(FileNotFoundError, match="nope.png"):
        backend(api).generate(build_request(spec, "x"))
    assert not api["requests"]


def test_retries_server_errors_but_not_bad_requests(api):
    api["replies"] = [(500, {"error": {"message": "overloaded"}}), (429, {"error": {"message": "slow down"}})]
    backend(api).generate(bare_request("a cat"))
    assert len(api["requests"]) == 3

    api["requests"].clear()
    api["replies"] = [(400, {"error": {"message": "Invalid size"}})]
    with pytest.raises(RuntimeError, match="HTTP 400: Invalid size"):
        backend(api).generate(bare_request("a cat"))
    assert len(api["requests"]) == 1


def test_gateway_url_reply_is_downloaded_without_the_key(api):
    api["replies"] = [(200, {"data": [{"url": api["url"] + "/files/out.png"}]})]
    result = backend(api).generate(bare_request("a cat"))
    assert result.image.getpixel((0, 0)) == (1, 2, 3)
    assert api["requests"][1] == {"path": "/files/out.png", "auth": None}


def test_reply_without_image_is_an_error(api):
    api["replies"] = [(200, {"data": []})] * 3
    with pytest.raises(RuntimeError, match="without an image"):
        backend(api).generate(bare_request("a cat"))


def test_size_and_quality_are_checked_locally(api):
    check_size(1536, 864)
    for bad in [(1000, 1000), (4096, 1024), (1024, 4096), (3840, 2304)]:
        with pytest.raises(ValueError):
            check_size(*bad)
    with pytest.raises(ValueError, match="quality"):
        backend(api).generate(bare_request("x", quality="ultra"))
    assert not api["requests"]


def test_missing_key_for_openai_is_explained():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIImageBackend().generate(bare_request("x"))


def test_multipart_encoding():
    body, ctype = encode_multipart({"prompt": "猫", "n": 1}, [("image[]", 'a"b.png', "image/png", b"\x89PNG")])
    boundary = ctype.split("boundary=")[1]
    assert body.endswith(f"--{boundary}--\r\n".encode())
    assert 'name="prompt"\r\n\r\n猫\r\n'.encode() in body and b'filename="a_b.png"' in body
