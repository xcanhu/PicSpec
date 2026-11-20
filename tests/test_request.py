from pathlib import Path

import pytest

from picspec import build_request, loads
from picspec.backends import make_backend
from picspec.backends.base import pick_references, render_compact, render_text

SPEC = """\
---
size: 1024x1536
quality: high
---
# Look

35mm film.

## Avoid
- `f1` Watermarks
  - negative: watermark

## Image look
- `t1` Fine grain
  - ref: refs/grain.png | grain like this
- `t2` Sharp face
  - when: a person is visible
  - prompt: tack-sharp face
- `t3` Backlight
  - level: should
  - ref: refs/light.png

## Subject
- `c1` Faces left
  - ref: refs/pose.png
"""


def spec():
    return loads(SPEC, path="/specs/PICSPEC.md")


def test_request_carries_rules_settings_and_references():
    req = build_request(spec(), "  a girl in an alley ")
    assert req.prompt == "a girl in an alley" and req.summary == "35mm film."
    assert req.size == (1024, 1536) and req.quality == "high"
    assert req.rule_ids == ["t1", "t2", "t3", "c1", "f1"]  # forbid rules go last
    assert req.directives[1].text == "tack-sharp face"
    assert req.negatives == ["watermark"]
    assert [(r.path, r.note) for r in req.references][:2] == [
        (Path("/specs/refs/grain.png"), "grain like this"), (Path("/specs/refs/light.png"), "Backlight")]


def test_only_skip_and_overrides():
    s = spec()
    assert build_request(s, "x", only=["t1", "f1"]).rule_ids == ["t1", "f1"]
    req = build_request(s, "x", skip=["t1"], size=(512, 512), quality="low", seed=7)
    assert "t1" not in req.rule_ids and req.size == (512, 512) and req.quality == "low" and req.seed == 7
    with pytest.raises(KeyError, match="zz"):
        build_request(s, "x", skip=["zz"])


def test_structured_text_groups_rules():
    text = render_text(build_request(spec(), "a girl"))
    assert text.startswith("a girl\n\nOverall style: 35mm film.")
    look, subject, avoid, pref = (text.index(s) for s in (
        "Image look:", "Subject and composition:", "Must not appear in the image:", "Preferred when possible:"))
    assert look < subject < avoid < pref
    assert "- (only when this applies: a person is visible) tack-sharp face" in text
    assert text.index("- Backlight") > pref


def test_emphasized_rules_come_first():
    req = build_request(spec(), "a girl", emphasize=["c1"])
    text = render_text(req)
    assert text.index("Most important") < text.index("Image look:")
    assert text.count("Faces left") == 1 and "Subject and composition:" not in text
    assert render_compact(req).index("Faces left") < render_compact(req).index("Fine grain")


def test_no_rules_means_the_bare_prompt():
    assert render_text(build_request(loads("# Empty\n"), "a cat")) == "a cat"


def test_reference_limit_prefers_stressed_then_must():
    req = build_request(spec(), "x", emphasize=["t3"])
    kept, dropped = pick_references(req, 2)
    assert [r.rule_id for r in kept] == ["t1", "t3"] and [r.rule_id for r in dropped] == ["c1"]
    kept, dropped = pick_references(build_request(spec(), "x"), 2)
    assert [r.rule_id for r in kept] == ["t1", "c1"]


def test_mock_backend_render_lists_references_and_negatives():
    rendered = make_backend("mock").render(build_request(spec(), "x"))
    assert "- Image 1: grain like this" in rendered.prompt and "- Image 3: Faces left" in rendered.prompt
    assert rendered.negative == "watermark" and not rendered.dropped


def test_chinese_labels():
    zh = loads("# 规格\n\n胶片感。\n\n## 禁忌\n- 水印\n\n## 画面质感\n- 细颗粒\n  - 适用：有人物\n")
    req = build_request(zh, "小巷")
    assert "整体风格：胶片感。" in render_text(req) and "画面中不能出现：\n- 水印" in render_text(req)
    assert render_compact(req) == "小巷。胶片感。（仅当：有人物）细颗粒。避免：水印。"
