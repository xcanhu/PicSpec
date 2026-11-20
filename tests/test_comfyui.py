import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from picspec import build_request, loads
from picspec.backends import make_backend
from picspec.backends.comfyui import ComfyUIBackend, fill_workflow

WF = {
    "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "%prompt%"}},
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "%negative%"}},
    "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": "%width%", "height": "%height%"}},
    "7": {"class_type": "KSampler", "inputs": {"seed": "%seed%", "steps": 4}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "run-%seed%"}},
}
SPEC = "## Look\n- Fine grain\n  - ref: refs/g.png\n## Avoid\n- Watermarks\n  - negative: watermark, text\n"


def test_fill_workflow_keeps_types():
    g = fill_workflow(WF, {"prompt": "a cat", "seed": 7, "width": 512, "height": 768})
    assert g["4"]["inputs"]["text"] == "a cat"
    assert g["7"]["inputs"]["seed"] == 7 and g["6"]["inputs"]["width"] == 512
    assert g["9"]["inputs"]["filename_prefix"] == "run-7"
    assert WF["7"]["inputs"]["seed"] == "%seed%"  # original untouched


def test_rejects_bad_workflows():
    with pytest.raises(ValueError, match="API Format"):
        ComfyUIBackend({"nodes": [], "links": []})
    with pytest.raises(ValueError, match="%prompt%"):
        ComfyUIBackend({"1": {"inputs": {"text": "fixed"}}})
    with pytest.raises(ValueError, match="--workflow"):
        make_backend("comfyui")


def test_render_is_one_paragraph_and_drops_references():
    rendered = ComfyUIBackend(WF).render(build_request(loads(SPEC, path="/s/PICSPEC.md"), "a cat"))
    assert rendered.prompt == "a cat. Fine grain. Avoid: Watermarks."
    assert rendered.negative == "watermark, text"
    assert not rendered.references and "g.png" in rendered.notes[0]

    no_negative = {k: v for k, v in WF.items() if k != "5"}
    rendered = ComfyUIBackend(no_negative).render(build_request(loads(SPEC), "a cat", skip=["t1"]))
    assert rendered.negative == "" and "%negative%" in rendered.notes[0]


def test_shipped_workflows_load():
    for path in (Path(__file__).parent.parent / "examples" / "comfyui").glob("*.json"):
        backend = make_backend(f"comfyui:{path}")
        assert backend.caps.negative_prompt and backend.caps.seed


@pytest.fixture
def fake_comfy():
    state = {"posted": None, "polls": 0}
    png = io.BytesIO()
    Image.new("RGB", (64, 32), (255, 0, 0)).save(png, format="PNG")

    class H(BaseHTTPRequestHandler):
        def _json(self, obj):
            out = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def do_POST(self):
            state["posted"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._json({"prompt_id": "abc", "node_errors": {}})

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/history/abc":
                state["polls"] += 1
                if state["polls"] < 2:
                    return self._json({})
                return self._json({"abc": {"status": {"status_str": "success", "completed": True}, "outputs": {
                    "9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}}}})
            assert u.path == "/view" and parse_qs(u.query)["filename"] == ["out.png"]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(png.getvalue())

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()


def test_generates_through_the_server(fake_comfy):
    backend = ComfyUIBackend(WF, url=fake_comfy["url"], poll_interval=0.01)
    result = backend.generate(build_request(loads(SPEC, path="/s/PICSPEC.md"), "a cat", seed=11, size=(512, 768)))
    graph = fake_comfy["posted"]["prompt"]
    assert graph["4"]["inputs"]["text"] == "a cat. Fine grain. Avoid: Watermarks."
    assert graph["5"]["inputs"]["text"] == "watermark, text"
    assert graph["7"]["inputs"]["seed"] == 11 and graph["6"]["inputs"] == {"width": 512, "height": 768}
    assert result.image.size == (64, 32) and result.meta["seed"] == 11


def test_unreachable_server_is_explained():
    backend = ComfyUIBackend(WF, url="http://127.0.0.1:9")
    with pytest.raises(RuntimeError, match="Is it running"):
        backend.generate(build_request(loads("- a\n"), "x"))
