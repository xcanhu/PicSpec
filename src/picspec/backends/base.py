"""What every image backend has in common."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from ..request import Directive, Reference, Request


@dataclass(frozen=True)
class Capabilities:
    max_references: int = 0
    negative_prompt: bool = False
    seed: bool = False
    edit: bool = False


@dataclass
class Rendered:
    """Exactly what a backend will send for a request."""

    prompt: str
    negative: str = ""
    references: list[Reference] = field(default_factory=list)
    dropped: list[Reference] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Result:
    image: Image.Image
    rendered: Rendered
    meta: dict[str, Any] = field(default_factory=dict)


class Backend:
    """Base class for adapters. Subclasses set ``name`` and ``caps`` and implement ``_run``."""

    name = "backend"
    caps = Capabilities()

    def render(self, request: Request) -> Rendered:
        kept, dropped = pick_references(request, self.caps.max_references)
        rendered = Rendered(prompt=render_text(request, kept), references=kept, dropped=dropped)
        if self.caps.negative_prompt:
            rendered.negative = ", ".join(request.negatives)
        if dropped:
            limit = self.caps.max_references
            why = "takes no reference images" if limit == 0 else f"takes at most {limit} reference images"
            rendered.notes.append(f"{self.name} {why}: left out {', '.join(r.path.name for r in dropped)}")
        return rendered

    def generate(self, request: Request) -> Result:
        rendered = self.render(request)
        missing = [str(r.path) for r in rendered.references if not r.path.is_file()]
        if missing:
            raise FileNotFoundError(f"reference image not found: {', '.join(missing)}")
        image, meta = self._run(request, rendered)
        return Result(image=image, rendered=rendered, meta={"backend": self.name, **meta})

    def _run(self, request: Request, rendered: Rendered) -> tuple[Image.Image, dict[str, Any]]:
        raise NotImplementedError

    def render_repair(self, request: Request) -> Rendered:
        """What ``repair`` will send. The rules to fix are ``request.emphasize``."""
        wanted = Request(prompt=request.prompt, emphasize=request.emphasize, lang=request.lang,
                         references=[r for r in request.references if r.rule_id in request.emphasize])
        kept, dropped = pick_references(wanted, max(self.caps.max_references - 1, 0))  # slot 1 is the image itself
        return Rendered(prompt=render_repair(request, kept), references=kept, dropped=dropped)

    def repair(self, image: Image.Image, request: Request) -> Result:
        """Edit ``image`` so that the rules in ``request.emphasize`` are met, changing as little else as possible."""
        if not self.caps.edit:
            raise NotImplementedError(f"{self.name} cannot edit images")
        rendered = self.render_repair(request)
        missing = [str(r.path) for r in rendered.references if not r.path.is_file()]
        if missing:
            raise FileNotFoundError(f"reference image not found: {', '.join(missing)}")
        out, meta = self._edit(image, request, rendered)
        return Result(image=out, rendered=rendered, meta={"backend": self.name, **meta})

    def _edit(self, image: Image.Image, request: Request,
              rendered: Rendered) -> tuple[Image.Image, dict[str, Any]]:
        raise NotImplementedError


def pick_references(request: Request, limit: int) -> tuple[list[Reference], list[Reference]]:
    """Keep at most ``limit`` references: rules being stressed first, then must before should."""
    stressed = set(request.emphasize)
    ranked = sorted(request.references,
                    key=lambda r: (r.rule_id not in stressed, r.level != "must"))  # stable sort keeps file order
    merged: dict[str, Reference] = {}  # one entry per file, however many rules point at it
    for r in ranked:
        first = merged.get(str(r.path))
        if first is None:
            merged[str(r.path)] = Reference(r.path, r.note, r.rule_id, r.level)
        elif r.note and r.note not in first.note.split("; "):
            first.note = f"{first.note}; {r.note}" if first.note else r.note
    unique = list(merged.values())
    order = {str(r.path): n for n, r in reversed(list(enumerate(request.references)))}  # file order of first use
    kept = sorted(unique[:max(limit, 0)], key=lambda r: order[str(r.path)])
    return kept, unique[max(limit, 0):]


_TEXT = {
    "en": {
        "summary": "Overall style: {}",
        "intro": "Requirements for how the image must look. Meet every one of them; "
                 "they take priority over your default style.",
        "stress": "Most important (the previous attempt got these wrong):",
        "texture": "Image look:",
        "composition": "Subject and composition:",
        "other": "Other requirements:",
        "forbid": "Must not appear in the image:",
        "should": "Preferred when possible:",
        "refs": "Reference images. Use each one only for the aspect named, and do not copy its content:",
        "ref": "Image {n}: {note}",
        "when": "(only when this applies: {when}) ",
        "avoid": "Avoid: ",
        "sep": "; ",
        "repair": "Edit the attached image (image 1), which was made for this prompt: {prompt}\n"
                  "It is almost right. Change only what is needed to fix the points below. Keep everything else "
                  "as it is: the same person, clothing, scene, colours and overall look.",
        "fix": "Fix:",
        "remove": "Remove from the image: ",
        "keep": "Already right, do not change:",
        "still": "Still must not appear:",
        "repair_refs": "Further images, each a reference for one aspect only. Do not copy their content:",
    },
    "zh": {
        "summary": "整体风格：{}",
        "intro": "以下是对画面效果的要求，必须逐条满足，优先于你默认的风格。",
        "stress": "最重要（上一次没有做到）：",
        "texture": "画面质感：",
        "composition": "主体与构图：",
        "other": "其他要求：",
        "forbid": "画面中不能出现：",
        "should": "尽量做到：",
        "refs": "参考图。每张只参考说明的那一方面，不要照搬其中的内容：",
        "ref": "图 {n}：{note}",
        "when": "（仅当：{when}）",
        "avoid": "避免：",
        "sep": "；",
        "repair": "请编辑附带的图片（图 1），它是按这个提示词生成的：{prompt}\n"
                  "这张图已经基本正确。只改动修复下列问题所必需的部分，其余全部保持原样："
                  "同一个人物、服装、场景、色彩和整体观感。",
        "fix": "需要修复：",
        "remove": "从画面中去掉：",
        "keep": "已经做到，不要改动：",
        "still": "仍然不能出现：",
        "repair_refs": "其余图片是参考图，每张只参考说明的那一方面，不要照搬其中的内容：",
    },
}


def _labels(request: Request) -> dict[str, str]:
    return _TEXT["zh" if request.lang == "zh" else "en"]


def _line(d: Directive, t: dict[str, str]) -> str:
    return (t["when"].format(when=d.when) if d.when else "") + d.text


def render_text(request: Request, references: list[Reference] | None = None) -> str:
    """The structured prompt used for models that read long instructions well."""
    t = _labels(request)
    blocks: list[str] = [request.prompt]
    if request.summary:
        blocks.append(t["summary"].format(request.summary))

    stressed = [d for d in request.directives if d.rule_id in request.emphasize]
    rest = [d for d in request.directives if d.rule_id not in request.emphasize]
    groups: list[tuple[str, list[Directive]]] = [("stress", stressed)]
    for kind in ("texture", "composition", "other"):
        groups.append((kind, [d for d in rest if d.kind == kind and d.level == "must"]))
    groups.append(("forbid", [d for d in rest if d.kind == "forbid"]))
    groups.append(("should", [d for d in rest if d.kind != "forbid" and d.level != "must"]))
    sections = ["\n".join([t[key], *(f"- {_line(d, t)}" for d in items)]) for key, items in groups if items]
    if sections:
        blocks.append(t["intro"])
        blocks += sections

    if references:
        blocks.append("\n".join([t["refs"], *(f"- {t['ref'].format(n=n, note=r.note)}"
                                               for n, r in enumerate(references, 1))]))
    return "\n\n".join(blocks)


def render_repair(request: Request, references: list[Reference] | None = None) -> str:
    """The instruction for editing an image: fix the stressed rules, leave the rest alone."""
    t = _labels(request)
    broken = [d for d in request.directives if d.rule_id in request.emphasize]
    fine = [d for d in request.directives if d.rule_id not in request.emphasize]
    blocks = [t["repair"].format(prompt=request.prompt)]
    blocks.append("\n".join([t["fix"], *(f"- {t['remove'] if d.kind == 'forbid' else ''}{d.text}" for d in broken)]))
    keep = [d for d in fine if d.kind != "forbid"]
    if keep:
        blocks.append("\n".join([t["keep"], *(f"- {_line(d, t)}" for d in keep)]))
    still = [d for d in fine if d.kind == "forbid"]
    if still:
        blocks.append("\n".join([t["still"], *(f"- {d.text}" for d in still)]))
    if references:
        blocks.append("\n".join([t["repair_refs"], *(f"- {t['ref'].format(n=n, note=r.note)}"
                                                    for n, r in enumerate(references, 2))]))
    return "\n\n".join(blocks)


def render_compact(request: Request) -> str:
    """One paragraph, for models whose text encoders prefer plain descriptions over lists."""
    t = _labels(request)
    stressed = set(request.emphasize)
    ordered = sorted(request.directives, key=lambda d: d.rule_id not in stressed)
    wanted = [_line(d, t) for d in ordered if d.kind != "forbid"]
    unwanted = [_line(d, t) for d in ordered if d.kind == "forbid"]
    parts = [request.prompt, request.summary, t["sep"].join(wanted)]
    if unwanted:
        parts.append(t["avoid"] + t["sep"].join(unwanted))
    stop = "。" if request.lang == "zh" else ". "
    return stop.join(p.strip().rstrip(".。") for p in parts if p.strip()).strip() + stop.strip()
