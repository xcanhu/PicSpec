"""PicSpec nodes for ComfyUI.

Install: copy or symlink this folder into ComfyUI/custom_nodes/picspec and run
``pip install picspec`` (or ``pip install -e .`` from this repository) in ComfyUI's Python.

* PicSpec Prompt: your short prompt plus a PICSPEC.md become the positive and negative text.
  Wire them into the CLIP Text Encode nodes of any workflow.
* PicSpec Check: checks a finished image against the same spec with a vision model and returns
  a report, so a workflow can show it or branch on the result.
"""

from __future__ import annotations

from typing import Any


def _load(spec_path: str):
    from pathlib import Path

    from picspec.spec import SPEC_FILENAME, find, load

    path = Path(spec_path.strip()) if spec_path.strip() else find()
    if path is None:
        raise ValueError("No spec given and no PICSPEC.md found. Set spec_path to your PICSPEC.md.")
    if path.is_dir():
        path = path / SPEC_FILENAME
    return load(path)


def _ids(text: str) -> list[str] | None:
    ids = [s.strip() for s in text.split(",") if s.strip()]
    return ids or None


class PicSpecPrompt:
    CATEGORY = "PicSpec"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive", "negative")

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {"prompt": ("STRING", {"multiline": True, "default": ""}),
                             "spec_path": ("STRING", {"default": "PICSPEC.md"})},
                "optional": {"only": ("STRING", {"default": ""}), "skip": ("STRING", {"default": ""})}}

    def build(self, prompt: str, spec_path: str, only: str = "", skip: str = "") -> tuple[str, str]:
        from picspec.backends.base import render_compact
        from picspec.request import build_request

        request = build_request(_load(spec_path), prompt, only=_ids(only), skip=_ids(skip) or ())
        return render_compact(request), ", ".join(request.negatives)


class PicSpecCheck:
    CATEGORY = "PicSpec"
    FUNCTION = "check"
    RETURN_TYPES = ("STRING", "BOOLEAN")
    RETURN_NAMES = ("report", "passed")
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {"image": ("IMAGE",), "spec_path": ("STRING", {"default": "PICSPEC.md"}),
                             "judge_model": ("STRING", {"default": ""})},
                "optional": {"judge_base_url": ("STRING", {"default": ""}),
                             "judge_api_key": ("STRING", {"default": ""})}}

    def check(self, image: Any, spec_path: str, judge_model: str, judge_base_url: str = "",
              judge_api_key: str = "") -> tuple[str, bool]:
        from PIL import Image

        from picspec.judge import check_image
        from picspec.llm import make_judge

        spec = _load(spec_path)
        judge = make_judge(judge_model.strip() or spec.settings.get("judge"), judge_base_url.strip() or None,
                           judge_api_key.strip() or None)
        frame = image[0] if getattr(image, "ndim", 3) == 4 else image  # ComfyUI images are [batch, h, w, c] in 0..1
        array = (frame.cpu().numpy() if hasattr(frame, "cpu") else frame)
        pil = Image.fromarray((array * 255).clip(0, 255).astype("uint8"))
        report = check_image(pil, spec, judge)
        lines = [f"{v.status:<5} {v.rule_id}: {spec.rule(v.rule_id).text}" + (f"  ({v.seen})" if v.failed else "")
                 for v in report.verdicts]
        met, applied = report.counts
        return f"{met}/{applied} rules met\n" + "\n".join(lines), report.ok


NODE_CLASS_MAPPINGS = {"PicSpecPrompt": PicSpecPrompt, "PicSpecCheck": PicSpecCheck}
NODE_DISPLAY_NAME_MAPPINGS = {"PicSpecPrompt": "PicSpec Prompt", "PicSpecCheck": "PicSpec Check"}
